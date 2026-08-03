"""Rauchtest der Oberfläche mit Streamlits eigenem Testläufer.

Prüft nicht das Aussehen, sondern dass jede Seite ohne Ausnahme rendert und
dass Navigation und Berechtigungsanzeige dem AD-Mock folgen. Das ist die
Regression, die beim Umbau der UI am ehesten bricht -- ein Importfehler, ein
doppelter Routenpfad oder eine falsche Feldbezeichnung fällt hier sofort auf.

Es wird kein Vorgang gestartet: die Tests fassen weder ein Modell noch ein
Zielsystem an.
"""

from __future__ import annotations

import sqlite3

import pytest

import prozessregistry
from config import DB_PFAD, MANIFEST_PFAD, PROJEKT_WURZEL

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

STARTZEIT = 60


@pytest.fixture(scope="module")
def upn() -> str:
    """Ein Nutzer mit beiden Rechten -- sonst zeigt die Seite nur Sperren."""
    if not DB_PFAD.is_file():
        pytest.skip("Stammdaten fehlen -- zuerst `python -m data.generate`.")

    con = sqlite3.connect(DB_PFAD)
    try:
        row = con.execute("""
            SELECT m.upn FROM ad_mitgliedschaften m
            WHERE m.gruppe = 'SG-CHG-Freigabe'
              AND EXISTS (SELECT 1 FROM ad_mitgliedschaften d
                          WHERE d.upn = m.upn AND d.gruppe = 'SG-CHG-DocIngest')
            LIMIT 1
        """).fetchone()
    finally:
        con.close()

    if not row:
        pytest.skip("Kein Nutzer mit beiden Rechten in den Stammdaten.")
    return row[0]


def _app() -> AppTest:
    at = AppTest.from_file("ui/app.py", default_timeout=STARTZEIT)
    at.run()
    return at


def _seite(quelle: str) -> AppTest:
    """Rendert eine einzelne Seite mit angemeldetem Nutzer.

    Die Seiten sind Funktionen hinter `st.navigation`; ein Seitenwechsel lässt
    sich im Testläufer nicht ansteuern. Sie direkt aufzurufen prüft genau den
    Code, um den es geht.
    """
    at = AppTest.from_string(quelle, default_timeout=STARTZEIT)
    at.run()
    return at


def _rahmen(upn: str, aufruf: str, vorspann: str = "") -> str:
    return (
        f"import sys; sys.path.insert(0, r'{PROJEKT_WURZEL}')\n"
        "import streamlit as st\n"
        "from ui.shared.kontext import SITZUNG_NUTZER\n"
        f"st.session_state[SITZUNG_NUTZER] = '{upn}'\n"
        f"{vorspann}"
        f"{aufruf}\n"
    )


def _text(at: AppTest) -> str:
    return " ".join(m.body for m in at.markdown)


# ------------------------------------------------------------ Gesamtanwendung

def test_app_startet_ohne_ausnahme():
    assert not _app().exception


def test_navigation_hat_eindeutige_routen():
    """Streamlit lehnt doppelte `url_path` ab -- und jeder Prozess braucht einen."""
    routen = [k.route for k in prozessregistry.alle()]
    # Die Upload-Seite ist die Standardseite und liegt ohne eigenen Pfad auf '/'.
    fest = ["historie", "protokoll", "architektur", "vorgang"]

    assert len(set(routen)) == len(routen)
    assert not set(routen) & set(fest)


def test_sidebar_bietet_ad_nutzer_zur_anmeldung():
    auswahl = _app().sidebar.selectbox[0]

    assert auswahl.label == "Angemeldet als"
    assert auswahl.options, "Ohne AD-Nutzer wäre keine Anmeldung möglich"


def test_sidebar_nennt_die_faehigkeiten_des_kontos():
    """Die Seitenleiste sagt, was dieses Konto kann -- nicht, in welcher
    Sicherheitsgruppe es steckt."""
    at = _app()
    optionen = at.sidebar.selectbox[0].options

    # Die Auswahl fuehrt Anzeigenamen -- der Anmeldename passte nicht in die
    # schmale Seitenleiste und steht darunter.
    extern = [o for o in optionen if o.startswith("Erik Extern")]
    keller = [o for o in optionen if o.startswith("Martina Keller")]
    if not (extern and keller):
        pytest.skip("Erwartete Testkonten fehlen in den Stammdaten.")

    at.sidebar.selectbox[0].set_value(extern[0]).run()
    text = " ".join(m.body for m in at.sidebar.markdown)
    assert "Nur lesen" in text
    assert "SG-CHG" not in text
    # Der Anmeldename steht vollständig darunter, statt in der Auswahl
    # abgeschnitten zu werden.
    assert "e.extern@partner-consulting.de" in text

    at.sidebar.selectbox[0].set_value(keller[0]).run()
    text = " ".join(m.body for m in at.sidebar.markdown)
    # Das Abzeichen bleibt knapp ("Hochladen"); die Belegarten stehen
    # ausführlich im Satz darunter.
    assert "Hochladen" in text
    assert "Zahlungsbestätigungen oder Eingangsrechnungen hochladen" in text


# ------------------------------------------------------------ Einzelne Seiten

def test_uploadseite_bietet_ablageflaeche_und_kurze_historie(upn):
    """Der Upload ist die Hauptsache, die Historie hier nur ein Auszug."""
    if not MANIFEST_PFAD.is_file():
        pytest.skip("Testbelege fehlen -- zuerst `python -m data.generate`.")
    at = _seite(_rahmen(upn, "upload.seite()",
                        "from ui.seiten import upload\n"))

    assert not at.exception
    assert at.file_uploader, "Ohne Uploader gäbe es keine Ablagefläche"
    # Die Ablagefläche trägt ihren Bedienhinweis selbst (CSS); eine
    # Beschriftung daneben wäre dieselbe Aussage zweimal.
    assert str(at.file_uploader[0].label_visibility).strip().lower().endswith(
        "collapsed")
    assert "Zuletzt hochgeladen" in _text(at)


def test_uploadseite_sperrt_hochladen_ohne_berechtigung():
    """Gesperrt, aber ohne Fehlerbalken und ohne Gruppenname: fuer dieses
    Konto ist das kein Fehler, sondern eine andere Aufgabe."""
    at = _seite(_rahmen("e.extern@partner-consulting.de", "upload.seite()",
                        "from ui.seiten import upload\n"))

    assert not at.exception
    hinweise = [i.value for i in at.info]
    assert any("nicht berechtigt" in h for h in hinweise)
    assert not any("SG-CHG" in h for h in hinweise)
    assert not at.file_uploader, "Ohne Recht darf keine Ablagefläche erscheinen"


def test_historienseite_rendert(upn):
    at = _seite(_rahmen(upn, "historie.seite()",
                        "from ui.seiten import historie\n"))
    assert not at.exception


def test_jede_prozessseite_rendert(upn):
    """Beide Prozesse entstehen aus derselben Funktion -- beide müssen laufen."""
    for konfiguration in prozessregistry.alle():
        at = _seite(_rahmen(
            upn,
            f"prozess.zeige(prozessregistry.konfiguration('{konfiguration.schluessel}'))",
            "import prozessregistry\nfrom ui.seiten import prozess\n"))

        assert not at.exception, f"Prozess {konfiguration.schluessel} bricht"
        assert konfiguration.bezeichnung in _text(at) + " ".join(
            t.value for t in at.title)


def test_architekturseite_zeigt_beide_prozesse_und_die_registry(upn):
    at = _seite(_rahmen(upn, "architektur.seite()",
                        "from ui.seiten import architektur\n"))
    text = _text(at)

    assert not at.exception
    assert "Zahlungsbestätigung" in text and "Eingangsrechnung" in text
    # Die Seite liest die Registry. Erschiene der Buchungs-Agent hier nicht als
    # Human-in-the-loop, zeigte die Oberfläche etwas anderes als der Code tut.
    assert "Human-in-the-loop" in text


def test_protokollseite_bewertet_die_unversehrtheit(upn):
    at = _seite(_rahmen(upn, "audit.seite()", "from ui.seiten import audit\n"))

    assert not at.exception
    meldungen = [e.value for e in at.success] + [e.value for e in at.error]
    assert any("Protokoll" in m for m in meldungen)


def test_vorgangsseite_ohne_id_bleibt_verstaendlich(upn):
    """Ein direkter Aufruf ohne `?id=` darf nicht in einen Fehler laufen."""
    at = _seite(_rahmen(upn, "vorgang.seite()", "from ui.seiten import vorgang\n"))

    assert not at.exception
    assert any("Kein Vorgang" in i.value for i in at.info)
