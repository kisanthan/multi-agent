"""Streamlit-Oberfläche des Multiagentensystems.

Zeigt den vollständigen Weg eines Belegs: Upload → Prozess A oder B →
Freigabe an den Risikostellen → Bestätigung mit der Wirkung im Zielsystem.

Die Oberfläche ist kein Beiwerk, sondern der sichtbare Beleg zweier Aussagen
der Arbeit:

- **Least Privilege**: der angemeldete Nutzer ist zugleich der Einspeiser. Wer
  nicht in der AD-Sicherheitsgruppe ist, kommt am Reader nicht vorbei.
- **Human-in-the-loop**: was auf Freigabe wartet, läuft ohne menschliche
  Entscheidung nicht weiter.

Diese Datei ist der Router: sie meldet an, baut die Navigation aus den
Registries und führt die gewählte Seite aus. Fachlogik steht hier keine.

Start:  streamlit run ui/app.py
"""

from __future__ import annotations

import functools
import sqlite3
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent.parent))

import prozessregistry  # noqa: E402
from config import DB_PFAD  # noqa: E402
from ui.shared import benutzer, stil  # noqa: E402
from ui.shared.kontext import SITZUNG_NUTZER, registriere_seiten  # noqa: E402

st.set_page_config(page_title="CHG-MERIDIAN Vorgangsbearbeitung",
                   page_icon="📄", layout="wide")


def _anmeldung() -> None:
    """Sidebar: Kontoauswahl und was dieses Konto darf.

    Im Prototyp eine Auswahl statt echter Anmeldung -- die Rechte dahinter sind
    aber die echten Gruppenmitgliedschaften aus dem Verzeichnisdienst.

    Angezeigt wird die *Faehigkeit* in einem Satz, nicht die Mitgliedschaft in
    einer Sicherheitsgruppe: der Gruppenname hilft niemandem weiter, der sie
    nicht ohnehin verwalten kann.
    """
    con = sqlite3.connect(DB_PFAD)
    try:
        konten = con.execute(
            "SELECT upn, anzeigename FROM ad_nutzer ORDER BY anzeigename"
        ).fetchall()
        if not konten:
            st.sidebar.error("Keine Benutzerkonten vorhanden. "
                             "Zuerst `python -m data.generate` ausführen.")
            st.stop()

        # Nur der Anzeigename: der Anmeldename passt nicht in die schmale
        # Seitenleiste und wurde dort abgeschnitten. Er steht darunter -- es
        # sei denn, zwei Konten heissen gleich, dann muss er in die Auswahl.
        namen = [name for _, name in konten]
        eindeutig = len(set(namen)) == len(namen)
        labels = {(name if eindeutig else f"{name} ({upn})"): upn
                  for upn, name in konten}

        # `with st.sidebar:` statt einzelner `st.sidebar.xxx()`-Aufrufe: die
        # Statuskarte wird ueber ein plaines `st.markdown()` gezeichnet (siehe
        # `stil.statuskarte`), und das faende ohne diesen Block den Weg in den
        # Hauptbereich statt in die Seitenleiste.
        with st.sidebar:
            stil.css()

            wahl = st.selectbox("Angemeldet als", list(labels))
            upn = labels[wahl]
            st.session_state[SITZUNG_NUTZER] = upn
            person = benutzer.lade(con, upn)

            # Eine Karte, ein Aufruf: Abzeichen fuer den schnellen Blick,
            # darunter der ganze Satz -- inklusive der Belegarten, die dieses
            # Konto einreichen darf. Sichtbar und nicht im Tooltip: was man
            # nur beim Darueberfahren findet, findet man nicht.
            #
            # Der Anmeldename wird hier nur gezeigt, wenn er noch nicht in der
            # Auswahl selbst steht (nicht eindeutige Anzeigenamen zwingen ihn
            # dorthin) -- sonst stuende er zweimal.
            stil.statuskarte(person, upn=upn if eindeutig else None)
    finally:
        con.close()


def _seiten() -> dict:
    """Baut die Seitenobjekte.

    Die Prozessseiten entstehen aus `prozessregistry` -- ein weiterer Prozess
    erscheint dadurch von selbst in der Navigation. `url_path` ist ueberall
    explizit, weil Streamlit den Pfad sonst aus dem Funktionsnamen ableitet und
    alle Seiten `seite` heissen; Slashes sind darin nicht erlaubt.
    """
    from ui.seiten import architektur, audit, historie, prozess, upload, vorgang

    seiten = {
        # 'Upload' ist bereits der Abschnitt -- die Seite heisst darum nicht
        # noch einmal so. Ebenso 'Alle Vorgänge' statt 'Historische Vorgänge':
        # letzteres ist innerhalb der Prozessseiten eine Abschnittsüberschrift
        # und meint dort etwas Engeres.
        #
        # Kein `url_path`: die Standardseite liegt bei Streamlit immer auf '/'
        # und ignoriert eine eigene Angabe -- ein '/upload' liefe ins Leere.
        "upload": st.Page(upload.seite, title="Neuer Beleg", icon="📥",
                          default=True),
        "historie": st.Page(historie.seite, title="Alle Vorgänge",
                            icon="🗂️", url_path="historie"),
        "audit": st.Page(audit.seite, title="Protokoll", icon="🔐",
                         url_path="protokoll"),
        "architektur": st.Page(architektur.seite, title="Architektur", icon="🏛️",
                               url_path="architektur"),
        # Ohne Eintrag in der Navigation: hierher kommt man aus einer Liste.
        "vorgang": st.Page(vorgang.seite, title="Vorgang", icon="📄",
                           url_path="vorgang", visibility="hidden"),
    }
    for konfiguration in prozessregistry.alle():
        seiten[konfiguration.route] = st.Page(
            functools.partial(prozess.zeige, konfiguration),
            title=konfiguration.bezeichnung, icon=konfiguration.icon,
            url_path=konfiguration.route,
        )
    return seiten


def main() -> None:
    _anmeldung()

    seiten = _seiten()
    registriere_seiten(seiten)

    st.navigation({
        "Upload": [seiten["upload"], seiten["historie"]],
        "Vorgangsarten": [seiten[k.route] for k in prozessregistry.alle()],
        "Nachweis": [seiten["audit"], seiten["architektur"]],
        "": [seiten["vorgang"]],
    }).run()


main()
