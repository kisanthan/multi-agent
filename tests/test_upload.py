"""Tests der Eingangspruefung.

Der Upload ist die neue Haupthandlung der Oberflaeche -- was hier durchrutscht,
scheitert spaeter im Reader mit einer Meldung, die niemand versteht.
"""

from __future__ import annotations

import pytest

from governance.audit import lies_alle, verify_chain
from ui.upload import ablage

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\nInhalt"
AKTEUR = "einspeiser@chg-meridian.com"


@pytest.fixture(autouse=True)
def _eingang(tmp_path, monkeypatch):
    """Schreibt in ein temporaeres Verzeichnis statt in data/eingang."""
    monkeypatch.setattr(ablage, "EINGANG_DIR", tmp_path / "eingang")


def test_gueltiges_pdf_wird_angenommen(con):
    assert ablage.pruefe(con, dateiname="beleg.pdf", daten=PDF).ok


def test_falsche_endung_wird_abgewiesen(con):
    ergebnis = ablage.pruefe(con, dateiname="bild.jpg", daten=PDF)

    assert not ergebnis.ok
    assert ".jpg" in ergebnis.grund


def test_leere_datei_wird_abgewiesen(con):
    ergebnis = ablage.pruefe(con, dateiname="leer.pdf", daten=b"")

    assert not ergebnis.ok
    assert "keine Daten" in ergebnis.grund


def test_falscher_inhalt_trotz_pdf_endung(con):
    """Die Endung ist eine Behauptung, die Kopfbytes sind der Beleg."""
    ergebnis = ablage.pruefe(con, dateiname="getarnt.pdf", daten=b"\xff\xd8\xff JPEG")

    assert not ergebnis.ok
    assert "kein PDF" in ergebnis.grund


def test_zu_grosse_datei_wird_abgewiesen(con, monkeypatch):
    monkeypatch.setattr(ablage, "MAX_BYTES", 10)
    ergebnis = ablage.pruefe(con, dateiname="gross.pdf", daten=PDF)

    assert not ergebnis.ok
    assert "größer" in ergebnis.grund


def test_ablage_schreibt_datei_und_eintrag(con):
    upload = ablage.lege_ab(con, dateiname="beleg.pdf", daten=PDF, akteur=AKTEUR)

    assert (ablage.EINGANG_DIR / "beleg.pdf").read_bytes() == PDF
    assert upload.hochgeladen_von == AKTEUR
    assert upload.groesse_bytes == len(PDF)
    assert ablage.lade(con, upload.upload_id) == upload


def test_ablage_normalisiert_pfadangaben_im_namen(con):
    """Ein Pfadanteil im Dateinamen darf nicht aus dem Eingang herausfuehren."""
    upload = ablage.lege_ab(con, dateiname="../../geheim.pdf", daten=PDF, akteur=AKTEUR)

    assert upload.dateiname == "geheim.pdf"
    assert (ablage.EINGANG_DIR / "geheim.pdf").is_file()


def test_inhaltsgleiche_datei_gilt_als_dublette(con):
    erster = ablage.lege_ab(con, dateiname="beleg.pdf", daten=PDF, akteur=AKTEUR)

    # Anderer Name, gleicher Inhalt -- der Hash entscheidet, nicht der Name.
    ergebnis = ablage.pruefe(con, dateiname="kopie.pdf", daten=PDF)

    assert not ergebnis.ok
    assert ergebnis.ist_dublette
    assert ergebnis.dublette_von == erster.upload_id


def test_upload_steht_im_audit_trail(con):
    ablage.lege_ab(con, dateiname="beleg.pdf", daten=PDF, akteur=AKTEUR)

    eintrag = lies_alle(con)[-1]
    assert eintrag.aktion == "datei_hochgeladen"
    assert eintrag.datenquelle == "beleg.pdf"
    assert eintrag.ergebnis == "abgelegt"
    # Ein Upload gehoert noch zu keinem Vorgang.
    assert eintrag.vorgang_id is None
    assert verify_chain(con).gueltig


def test_abgewiesene_datei_steht_ebenfalls_im_trail(con):
    """Sonst waere ein Einspeiseversuch mit unzulaessiger Datei unsichtbar."""
    ablage.protokolliere_abweisung(con, dateiname="bild.jpg", akteur=AKTEUR,
                                   grund="Der Dateiinhalt ist kein PDF.")

    eintrag = lies_alle(con)[-1]
    assert eintrag.ergebnis == "abgewiesen"
    assert eintrag.entscheidung.value == "verweigert"


def test_fuer_datei_findet_juengsten_eintrag(con):
    ablage.lege_ab(con, dateiname="beleg.pdf", daten=PDF, akteur=AKTEUR)

    assert ablage.fuer_datei(con, "beleg.pdf") is not None
    # Generierte Testbelege lagen schon im Ordner und haben keinen Upload.
    assert ablage.fuer_datei(con, "nie_hochgeladen.pdf") is None
