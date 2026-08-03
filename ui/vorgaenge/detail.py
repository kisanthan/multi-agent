"""Detailansicht eines Vorgangs: Stepper, Freigabe, Bestaetigung.

Eine Ansicht fuer alle Prozesse -- was fachlich unterschiedlich ist (welche
Felder im Kopf stehen), kommt aus `prozessregistry`, nicht aus Fallunter-
scheidungen hier.
"""

from __future__ import annotations

import base64
from pathlib import Path

import streamlit as st

import prozessregistry
from agents import kostenstelle as kostenstelle_agent
from governance.audit import verify_chain
from governance.policy import pruefe_freigabe
from graph.vorgaenge import Status, prozess_von, status_von
from graph.wirkung import lies_wirkung
from ui.shared import stil
from ui.shared import benutzer
from ui.shared.formate import feld
from ui.shared.kontext import verbindung, zeige_audit_zu
from ui.vorgaenge.lauf import setze_fort
from ui.vorgaenge.schritte import schritte_fuer

# Welcher Agent fuer welchen Freigabepunkt zustaendig ist. Die Berechtigung
# gegen den falschen Agenten zu pruefen waere eine stille Umgehung der Policy.
AGENT_JE_INTERRUPT = {
    "klaerfall": "buchung",
    "kostenstellen_freigabe": "kostenstelle",
}

ERGEBNISTEXTE = {
    "verbucht": "Die Zahlung ist verbucht. Die Rechnung gilt als bezahlt.",
    "archiviert": "Die Rechnung ist revisionssicher abgelegt. Damit ist der "
                  "Vorgang beendet.",
    "verworfen": "Der Vorgang wurde abgelehnt. Es wurde nichts gebucht und "
                 "nichts abgelegt.",
    "zugriff_verweigert": "Der Beleg wurde nicht geöffnet: das Konto ist dazu "
                          "nicht berechtigt.",
    "abgelehnt": "Die Buchhaltung hat die Buchung abgelehnt.",
    "archivierung_fehlgeschlagen": "Die Ablage im Archiv ist fehlgeschlagen.",
}


def zeige(app, thread_id: str, *, upn: str, mit_titel: bool = True) -> None:
    """Rendert einen Vorgang vollstaendig."""
    schnappschuss = app.get_state({"configurable": {"thread_id": thread_id}})
    werte = schnappschuss.values or {}

    if not werte:
        st.warning("Zu diesem Vorgang liegen keine Daten vor. "
                   "Möglicherweise wurde er nie gestartet.")
        return

    anfrage = schnappschuss.interrupts[0].value if schnappschuss.interrupts else None
    status = status_von(werte, wartet=bool(anfrage))
    prozess = prozess_von(werte)

    _kopf(werte, status, prozess, thread_id, mit_titel=mit_titel)
    stil.stepper(schritte_fuer(prozess, werte.get("protokoll", []),
                               wartet_auf=(anfrage or {}).get("art"), status=status))

    if anfrage:
        _entscheidungsformular(app, thread_id, anfrage, werte, upn=upn)
    else:
        _ergebnis(werte, status)

    with st.expander("Was bisher geschah"):
        for schritt in werte.get("protokoll", []):
            st.markdown(
                f"**{prozessregistry.schritt_titel(schritt['knoten'])}** — "
                f"{schritt['text']}")

    _belegvorschau(werte.get("pfad"))

    if st.button("Protokoll zu diesem Vorgang", key=f"audit_{thread_id}",
                 use_container_width=False,
                 help="Zeigt alle protokollierten Schritte dieses Vorgangs"):
        zeige_audit_zu(thread_id)


def _kopf(werte: dict, status: Status, prozess: str | None, thread_id: str, *,
          mit_titel: bool) -> None:
    konfiguration = prozessregistry.konfiguration(prozess) if prozess else None
    # Die Belegart, nicht der Prozessname: hier steht ein einzelnes Dokument,
    # und „Zahlungsbestätigung" sagt darueber mehr als „Zahlungseingang". Kein
    # „Prozess A" -- die Zuordnung A/B steht auf der Architekturseite.
    prozesstext = (konfiguration.belegart if konfiguration
                   else "Belegart wird noch erkannt")

    if mit_titel:
        st.subheader(werte.get("dateiname") or thread_id)
    st.markdown(
        f"{stil.badge(status)} &nbsp; <span style='opacity:0.75'>{prozesstext}</span>",
        unsafe_allow_html=True,
    )

    # Welche Felder fachlich interessieren, weiss der Prozess.
    fachfelder = list(konfiguration.detailfelder) if konfiguration else ["nummer"]
    links, rechts = st.columns(2)
    with links:
        stil.felder(werte, ["akteur", "gestartet_am"])
    with rechts:
        stil.felder(werte, fachfelder)


def _entscheidungsformular(app, thread_id: str, anfrage: dict, werte: dict, *,
                           upn: str) -> None:
    """Hier haelt der Vorgang an, bis ein Mensch entscheidet."""
    art = anfrage.get("art", "")
    agent_id = AGENT_JE_INTERRUPT.get(art, "buchung")

    con = verbindung()
    try:
        person = benutzer.lade(con, upn)
        entscheid = pruefe_freigabe(con, akteur=upn, agent_id=agent_id)
    finally:
        con.close()

    # Was hier steht, haengt davon ab, wer zusieht: wer entscheiden darf, wird
    # aufgefordert; wer nicht, bekommt eine Einordnung statt einer Aufforderung.
    if entscheid.erlaubt:
        st.markdown("#### Ihre Entscheidung")
    else:
        st.markdown("#### Wartet auf Bestätigung")

    zeilen = "".join(
        f"<div class='feldzeile'><b>{feld(s, anfrage[s])[0]}:</b> "
        f"{feld(s, anfrage[s])[1]}</div>"
        for s in ("grund", "befund", "begruendung", "eskalation") if anfrage.get(s)
    )
    st.markdown(f'<div class="karte">{zeilen}</div>', unsafe_allow_html=True)

    if anfrage.get("positionen"):
        st.markdown("**Rechnungsposten:** " + ", ".join(anfrage["positionen"]))

    kostenstelle_id = None
    if art == "kostenstellen_freigabe":
        katalog = anfrage.get("katalog") or []
        if not katalog:
            con = verbindung()
            try:
                katalog = [{"id": z[0], "bezeichnung": z[1], "referenz": z[2]}
                           for z in kostenstelle_agent.katalog(con)]
            finally:
                con.close()
        labels = {e["id"]: f"{e['id']} — {e['bezeichnung']} ({e['referenz']})"
                  for e in katalog}
        st.warning("Auf dem Beleg steht keine Kostenstelle, die zugeordnet "
                   "werden konnte. Bitte wählen Sie die passende aus.")
        kostenstelle_id = st.selectbox(
            "Kostenstelle", [e["id"] for e in katalog],
            format_func=lambda o: labels.get(o, o), key=f"kst_{thread_id}",
        )

    if not entscheid.erlaubt:
        # Kein Fehlerbalken: fuer diese Person ist das kein Fehler, sondern
        # schlicht nicht ihre Aufgabe.
        st.info(person.hinweis_bestaetigen)
    elif werte.get("akteur") == upn:
        # Nur Hinweis. Technisch erzwungen wird bislang die
        # Gruppenmitgliedschaft (governance/policy.py) -- die Personengleichheit
        # zu verbieten waere eine Governance-Aenderung (docs/grenzen.md L10).
        st.warning(person.hinweis_eigener_beleg)

    links, rechts = st.columns(2)
    with links:
        freigeben = st.button("Bestätigen", key=f"f_{thread_id}", type="primary",
                              disabled=not entscheid.erlaubt, use_container_width=True)
    with rechts:
        verwerfen = st.button("Ablehnen", key=f"v_{thread_id}",
                              disabled=not entscheid.erlaubt, use_container_width=True)

    if verwerfen and not st.session_state.get(f"ablehnen_bestaetigt_{thread_id}"):
        st.session_state[f"ablehnen_bestaetigt_{thread_id}"] = True
        st.warning("Ablehnen beendet den Vorgang endgültig. Zum Fortfahren "
                   "erneut auf „Ablehnen“ klicken.")
        return

    if freigeben or verwerfen:
        antwort = {
            "entscheidung": "freigegeben" if freigeben else "verworfen",
            "pruefer": upn,
            "nummer": anfrage.get("nummer"),
        }
        if kostenstelle_id:
            antwort["kostenstelle_id"] = kostenstelle_id
        st.session_state.pop(f"ablehnen_bestaetigt_{thread_id}", None)
        setze_fort(app, thread_id=thread_id, antwort=antwort)
        st.rerun()


def _ergebnis(werte: dict, status: Status) -> None:
    """Abschlusskarte: was ist am Ende tatsaechlich passiert?"""
    if not werte.get("abgeschlossen"):
        st.info("Der Vorgang wird gerade bearbeitet.")
        return

    ergebnis = werte.get("ergebnis", "")
    text = ERGEBNISTEXTE.get(ergebnis, f"Vorgang beendet: {ergebnis or 'unbekannt'}")

    st.markdown("#### Ergebnis")
    if status is Status.ABGESCHLOSSEN:
        st.success(text)
    elif status is Status.VERWORFEN:
        st.warning(text)
    else:
        st.error(text)

    if werte.get("fehler"):
        st.caption(f"Rückmeldung: {werte['fehler']}")

    con = verbindung()
    try:
        wirkung = lies_wirkung(con, werte)
        kette = verify_chain(con)
    finally:
        con.close()

    if wirkung.hat_wirkung:
        spalten = st.columns(2)
        if wirkung.navision_status:
            spalten[0].metric(f"Rechnung {wirkung.navision_nummer}",
                              wirkung.navision_status.capitalize())
        if wirkung.elo_archiv_id:
            spalten[1].metric("Im Archiv abgelegt unter", wirkung.elo_archiv_id)

    if werte.get("freigegeben_von"):
        st.caption(f"Bestätigt von {werte['freigegeben_von']}")

    st.caption(
        "✓ Das Protokoll dieses Systems ist unverändert."
        if kette.gueltig else
        f"✕ Das Protokoll wurde nachträglich verändert. {kette}"
    )


def _belegvorschau(pfad: str | None) -> None:
    """Zeigt das Original-PDF -- ein Prüfer entscheidet nicht ohne den Beleg."""
    if not pfad or not Path(pfad).is_file():
        return
    with st.expander("Beleg ansehen"):
        daten = base64.b64encode(Path(pfad).read_bytes()).decode("ascii")
        st.markdown(
            f'<iframe src="data:application/pdf;base64,{daten}" '
            'width="100%" height="620" style="border:1px solid #ccc; '
            'border-radius:6px;"></iframe>',
            unsafe_allow_html=True,
        )
