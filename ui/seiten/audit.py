"""Seite 'Audit-Trail': der manipulationsgeschützte Nachweis.

Die Kettenprüfung steht oben und bezieht sich **immer** auf den vollständigen
Trail, nie auf die gefilterte Sicht: ein Filter darf keine Aussage über
Unversehrtheit erzeugen. Wird gefiltert, steht das ausdrücklich dabei.
"""

from __future__ import annotations

import csv
import io

import streamlit as st

import prozessregistry
from governance import ad
from governance.audit import lies_alle, verify_chain, vorgaenge_im_trail
from ui.shared import stil
from ui.shared.formate import zeitpunkt
from ui.shared.kontext import angemeldet, verbindung

SPALTEN = ["#", "Zeitpunkt", "Person oder System", "Schritt", "Beleg",
           "Bewertung", "Ergebnis", "Erläuterung", "Prüfsumme"]

# Die interne Bewertung eines Eintrags in Worten. 'info' heisst: weder erlaubt
# noch verweigert, sondern schlicht festgehalten.
BEWERTUNG = {"erlaubt": "Erlaubt", "verweigert": "Abgelehnt", "info": "Vermerk"}

# Komponenten, die keinen eigenen Prozessschritt haben und trotzdem
# protokollieren.
WEITERE_BETEILIGTE = {
    "orchestrator": "Weiterleitung",
    "policy": "Berechtigungsprüfung",
    "audit": "Protokollierung",
}


def _schrittname(agent_id: str | None) -> str:
    """Plain-Bezeichnung der Komponente, die den Eintrag geschrieben hat.

    Die handelnden Agenten tragen dieselbe Kennung wie ihr Knoten im Ablauf --
    fuer sie liefert die Prozessregistry den Namen. Die uebrigen Komponenten
    stehen in `WEITERE_BETEILIGTE`.
    """
    if not agent_id:
        return "—"
    if agent_id in WEITERE_BETEILIGTE:
        return WEITERE_BETEILIGTE[agent_id]
    return prozessregistry.schritt_titel(agent_id)


def _als_zeile(e) -> dict:
    return {
        "#": e.id,
        "Zeitpunkt": zeitpunkt(e.ts),
        "Person oder System": e.akteur,
        "Schritt": _schrittname(e.agent),
        "Beleg": e.datenquelle or "—",
        "Bewertung": BEWERTUNG.get(e.entscheidung.value, e.entscheidung.value),
        "Ergebnis": e.ergebnis or "—",
        "Erläuterung": e.begruendung,
        "Prüfsumme": e.hash[:12] + "…",
        "Vorgang": e.vorgang_id or "—",
    }


def seite() -> None:
    stil.css()
    st.title("Protokoll")
    st.caption("Jeder Schritt jedes Vorgangs wird hier festgehalten – auch "
               "abgelehnte Zugriffe und zurückgewiesene Uploads. Die Einträge "
               "lassen sich nachträglich nicht ändern.")

    upn = angemeldet()
    con = verbindung()
    try:
        kette = verify_chain(con)
        alle = lies_alle(con)
        bekannte_vorgaenge = vorgaenge_im_trail(con)
        darf_exportieren = ad.pruefe_freigabe_berechtigung(con, upn).erlaubt
    finally:
        con.close()

    if kette.gueltig:
        st.success(f"Das Protokoll ist unverändert – alle {kette.geprueft} "
                   "Einträge sind lückenlos.")
    else:
        st.error(f"Das Protokoll wurde nachträglich verändert. {kette}")

    if not alle:
        st.info("Noch keine Einträge vorhanden.")
        return

    # Aus einem Vorgang heraus vorbelegt (?vorgang=…).
    vorbelegt = st.query_params.get("vorgang")
    optionen = ["Alle", *bekannte_vorgaenge]
    index = optionen.index(vorbelegt) if vorbelegt in optionen else 0

    oben = st.columns([3, 3, 2, 2])
    suche = oben[0].text_input("Suche", placeholder="Person, Beleg, Erläuterung …")
    vorgang = oben[1].selectbox(
        "Vorgang", optionen, index=index,
        format_func=lambda v: v if v == "Alle" else v.rsplit("-", 1)[0])
    agenten = sorted({e.agent for e in alle if e.agent})
    agent = oben[2].selectbox(
        "Schritt", ["Alle", *agenten],
        format_func=lambda a: a if a == "Alle" else _schrittname(a))
    entscheidung = oben[3].selectbox(
        "Bewertung", ["Alle", "erlaubt", "verweigert", "info"],
        format_func=lambda e: e if e == "Alle" else BEWERTUNG[e])

    treffer = alle
    if vorgang != "Alle":
        treffer = [e for e in treffer if e.vorgang_id == vorgang]
    if agent != "Alle":
        treffer = [e for e in treffer if e.agent == agent]
    if entscheidung != "Alle":
        treffer = [e for e in treffer if e.entscheidung.value == entscheidung]
    if suche:
        begriff = suche.lower()
        treffer = [e for e in treffer if begriff in " ".join([
            e.akteur, e.agent or "", e.aktion, e.begruendung,
            e.datenquelle or "", e.ergebnis or ""]).lower()]

    gefiltert = len(treffer) != len(alle)
    if gefiltert:
        st.caption(f"{len(treffer)} von {len(alle)} Einträgen. Die Aussage "
                   "oben gilt für das vollständige Protokoll, nicht nur für "
                   "diese Auswahl.")

    st.dataframe([_als_zeile(e) for e in reversed(treffer)],
                 column_order=SPALTEN, use_container_width=True, hide_index=True)

    if darf_exportieren:
        st.download_button(
            "Auswahl als CSV herunterladen", _csv(treffer, kette),
            file_name="protokoll.csv", mime="text/csv",
        )
    else:
        st.caption("Zum Herunterladen des Protokolls ist Ihr Konto nicht "
                   "berechtigt.")


def _csv(eintraege, kette) -> str:
    """CSV mit Kettenstatus im Kopf.

    Der Status gehoert in die Datei: ein exportierter Auszug ohne die Aussage,
    ob die Kette intakt war, ist als Nachweis wertlos.
    """
    puffer = io.StringIO()
    puffer.write(f"# Protokollprüfung: {kette}\n")
    schreiber = csv.DictWriter(puffer, fieldnames=[*SPALTEN, "Vorgang"],
                               delimiter=";", extrasaction="ignore")
    schreiber.writeheader()
    for e in eintraege:
        schreiber.writerow(_als_zeile(e))
    return puffer.getvalue()
