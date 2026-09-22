"""Authenticated end-to-end process tests including real mock target handlers."""
import sqlite3
import uuid
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from langgraph.types import Command
import config
from data.migrations import connect
from governance import identity, control
from governance.audit_contract import verify
from graph.workflow import compile_graph
from agents.shared.schemas import Classification, DocumentType
from llm.extraction import ExtractionResult

SUBMITTER = "m.keller@chg-meridian.com"
APPROVER = "s.hofmann@chg-meridian.com"


@pytest.fixture
def flow(tmp_path, monkeypatch):
    from mocks import navision, elo
    clients = {"booking": TestClient(navision.app), "archive": TestClient(elo.app)}
    def post(url, **kwargs):
        kwargs.pop("timeout", None)
        route = url.rsplit("/", 1)[1]
        return clients[route].post("/" + route, **kwargs)
    monkeypatch.setattr("runtime.tool_gateway.httpx.post", post)
    with connect(config.DB_PATH) as con:
        tokens = {}
        for actor in (SUBMITTER, APPROVER):
            identity.set_password(con, actor, "synthetic-e2e-password")
            tokens[actor] = identity.login(con, actor, "synthetic-e2e-password")
        con.execute("UPDATE invoices SET status='offen',paid_at=NULL,amount_eur=1500 WHERE number='RE-2026-4200'")
        con.commit()
    app, checkpoint = compile_graph(tmp_path / "checkpoints.sqlite")
    thread = {"configurable": {"thread_id": uuid.uuid4().hex}}
    yield app, thread, tokens, clients
    checkpoint.close()
    for client in clients.values():
        client.close()


def model(monkeypatch, kind, **fields):
    data = Classification(type=kind, **fields)
    monkeypatch.setattr("agents.shared.classification.extract",
                        lambda *args, **kwargs: ExtractionResult(data, 1, "synthetic", "mock"))


def start(flow, filename):
    app, thread, tokens, _ = flow
    with identity.session(tokens[SUBMITTER]):
        return app.invoke({"actor": SUBMITTER, "path": str(config.INTAKE_DIR / filename), "log": []}, thread)


def decide(flow, state, **fields):
    app, thread, tokens, _ = flow
    request = state["__interrupt__"][0].value
    payload = {"decision": "freigegeben", "approver": APPROVER,
               "approval_id": request["approval_id"], "version": request["version"], **fields}
    with identity.session(tokens[APPROVER]):
        return app.invoke(Command(resume=payload), thread)


def test_authenticated_payment_finishes_once(flow, monkeypatch):
    model(monkeypatch, DocumentType.PAYMENT_CONFIRMATION, number="RE-2026-4200", amount_eur=1500)
    state = start(flow, "A_payment_ok_01.pdf")
    assert "__interrupt__" in state, state
    state = decide(flow, state)
    assert state["outcome"] == "verbucht", state
    with connect(config.DB_PATH) as con:
        cmd = control.command(con, state["command_id"])
        assert cmd["status"] == "succeeded"
        assert verify(con).valid


def test_invoice_with_unique_match_stores_original_and_cost_center(flow, monkeypatch):
    with connect(config.DB_PATH) as con:
        center, ref = con.execute("SELECT id,reference FROM cost_centers ORDER BY id LIMIT 1").fetchone()
    model(monkeypatch, DocumentType.INCOMING_INVOICE, number="INV-1", amount_eur=125, cost_center_reference=ref)
    state = start(flow, "B_invoice_ok_01.pdf")
    assert state["outcome"] == "archiviert", state
    with connect(config.DB_PATH) as con:
        assert control.command(con, state["command_id"])["receipt"]["cost_center_id"] == center
        original = con.execute("SELECT content FROM document_objects WHERE document_hash=?", (state["document_hash"],)).fetchone()[0]
        assert original == (config.INTAKE_DIR / "B_invoice_ok_01.pdf").read_bytes()


def test_unknown_cost_center_requires_selection_then_confirmation(flow, monkeypatch):
    model(monkeypatch, DocumentType.INCOMING_INVOICE, number="INV-2", amount_eur=125)
    state = start(flow, "B_invoice_without_reference.pdf")
    with connect(config.DB_PATH) as con:
        center = con.execute("SELECT id FROM cost_centers ORDER BY id LIMIT 1").fetchone()[0]
    state = decide(flow, state, cost_center_id=center)
    assert "__interrupt__" in state
    state = decide(flow, state, cost_center_id=center)
    assert state["outcome"] == "archiviert", state


def test_invalid_cost_center_cannot_be_approved(flow, monkeypatch):
    model(monkeypatch, DocumentType.INCOMING_INVOICE, number="INV-2", amount_eur=125)
    state = start(flow, "B_invoice_without_reference.pdf")
    state = decide(flow, state, cost_center_id="DOES-NOT-EXIST")
    assert state["outcome"] == "verworfen"
    assert not state.get("archive_id")


def test_raw_identity_does_not_start_a_case(flow, monkeypatch):
    app, thread, tokens, _ = flow
    state = app.invoke({"actor": SUBMITTER, "path": str(config.INTAKE_DIR / "A_payment_ok_01.pdf")}, thread)
    assert state["outcome"] == "zugriff_verweigert"
