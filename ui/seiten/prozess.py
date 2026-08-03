"""Arbeitsansicht eines Prozesses -- eine Implementierung für alle Prozesse.

Was Prozess A von Prozess B unterscheidet, steht vollständig in
`prozessregistry`: Bezeichnung, Zielsystem, Schrittfolge, fachliche Felder.
Diese Seite liest das und rendert es. Ein dritter Prozess braucht hier
keine Zeile.
"""

from __future__ import annotations

import streamlit as st

from config import CHECKPOINT_PFAD
from graph.vorgaenge import uebersicht
from prozessregistry import Prozesskonfiguration
from registry import REGISTRY, Aufsichtsmodus
from ui.shared import benutzer
from ui.shared import filter as filtern
from ui.shared import stil
from ui.shared.kontext import angemeldet, graph, verbindung
from ui.vorgaenge import liste
from ui.vorgaenge.schritte import schritte_fuer


def zeige(konfiguration: Prozesskonfiguration) -> None:
    stil.css()
    st.title(konfiguration.bezeichnung)
    st.caption(konfiguration.beschreibung)

    app, _ = graph()
    schluessel = f"prozess_{konfiguration.schluessel}"
    eigene = filtern.fuer_prozess(uebersicht(app, CHECKPOINT_PFAD),
                                  konfiguration.schluessel)

    con = verbindung()
    try:
        person = benutzer.lade(con, angemeldet())
    finally:
        con.close()

    zahlen = filtern.kennzahlen(eigene)
    spalten = st.columns(4)
    spalten[0].metric(person.label_offene, zahlen["offen"])
    spalten[1].metric("In Bearbeitung", zahlen["laeuft"])
    spalten[2].metric("Abgeschlossen", zahlen["abgeschlossen"])
    spalten[3].metric("Nicht abgeschlossen", zahlen["fehlgeschlagen"])
    st.caption(f"Am Ende steht: {konfiguration.prozessende} – "
               f"festgehalten in: {konfiguration.zielsystem}.")

    if not eigene:
        st.info(f"Hier liegt noch kein Vorgang. Laden Sie unter „Upload“ eine "
                f"{konfiguration.belegart} hoch.")
        _ablauf(konfiguration)
        return

    auswahl = liste.filterleiste(schluessel=schluessel,
                                 prozess_fest=konfiguration.schluessel)
    treffer = filtern.wende_an(eigene, auswahl)

    liste.abschnitt(
        filtern.offene(treffer), titel="In Bearbeitung",
        schluessel=f"{schluessel}_offen", darstellung="karten",
        leer="Zurzeit ist hier nichts in Bearbeitung.",
        konfiguration=konfiguration, filter_aktiv=not auswahl.ist_leer,
    )
    liste.abschnitt(
        filtern.abgeschlossene(treffer), titel="Erledigt",
        schluessel=f"{schluessel}_fertig",
        leer="Hier ist noch nichts erledigt.",
        konfiguration=konfiguration, filter_aktiv=not auswahl.ist_leer,
    )

    _ablauf(konfiguration)


def _ablauf(konfiguration: Prozesskonfiguration) -> None:
    """Die prozessbezogene Scheibe dessen, was die Architekturseite ganz zeigt."""
    with st.expander("So läuft dieser Vorgang ab"):
        stil.stepper(schritte_fuer(konfiguration.schluessel, []))
        for schritt in konfiguration.schritte:
            if not schritt.agent_id:
                continue
            cfg = REGISTRY[schritt.agent_id]
            if cfg.aufsicht is Aufsichtsmodus.HUMAN_IN_THE_LOOP:
                zusatz = "🔒 Eine Person muss diesen Schritt bestätigen."
            elif cfg.darf_schreiben:
                zusatz = "Wird automatisch ausgeführt und protokolliert."
            else:
                zusatz = "Wird automatisch ausgeführt, ohne etwas zu ändern."
            st.markdown(
                f'<div class="feldzeile"><b>{schritt.titel}</b> — {zusatz}</div>',
                unsafe_allow_html=True,
            )
        st.caption("Welche Rolle und welche Berechtigung hinter jedem Schritt "
                   "steht, zeigt die Seite „Architektur“.")
