"""Tests des Reader-Tools -- Least-Privilege-Nachweis (Szenario 5).

Der wichtigste Test hier ist test_verweigerter_zugriff_liest_die_datei_nicht:
er belegt, dass bei fehlender AD-Mitgliedschaft nicht bloss ein Fehler kommt,
sondern das Dokument tatsaechlich nie geoeffnet wird. "Zugriff verweigert" und
"Zugriff verweigert, aber vorher schnell gelesen" sehen von aussen gleich aus --
dieser Test unterscheidet sie.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from governance.audit import lies_alle, verify_chain
from tools.reader import Dokumentinhalt, ZugriffVerweigert, lies_dokument

EINSPEISER = "einspeiser@chg-meridian.com"
EXTERN = "extern@partner.de"

PDF = Path(__file__).parent.parent / "data" / "eingang" / "A_zahlung_ok_01.pdf"

pytestmark = pytest.mark.skipif(
    not PDF.is_file(),
    reason="Testdaten fehlen -- zuerst `python -m data.generate` ausfuehren.",
)


def test_berechtigter_einspeiser_erhaelt_markdown(con):
    inhalt = lies_dokument(con, PDF, akteur=EINSPEISER)

    assert isinstance(inhalt, Dokumentinhalt)
    assert inhalt.parser == "pymupdf4llm"
    assert inhalt.seiten == 1
    assert len(inhalt.dokument_hash) == 64
    # Die fachlich tragenden Felder muessen im Markdown ankommen.
    assert "Zahlungsbestaetigung" in inhalt.markdown
    assert "Verwendungszweck" in inhalt.markdown


def test_unberechtigter_einspeiser_wird_abgewiesen(con):
    with pytest.raises(ZugriffVerweigert, match="SG-CHG-DocIngest"):
        lies_dokument(con, PDF, akteur=EXTERN)


def test_unbekannter_nutzer_wird_abgewiesen(con):
    """Zero Trust: kein AD-Eintrag, kein Zugriff."""
    with pytest.raises(ZugriffVerweigert):
        lies_dokument(con, PDF, akteur="niemand@nirgends.de")


def test_verweigerter_zugriff_liest_die_datei_nicht(con):
    """Kernnachweis Least Privilege: der Parser wird nie erreicht.

    Wir patchen den Parser: wuerde er trotz verweigertem AD-Check aufgerufen,
    schlaegt der Test fehl. Damit ist belegt, dass die Pruefung *vor* jedem
    Dateizugriff liegt und nicht bloss das Ergebnis verwirft.
    """
    with patch("tools.reader._parse_pymupdf4llm") as parser:
        with pytest.raises(ZugriffVerweigert):
            lies_dokument(con, PDF, akteur=EXTERN)
        parser.assert_not_called()


def test_verweigerter_zugriff_erzeugt_audit_eintrag(con):
    """Szenario 5 verlangt genau das: verweigert *und* protokolliert."""
    with pytest.raises(ZugriffVerweigert):
        lies_dokument(con, PDF, akteur=EXTERN)

    eintraege = lies_alle(con)
    assert len(eintraege) == 1
    e = eintraege[0]
    assert e.agent == "reader"
    assert e.aktion == "dokument_einspeisen"
    assert e.entscheidung.value == "verweigert"
    assert e.akteur == EXTERN
    assert verify_chain(con).gueltig


def test_erfolgreicher_zugriff_protokolliert_dokument_hash(con):
    """Der Hash ist die Grundlage der revisionssicheren Ablage in Prozess B."""
    inhalt = lies_dokument(con, PDF, akteur=EINSPEISER)

    eintraege = lies_alle(con)
    assert eintraege[-1].aktion == "dokument_eingespeist"
    assert eintraege[-1].entscheidung.value == "erlaubt"
    assert verify_chain(con).gueltig
    # Gleiches Dokument -> gleicher Hash (Dublettenerkennung in Prozess A).
    assert lies_dokument(con, PDF, akteur=EINSPEISER).dokument_hash == inhalt.dokument_hash


def test_fehlende_datei_meldet_sich_klar(con):
    with pytest.raises(FileNotFoundError):
        lies_dokument(con, PDF.parent / "gibt_es_nicht.pdf", akteur=EINSPEISER)
