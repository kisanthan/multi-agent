"""Die Arbeitsansichten bleiben frei von Fachjargon.

Begriffe wie „Prozess A", „Human-in-the-loop", „Einspeiser" oder der Name einer
Sicherheitsgruppe stammen aus dem Fachkonzept. Sie sind dort richtig und auf
dem Bildschirm eines Sachbearbeiters falsch.

Zwei Stellen sind bewusst ausgenommen:

- die Seite **Architektur** -- sie erklaert genau diese Begriffe,
- der **Inhalt des Protokolls** -- dort steht, was tatsaechlich aufgezeichnet
  wurde. Einen aufgezeichneten Grund fuer die Anzeige umzuformulieren, hiesse
  den Nachweis zu faelschen. Geprueft wird deshalb nur die Umgebung der
  Protokollseite, nicht die Tabelle darin.
"""

from __future__ import annotations

import pytest

from config import DB_PFAD, PROJEKT_WURZEL

pytest.importorskip("streamlit.testing.v1")
from streamlit.testing.v1 import AppTest  # noqa: E402

# Was auf keiner Arbeitsansicht auftauchen darf.
JARGON = [
    "SG-CHG",
    "Prozess A",
    "Prozess B",
    "Human-in-the-loop",
    "Human-on-the-loop",
    "AD-Check",
    "Einspeiser",
    "einspeisen",
    "eingespeist",
    "Klärfall",
    "Vier-Augen",
    "Autonomiestufe",
    "Least Privilege",
    "Audit-Trail",
    "Zielsystem",
]


@pytest.fixture(scope="module")
def upn() -> str:
    import sqlite3

    if not DB_PFAD.is_file():
        pytest.skip("Stammdaten fehlen -- zuerst `python -m data.generate`.")
    con = sqlite3.connect(DB_PFAD)
    try:
        row = con.execute(
            "SELECT upn FROM ad_mitgliedschaften WHERE gruppe = 'SG-CHG-Freigabe'"
            " LIMIT 1").fetchone()
    finally:
        con.close()
    if not row:
        pytest.skip("Kein freigabeberechtigtes Konto in den Stammdaten.")
    return row[0]


def _rendere(quelle: str) -> AppTest:
    at = AppTest.from_string(quelle, default_timeout=90)
    at.run()
    return at


def _seite(upn: str, aufruf: str, importe: str) -> AppTest:
    return _rendere(
        f"import sys; sys.path.insert(0, r'{PROJEKT_WURZEL}')\n"
        "import streamlit as st\n"
        "from ui.shared.kontext import SITZUNG_NUTZER\n"
        f"st.session_state[SITZUNG_NUTZER] = '{upn}'\n"
        f"{importe}"
        f"{aufruf}\n"
    )


def _sichtbarer_text(at: AppTest) -> str:
    """Alles, was ein Mensch auf der Seite liest.

    Ohne den Inhalt von Tabellen: dort steht bei der Protokollseite der
    aufgezeichnete Wortlaut, der bewusst unveraendert bleibt.
    """
    teile: list[str] = []
    for name in ("markdown", "caption", "title", "header", "subheader",
                 "info", "warning", "error", "success"):
        for element in getattr(at, name, []):
            teile.append(str(getattr(element, "value", getattr(element, "body", ""))))

    for name in ("button", "selectbox", "multiselect", "text_input",
                 "date_input", "metric", "file_uploader", "toggle"):
        for element in getattr(at, name, []):
            teile.append(str(getattr(element, "label", "")))

    # Das eingebettete Stylesheet ist kein Text fuer Menschen.
    return " ".join(t for t in teile if not t.lstrip().startswith("<style>"))


def _pruefe_frei_von_jargon(at: AppTest, seitenname: str) -> None:
    text = _sichtbarer_text(at)
    treffer = [w for w in JARGON if w.lower() in text.lower()]
    assert not treffer, f"{seitenname} zeigt Fachjargon: {treffer}"


def test_uploadseite_ohne_jargon(upn):
    at = _seite(upn, "upload.seite()", "from ui.seiten import upload\n")
    assert not at.exception
    _pruefe_frei_von_jargon(at, "Upload")


def test_uploadseite_ohne_jargon_auch_ohne_berechtigung():
    """Gerade die Sperrmeldung darf keine Sicherheitsgruppe nennen."""
    at = _seite("e.extern@partner-consulting.de", "upload.seite()",
                "from ui.seiten import upload\n")
    assert not at.exception
    _pruefe_frei_von_jargon(at, "Upload (gesperrt)")


def test_alle_vorgaenge_ohne_jargon(upn):
    at = _seite(upn, "historie.seite()", "from ui.seiten import historie\n")
    assert not at.exception
    _pruefe_frei_von_jargon(at, "Alle Vorgänge")


def test_vorgangsarten_ohne_jargon(upn):
    import prozessregistry

    for konfiguration in prozessregistry.alle():
        at = _seite(
            upn,
            f"prozess.zeige(prozessregistry.konfiguration('{konfiguration.schluessel}'))",
            "import prozessregistry\nfrom ui.seiten import prozess\n")
        assert not at.exception
        _pruefe_frei_von_jargon(at, konfiguration.bezeichnung)


def test_protokollseite_ohne_jargon_in_der_umgebung(upn):
    at = _seite(upn, "audit.seite()", "from ui.seiten import audit\n")
    assert not at.exception
    _pruefe_frei_von_jargon(at, "Protokoll")


def test_architekturseite_darf_die_fachbegriffe_zeigen(upn):
    """Die Gegenprobe: hier gehoeren sie hin, sonst waere die Ausnahme sinnlos."""
    at = _seite(upn, "architektur.seite()", "from ui.seiten import architektur\n")
    text = _sichtbarer_text(at)

    assert not at.exception
    assert "Human-in-the-loop" in text
    assert "Prozess A" in text
