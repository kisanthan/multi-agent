"""Integration test: an upload turns into a case in the right process.

Covers the arc the UI promises: submit file -> upload entry -> case with a
reference to the upload -> assignment to process A or B -> findable in the
history *and* on the process page -> gapless in the audit trail.

The language model is mocked (as in test_szenarien.py) -- what is tested is
the chaining of the building blocks, not the extraction quality.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

import process_registry
from agents.shared.schemas import DocumentType, Classification
from config import INTAKE_DIR
from governance.audit import read_all, verify_chain
from graph.cases import Status, process_of, determine_status, overview
from llm.extraction import ExtractionResult
from ui.shared import filter as filters
from ui.intake import intake

PDF = (INTAKE_DIR / "A_payment_ok_01.pdf")
SUBMITTER = "m.keller@chg-meridian.com"


@pytest.fixture(autouse=True)
def _test_data():
    if not PDF.is_file():
        pytest.skip("Testbelege fehlen -- zuerst `python -m data.generate`.")


@pytest.fixture
def production():
    """Read connection to the test session's isolated runtime database.

    The graph nodes open their own connection to `DB_PATH` and write their
    audit entries there -- the `con` fixture's in-memory database does not
    see them. This connection is therefore needed for assertions about the
    integration run's trail.
    """
    import sqlite3

    from config import DB_PATH

    if not DB_PATH.is_file():
        pytest.skip("Stammdaten fehlen -- zuerst `python -m data.generate`.")
    con = sqlite3.connect(DB_PATH)
    yield con
    con.close()


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Graph with a mocked model and in-process target systems."""
    from fastapi.testclient import TestClient

    from mocks import elo as elo_mock
    from mocks import navision as navision_mock

    navision = TestClient(navision_mock.app)
    elo = TestClient(elo_mock.app)

    def fake_post(url, **kwargs):
        kwargs.pop("timeout", None)
        if url.endswith("/booking"):
            return navision.post("/booking", **kwargs)
        if url.endswith("/archive"):
            return elo.post("/archive", **kwargs)
        raise AssertionError(f"Unerwarteter POST an {url}")

    monkeypatch.setattr("agents.payment_confirmation.booking.httpx.post", fake_post)
    monkeypatch.setattr("agents.incoming_invoice.archiving.httpx.post", fake_post)

    data = Classification(type=DocumentType.PAYMENT_CONFIRMATION,
                          number="RE-2026-4203", amount_eur=1341.96)
    monkeypatch.setattr(
        "agents.shared.classification.extract",
        lambda *a, **k: ExtractionResult(data=data, attempts=1,
                                         model="mock", provider="mock"))

    from graph.workflow import compile_graph
    graph, cp_con = compile_graph(tmp_path / "checkpoints.sqlite")
    from tests.auth_helpers import SignedInGraph
    yield SignedInGraph(graph), tmp_path / "checkpoints.sqlite"
    cp_con.close()
    navision.close()
    elo.close()


def _start(app, *, upload_id: str | None, path: Path) -> str:
    """Runs a case the same way the UI does."""
    case_id = f"{path.name}-{uuid.uuid4().hex[:8]}"
    app.invoke({
        "path": str(path), "actor": SUBMITTER, "upload_id": upload_id,
        "case_id": case_id,
        "started_at": datetime.now(timezone.utc).isoformat(), "log": [],
    }, {"configurable": {"thread_id": case_id}})
    return case_id


def test_upload_creates_a_case_in_the_right_process(con, app, tmp_path, monkeypatch):
    monkeypatch.setattr(intake, "INTAKE_DIR", tmp_path / "inbox")
    graph, checkpoint = app

    upload = intake.store(con, filename="A_payment_ok_01.pdf",
                          data=PDF.read_bytes(), actor=SUBMITTER)
    case_id = _start(graph, upload_id=upload.upload_id,
                     path=Path(upload.path))

    values = graph.get_state({"configurable": {"thread_id": case_id}}).values

    # The case knows its upload -- the relationship is 1:n.
    assert values["upload_id"] == upload.upload_id
    assert values["case_id"] == case_id
    assert process_of(values) == "A"
    assert process_registry.get_config("A").name == "Zahlungsbestätigung"


def test_case_is_in_history_and_on_the_process_page(con, app, tmp_path,
                                                     monkeypatch):
    """Both views draw from the same source, just filtered differently."""
    monkeypatch.setattr(intake, "INTAKE_DIR", tmp_path / "inbox")
    graph, checkpoint = app

    upload = intake.store(con, filename="A_payment_ok_01.pdf",
                          data=PDF.read_bytes(), actor=SUBMITTER)
    case_id = _start(graph, upload_id=upload.upload_id, path=Path(upload.path))

    all_rows = overview(graph, checkpoint)
    in_process_a = filters.for_process(all_rows, "A")
    in_process_b = filters.for_process(all_rows, "B")

    assert [z.thread_id for z in all_rows] == [case_id]
    assert [z.thread_id for z in in_process_a] == [case_id]
    assert in_process_b == []


def test_case_waits_for_booking_approval(con, app, tmp_path, monkeypatch):
    """Process A is human-in-the-loop -- even the happy path pauses."""
    monkeypatch.setattr(intake, "INTAKE_DIR", tmp_path / "inbox")
    graph, checkpoint = app

    upload = intake.store(con, filename="A_payment_ok_01.pdf",
                          data=PDF.read_bytes(), actor=SUBMITTER)
    case_id = _start(graph, upload_id=upload.upload_id, path=Path(upload.path))

    snapshot = graph.get_state({"configurable": {"thread_id": case_id}})
    status = determine_status(snapshot.values, waiting=bool(snapshot.interrupts))

    assert status is Status.WAITING_FOR_APPROVAL
    assert filters.counts(overview(graph, checkpoint))["pending"] == 1


def test_audit_is_filterable_by_case(con, app, tmp_path, monkeypatch,
                                     production):
    """The case -> evidence arc the detail page offers."""
    monkeypatch.setattr(intake, "INTAKE_DIR", tmp_path / "inbox")
    graph, _ = app

    upload = intake.store(con, filename="A_payment_ok_01.pdf",
                          data=PDF.read_bytes(), actor=SUBMITTER)
    case_id = _start(graph, upload_id=upload.upload_id, path=Path(upload.path))

    entries = read_all(production, case_id=case_id)

    assert entries, "Der Lauf muss im Trail auffindbar sein"
    assert {e.case_id for e in entries} == {case_id}
    # Every entry names the document it relates to.
    import hashlib
    expected_hash = hashlib.sha256(PDF.read_bytes()).hexdigest()
    assert all(e.source in {"A_payment_ok_01.pdf", expected_hash} for e in entries)
    # The upload itself belongs to no case and is not among them.
    assert all(e.action != "datei_hochgeladen" for e in entries)
    assert verify_chain(production).valid


def test_second_run_of_the_same_file_is_its_own_case(con, app, tmp_path,
                                                      monkeypatch, production):
    """An upload can create several cases -- so the filename alone is not
    enough as a correlation."""
    monkeypatch.setattr(intake, "INTAKE_DIR", tmp_path / "inbox")
    graph, checkpoint = app

    upload = intake.store(con, filename="A_payment_ok_01.pdf",
                          data=PDF.read_bytes(), actor=SUBMITTER)
    first = _start(graph, upload_id=upload.upload_id, path=Path(upload.path))
    second = _start(graph, upload_id=upload.upload_id, path=Path(upload.path))

    ids_first = {e.id for e in read_all(production, case_id=first)}
    ids_second = {e.id for e in read_all(production, case_id=second)}

    assert first != second
    assert len(overview(graph, checkpoint)) == 2
    assert ids_first and ids_second
    assert not ids_first & ids_second
