"""Seite 'Upload': Belege einspeisen -- die Haupthandlung der Anwendung.

Aufbau bewusst zweigeteilt: oben der Upload-Bereich, der die Seite optisch
traegt, darunter klar abgetrennt die zuletzt eingespeisten Vorgaenge. Die
vollstaendige Liste mit Filtern lebt auf der Historienseite, damit der Upload
hier nicht in einer Tabelle untergeht.

Ein Upload ist noch kein Vorgang: die Verarbeitung dauert Minuten und startet
der Nutzer bewusst.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

import prozessregistry
from config import EINGANG_DIR, MANIFEST_PFAD
from graph.vorgaenge import uebersicht
from ui.shared import benutzer, stil
from ui.shared.formate import aufzaehlung, dateigroesse
from ui.shared.kontext import angemeldet, graph, oeffne_vorgang, verbindung
from ui.upload import ablage
from ui.vorgaenge import liste
from ui.vorgaenge.lauf import starte

ZULETZT = 5


def _manifest() -> dict[str, dict]:
    """Erwartungen zu den generierten Testbelegen, falls vorhanden.

    Hochgeladene Belege stehen nicht im Manifest -- die Seite muss ohne
    Manifesteintrag genauso funktionieren.
    """
    if not MANIFEST_PFAD.is_file():
        return {}
    return {d["dateiname"]: d
            for d in json.loads(MANIFEST_PFAD.read_text(encoding="utf-8"))}


# ------------------------------------------------------------- Upload-Bereich

def _uploadbereich(person) -> None:
    if not person.darf_hochladen:
        # Kein Fehlerbalken: das Konto ist nicht kaputt, es hat nur eine
        # andere Aufgabe.
        st.info(person.hinweis_hochladen)
        return

    # Die Beschriftung ist eingeklappt: die Ablageflaeche traegt ihren
    # Bedienhinweis selbst (siehe ui/shared/stil.py), eine Ueberschrift
    # daneben waere dieselbe Aussage zweimal.
    #
    # Der Schluessel ist nicht nur Zustandsschluessel: Streamlit haengt ihn als
    # CSS-Klasse `st-key-upload_belege` an den Container, und genau darueber
    # wird die Ablageflaeche gestaltet. Ein <div> per Markdown darum zu legen
    # funktioniert nicht -- Streamlit schliesst solche Bloecke sofort wieder.
    dateien = st.file_uploader(
        "Belege hierher ziehen oder auswählen",
        type=["pdf"], accept_multiple_files=True, key="upload_belege",
        label_visibility="collapsed",
    )

    if not dateien:
        return

    # Was Streamlit unterhalb der Flaeche auflistet, sind die gewaehlten
    # Dateien samt Entfernen-Knopf. Hier steht daneben etwas anderes: das
    # Ergebnis der Eingangspruefung -- also warum eine Datei durchgeht oder
    # nicht.
    st.markdown("**Eingangsprüfung**")
    con = verbindung()
    try:
        geprueft = [(d, ablage.pruefe(con, dateiname=d.name, daten=d.getvalue()))
                    for d in dateien]
    finally:
        con.close()

    for datei, pruefung in geprueft:
        spalten = st.columns([4, 2, 4])
        spalten[0].markdown(f"`{datei.name}`")
        spalten[1].caption(dateigroesse(len(datei.getvalue())))
        if pruefung.ok:
            spalten[2].caption("✓ " + pruefung.grund)
        else:
            spalten[2].caption("✕ " + pruefung.grund)

    annehmbar = [d for d, p in geprueft if p.ok]
    beschriftung = ("Beleg übernehmen" if len(annehmbar) == 1
                    else f"{len(annehmbar)} Belege übernehmen")
    knopf = st.button(
        beschriftung if annehmbar else "Übernehmen",
        type="primary", disabled=not annehmbar, use_container_width=True,
    )

    if knopf:
        con = verbindung()
        try:
            for datei, pruefung in geprueft:
                if pruefung.ok:
                    ablage.lege_ab(con, dateiname=datei.name,
                                   daten=datei.getvalue(), akteur=person.upn)
                else:
                    ablage.protokolliere_abweisung(
                        con, dateiname=datei.name, akteur=person.upn,
                        grund=pruefung.grund)
        finally:
            con.close()
        st.success("Übernommen. Die Verarbeitung starten Sie unten mit "
                   "„Starten“ – sie dauert ein bis drei Minuten.")
        # Widget leeren, sonst erscheint dieselbe Auswahl nach dem Rerun erneut.
        st.session_state.pop("upload_belege", None)
        st.rerun()


# ---------------------------------------------------------------- Belegliste

def _belegliste(upn: str, app) -> None:
    belege = sorted(EINGANG_DIR.glob("*.pdf")) if EINGANG_DIR.is_dir() else []
    if not belege:
        st.info("Noch keine Belege vorhanden. Laden Sie oben ein PDF hoch.")
        return

    manifest = _manifest()
    with st.expander(f"Bereitliegende Belege ({len(belege)})", expanded=not manifest):
        st.caption("„Starten“ legt einen neuen Vorgang an. Derselbe Beleg kann "
                   "mehrfach verarbeitet werden.")
        for beleg in belege:
            eintrag = manifest.get(beleg.name, {})
            kopf, knopf = st.columns([5, 1])
            with kopf:
                st.markdown(f"**{beleg.name}**")
                if eintrag:
                    art = prozessregistry.konfiguration(eintrag["prozess"])
                    sonderfall = (" · Sonderfall zum Ausprobieren"
                                  if eintrag.get("stoerfall") else "")
                    st.caption(f"{art.belegart}{sonderfall}")
                else:
                    st.caption(dateigroesse(beleg.stat().st_size))
            starten = knopf.button("Starten", key=f"start_{beleg.name}",
                                   use_container_width=True)

            if starten:
                con = verbindung()
                try:
                    upload = ablage.fuer_datei(con, beleg.name)
                finally:
                    con.close()
                thread_id = starte(app, pfad=beleg, akteur=upn,
                                   upload_id=upload.upload_id if upload else None)
                oeffne_vorgang(thread_id)


# ------------------------------------------------------------------- Seite

def seite() -> None:
    # Die Belegarten stehen in der Ablagefläche selbst -- dort, wo die Datei
    # hinsoll, und nicht nur in einer Zeile darüber.
    arten = aufzaehlung(prozessregistry.belegarten(), verbinder="oder")
    stil.css(ablagehinweis=f"{arten} hierher ziehen oder auswählen")

    st.title("Upload")
    st.caption("Welche Belegart vorliegt, erkennt das System selbst und legt "
               "den Vorgang entsprechend an.")

    upn = angemeldet()
    app, _ = graph()

    con = verbindung()
    try:
        person = benutzer.lade(con, upn)
    finally:
        con.close()

    with st.container(border=True):
        _uploadbereich(person)

    _belegliste(upn, app)

    st.divider()
    st.markdown("### Zuletzt hochgeladen")
    from config import CHECKPOINT_PFAD
    zeilen = uebersicht(app, CHECKPOINT_PFAD)

    if not zeilen:
        st.info("Noch keine Vorgänge. Starten Sie oben einen Beleg.")
        return

    liste.als_karten(zeilen[:ZULETZT], schluessel="upload")
    if len(zeilen) > ZULETZT:
        st.caption(f"{ZULETZT} von {len(zeilen)} Vorgängen. "
                   "Die vollständige Liste steht unter „Alle Vorgänge“.")
