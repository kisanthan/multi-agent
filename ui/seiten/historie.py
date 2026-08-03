"""Seite 'Historische Vorgänge': alle Vorgänge, prozessübergreifend.

Dieselbe Datenquelle wie die Prozessseiten -- nur ohne Prozessfilter. Die
Trennung ist keine Doppelung, sondern eine andere Frage: hier „was ist
insgesamt eingespeist worden", dort „wie steht dieser Prozess".
"""

from __future__ import annotations

import streamlit as st

from config import CHECKPOINT_PFAD
from graph.vorgaenge import uebersicht
from ui.shared import benutzer
from ui.shared import filter as filtern
from ui.shared import stil
from ui.shared.kontext import angemeldet, graph, verbindung
from ui.vorgaenge import liste

SCHLUESSEL = "historie"


def seite() -> None:
    stil.css()
    st.title("Alle Vorgänge")
    st.caption("Alle Zahlungseingänge und Eingangsrechnungen zusammen.")

    app, _ = graph()
    alle = uebersicht(app, CHECKPOINT_PFAD)

    con = verbindung()
    try:
        person = benutzer.lade(con, angemeldet())
    finally:
        con.close()

    if not alle:
        st.info("Noch keine Vorgänge. Laden Sie unter „Upload“ einen Beleg hoch.")
        return

    zahlen = filtern.kennzahlen(alle)
    spalten = st.columns(4)
    spalten[0].metric(person.label_offene, zahlen["offen"])
    spalten[1].metric("In Bearbeitung", zahlen["laeuft"])
    spalten[2].metric("Abgeschlossen", zahlen["abgeschlossen"])
    spalten[3].metric("Nicht abgeschlossen", zahlen["fehlgeschlagen"])

    auswahl = liste.filterleiste(schluessel=SCHLUESSEL)
    treffer = filtern.wende_an(alle, auswahl)

    liste.abschnitt(
        filtern.offene(treffer), titel="In Bearbeitung",
        schluessel=f"{SCHLUESSEL}_offen", darstellung="karten",
        leer="Zurzeit ist nichts in Bearbeitung.",
        filter_aktiv=not auswahl.ist_leer,
    )
    liste.abschnitt(
        filtern.abgeschlossene(treffer), titel="Erledigt",
        schluessel=f"{SCHLUESSEL}_fertig", leer="Noch nichts erledigt.",
        filter_aktiv=not auswahl.ist_leer,
    )
