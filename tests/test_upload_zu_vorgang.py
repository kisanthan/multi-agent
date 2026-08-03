"""Integrationstest: aus einem Upload entsteht ein Vorgang im richtigen Prozess.

Deckt den Bogen ab, den die Oberflaeche verspricht: Datei einspeisen ->
Upload-Eintrag -> Vorgang mit Bezug zum Upload -> Zuordnung zu Prozess A oder B
-> auffindbar in der Historie *und* auf der Prozessseite -> lueckenlos im
Audit-Trail.

Das Sprachmodell ist gemockt (wie in test_szenarien.py) -- geprueft wird die
Verkettung der Bausteine, nicht die Extraktionsguete.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

import prozessregistry
from agents.schemas import Dokumenttyp, Klassifikation
from config import EINGANG_DIR
from governance.audit import lies_alle, verify_chain
from graph.vorgaenge import Status, prozess_von, status_von, uebersicht
from llm.extraktion import Extraktionsergebnis
from ui.shared import filter as filtern
from ui.upload import ablage

PDF = (EINGANG_DIR / "A_zahlung_ok_01.pdf")
EINSPEISER = "m.keller@chg-meridian.com"


@pytest.fixture(autouse=True)
def _testdaten():
    if not PDF.is_file():
        pytest.skip("Testbelege fehlen -- zuerst `python -m data.generate`.")


@pytest.fixture
def produktiv():
    """Leseverbindung auf die echte Datenbank.

    Die Graph-Knoten oeffnen ihre eigene Verbindung auf `DB_PFAD` und schreiben
    ihre Audit-Eintraege dorthin -- die In-Memory-Datenbank der `con`-Fixture
    sieht sie nicht. Fuer Aussagen ueber den Trail eines echten Laufs ist
    deshalb diese Verbindung noetig.
    """
    import sqlite3

    from config import DB_PFAD

    if not DB_PFAD.is_file():
        pytest.skip("Stammdaten fehlen -- zuerst `python -m data.generate`.")
    con = sqlite3.connect(DB_PFAD)
    yield con
    con.close()


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Graph mit gemocktem Modell und In-Prozess-Zielsystemen."""
    from fastapi.testclient import TestClient

    from mocks import elo as elo_mock
    from mocks import navision as navision_mock

    navision = TestClient(navision_mock.app)
    elo = TestClient(elo_mock.app)

    def fake_post(url, **kwargs):
        if url.endswith("/booking"):
            return navision.post("/booking", **kwargs)
        if url.endswith("/archive"):
            return elo.post("/archive", **kwargs)
        raise AssertionError(f"Unerwarteter POST an {url}")

    monkeypatch.setattr("agents.buchung.httpx.post", fake_post)
    monkeypatch.setattr("agents.zielsysteme.httpx.post", fake_post)

    daten = Klassifikation(typ=Dokumenttyp.ZAHLUNGSBESTAETIGUNG,
                           nummer="RE-2026-4203", betrag_eur=1341.96)
    monkeypatch.setattr(
        "agents.klassifikation.extrahiere",
        lambda *a, **k: Extraktionsergebnis(daten=daten, versuche=1,
                                            modell="mock", anbieter="mock"))

    from graph.workflow import kompiliere
    graph, cp_con = kompiliere(tmp_path / "checkpoints.sqlite")
    yield graph, tmp_path / "checkpoints.sqlite"
    cp_con.close()
    navision.close()
    elo.close()


def _starte(app, *, upload_id: str | None, pfad: Path) -> str:
    """Faehrt einen Vorgang so an, wie es die Oberflaeche tut."""
    vorgang_id = f"{pfad.name}-{uuid.uuid4().hex[:8]}"
    app.invoke({
        "pfad": str(pfad), "akteur": EINSPEISER, "upload_id": upload_id,
        "vorgang_id": vorgang_id,
        "gestartet_am": datetime.now(timezone.utc).isoformat(), "protokoll": [],
    }, {"configurable": {"thread_id": vorgang_id}})
    return vorgang_id


def test_upload_erzeugt_vorgang_im_richtigen_prozess(con, app, tmp_path, monkeypatch):
    monkeypatch.setattr(ablage, "EINGANG_DIR", tmp_path / "eingang")
    graph, checkpoint = app

    upload = ablage.lege_ab(con, dateiname="A_zahlung_ok_01.pdf",
                            daten=PDF.read_bytes(), akteur=EINSPEISER)
    vorgang_id = _starte(graph, upload_id=upload.upload_id,
                         pfad=Path(upload.pfad))

    werte = graph.get_state({"configurable": {"thread_id": vorgang_id}}).values

    # Der Vorgang kennt seinen Upload -- die Beziehung ist 1:n.
    assert werte["upload_id"] == upload.upload_id
    assert werte["vorgang_id"] == vorgang_id
    assert prozess_von(werte) == "A"
    assert prozessregistry.konfiguration("A").bezeichnung == "Zahlungsbestätigung"


def test_vorgang_ist_in_historie_und_auf_der_prozessseite(con, app, tmp_path,
                                                          monkeypatch):
    """Beide Ansichten speisen sich aus derselben Quelle, nur anders gefiltert."""
    monkeypatch.setattr(ablage, "EINGANG_DIR", tmp_path / "eingang")
    graph, checkpoint = app

    upload = ablage.lege_ab(con, dateiname="A_zahlung_ok_01.pdf",
                            daten=PDF.read_bytes(), akteur=EINSPEISER)
    vorgang_id = _starte(graph, upload_id=upload.upload_id, pfad=Path(upload.pfad))

    alle = uebersicht(graph, checkpoint)
    in_prozess_a = filtern.fuer_prozess(alle, "A")
    in_prozess_b = filtern.fuer_prozess(alle, "B")

    assert [z.thread_id for z in alle] == [vorgang_id]
    assert [z.thread_id for z in in_prozess_a] == [vorgang_id]
    assert in_prozess_b == []


def test_vorgang_wartet_auf_die_buchungsfreigabe(con, app, tmp_path, monkeypatch):
    """Prozess A ist Human-in-the-loop -- auch der Happy Path haelt an."""
    monkeypatch.setattr(ablage, "EINGANG_DIR", tmp_path / "eingang")
    graph, checkpoint = app

    upload = ablage.lege_ab(con, dateiname="A_zahlung_ok_01.pdf",
                            daten=PDF.read_bytes(), akteur=EINSPEISER)
    vorgang_id = _starte(graph, upload_id=upload.upload_id, pfad=Path(upload.pfad))

    schnappschuss = graph.get_state({"configurable": {"thread_id": vorgang_id}})
    status = status_von(schnappschuss.values, wartet=bool(schnappschuss.interrupts))

    assert status is Status.WARTET_AUF_FREIGABE
    assert filtern.kennzahlen(uebersicht(graph, checkpoint))["offen"] == 1


def test_audit_ist_nach_dem_vorgang_filterbar(con, app, tmp_path, monkeypatch,
                                              produktiv):
    """Der Bogen Vorgang -> Nachweis, den die Detailseite anbietet."""
    monkeypatch.setattr(ablage, "EINGANG_DIR", tmp_path / "eingang")
    graph, _ = app

    upload = ablage.lege_ab(con, dateiname="A_zahlung_ok_01.pdf",
                            daten=PDF.read_bytes(), akteur=EINSPEISER)
    vorgang_id = _starte(graph, upload_id=upload.upload_id, pfad=Path(upload.pfad))

    eintraege = lies_alle(produktiv, vorgang_id=vorgang_id)

    assert eintraege, "Der Lauf muss im Trail auffindbar sein"
    assert {e.vorgang_id for e in eintraege} == {vorgang_id}
    # Jeder Eintrag nennt den Beleg, auf den er sich bezieht.
    assert all(e.datenquelle == "A_zahlung_ok_01.pdf" for e in eintraege)
    # Der Upload selbst gehoert zu keinem Vorgang und ist nicht dabei.
    assert all(e.aktion != "datei_hochgeladen" for e in eintraege)
    assert verify_chain(produktiv).gueltig


def test_zweiter_lauf_derselben_datei_ist_ein_eigener_vorgang(con, app, tmp_path,
                                                              monkeypatch, produktiv):
    """Ein Upload kann mehrere Vorgaenge erzeugen -- deshalb reicht der
    Dateiname als Korrelation nicht aus."""
    monkeypatch.setattr(ablage, "EINGANG_DIR", tmp_path / "eingang")
    graph, checkpoint = app

    upload = ablage.lege_ab(con, dateiname="A_zahlung_ok_01.pdf",
                            daten=PDF.read_bytes(), akteur=EINSPEISER)
    erster = _starte(graph, upload_id=upload.upload_id, pfad=Path(upload.pfad))
    zweiter = _starte(graph, upload_id=upload.upload_id, pfad=Path(upload.pfad))

    ids_erster = {e.id for e in lies_alle(produktiv, vorgang_id=erster)}
    ids_zweiter = {e.id for e in lies_alle(produktiv, vorgang_id=zweiter)}

    assert erster != zweiter
    assert len(uebersicht(graph, checkpoint)) == 2
    assert ids_erster and ids_zweiter
    assert not ids_erster & ids_zweiter
