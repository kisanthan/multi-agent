"""End-to-end tests of the five demonstration scenarios.

These tests run the complete graph -- reader, classification, orchestrator
routing, agents, HITL interrupts, target systems, audit. Only two things are
replaced:

1. The language model (llm.extraction.extract) -- with fixed extraction
   results. That way the tests run without Ollama and deterministically;
   what is tested is the *architecture*, not the model's extraction
   quality.
2. The HTTP transport to the mocks -- the FastAPI apps run via ASGI in the
   same process, without a real server.

That makes the entire chain testable, including the HITL resumption via the
checkpoint. This is the proof that the thesis's five scenarios actually run
through.
"""

from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

import pytest

from agents.shared.schemas import DocumentType, Classification
from config import INTAKE_DIR, MANIFEST_PATH
from governance.audit import verify_chain
from llm.extraction import ExtractionResult

PROJECT_ROOT = Path(__file__).parent.parent


# --------------------------------------------------------------- Fixtures

@pytest.fixture(scope="module", autouse=True)
def test_data():
    """Requires the synthetic data to exist (generation happens outside).

    Deliberately NOT generated here: the Faker import is very expensive on
    this machine (full disk). The data is generated once via `python -m
    data.generate`; the scenario tests run against it. The graph runs
    against the real DB (not in-memory), because several connections and
    the mock services access it.
    """
    if not MANIFEST_PATH.is_file() or not any(INTAKE_DIR.glob("*.pdf")):
        pytest.skip("Testdaten fehlen -- zuerst `python -m data.generate` ausfuehren.")
    yield


@pytest.fixture
def thread():
    return {"configurable": {"thread_id": f"test-{uuid.uuid4().hex[:8]}"}}


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Compiled graph with a mocked LLM and in-process mocks.

    The checkpoint sits in tmp_path and not on the production path: the
    running UI keeps `data/checkpoints.sqlite` open, and a test must
    neither delete its cases nor fail on a file lock.
    """
    # --- Bring target systems into the process via ASGI ---
    # FastAPI's TestClient talks to the ASGI app synchronously (httpx's
    # ASGITransport is async-only and does not fit the agents' synchronous
    # httpx.post calls). This way the mocks run without a real server in
    # the same process.
    from fastapi.testclient import TestClient

    from mocks import elo as elo_mock
    from mocks import navision as navision_mock

    navision_client = TestClient(navision_mock.app)
    elo_client = TestClient(elo_mock.app)

    # The agents call known endpoint paths -- map them directly onto the
    # in-process mocks instead of starting a real server.
    def fake_post(url, **kwargs):
        if url.endswith("/booking"):
            return navision_client.post("/booking", **kwargs)
        if url.endswith("/archive"):
            return elo_client.post("/archive", **kwargs)
        raise AssertionError(f"Unerwarteter POST an {url}")

    monkeypatch.setattr("agents.payment_confirmation.booking.httpx.post", fake_post)
    monkeypatch.setattr("agents.incoming_invoice.archiving.httpx.post", fake_post)

    from graph.workflow import compile_graph
    graph, cp_con = compile_graph(tmp_path / "checkpoints.sqlite")
    yield graph
    cp_con.close()
    navision_client.close()
    elo_client.close()


def _mock_classification(monkeypatch, **fields):
    """Replaces the extraction agent with a fixed classification result."""
    data = Classification(**fields)
    result = ExtractionResult(data=data, attempts=1, model="mock", provider="mock")
    monkeypatch.setattr("agents.shared.classification.extract", lambda *a, **k: result)


def _reset_status(number: str, status: str = "offen") -> None:
    from config import DB_PATH
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE invoices SET status = ?, paid_at = NULL WHERE number = ?",
                (status, number))
    con.commit()
    con.close()


def _pdf(name: str) -> str:
    return str(INTAKE_DIR / name)


# ------------------------------------------------- Scenario 1: happy path A

def test_scenario1_valid_payment_needs_booking_approval(app, thread, monkeypatch):
    """Valid payment -> reconciliation ok -> booking approval (HITL) -> open->paid.

    Thesis §7.4: the financially effective booking step is human-in-the-loop.
    Even with a valid, unique match, the booking only executes after a
    human approval -- there is no automatic booking.
    """
    _reset_status("RE-2026-4200")
    _set_amount("RE-2026-4200", 1_500.0)
    _mock_classification(
        monkeypatch, type=DocumentType.PAYMENT_CONFIRMATION,
        number="RE-2026-4200", amount_eur=1_500.0,
        supplier="Microsoft Deutschland GmbH",
    )

    from langgraph.types import Command
    state = app.invoke(
        {"path": _pdf("A_zahlung_ok_01.pdf"), "actor": "m.keller@chg-meridian.com",
         "log": []},
        thread,
    )

    # Booking is always HITL -> even the happy path pauses for approval.
    assert "__interrupt__" in state
    assert state["__interrupt__"][0].value["finding"] == "ok"

    state = app.invoke(
        Command(resume={"decision": "freigegeben",
                        "approver": "s.hofmann@chg-meridian.com",
                        "number": "RE-2026-4200"}),
        thread,
    )
    assert state["outcome"] == "verbucht"

    from config import DB_PATH
    con = sqlite3.connect(DB_PATH)
    status = con.execute("SELECT status FROM invoices WHERE number = ?",
                         ("RE-2026-4200",)).fetchone()[0]
    assert verify_chain(con).valid
    con.close()
    assert status == "bezahlt"


def test_scenario1_large_amount_same_single_approval(app, thread, monkeypatch):
    """Even a large amount goes through exactly one approval -- no threshold.

    Proves there is no amount-dependent special path: 500,000 EUR goes
    through the same single human-in-the-loop approval as 1,500 EUR.
    """
    _reset_status("RE-2026-4200")
    _set_amount("RE-2026-4200", 500_000.0)
    _mock_classification(
        monkeypatch, type=DocumentType.PAYMENT_CONFIRMATION,
        number="RE-2026-4200", amount_eur=500_000.0,
    )

    from langgraph.types import Command
    state = app.invoke(
        {"path": _pdf("A_zahlung_ok_01.pdf"), "actor": "m.keller@chg-meridian.com",
         "log": []},
        thread,
    )
    assert "__interrupt__" in state

    state = app.invoke(
        Command(resume={"decision": "freigegeben",
                        "approver": "s.hofmann@chg-meridian.com",
                        "number": "RE-2026-4200"}),
        thread,
    )
    assert state["outcome"] == "verbucht"


def _set_amount(number: str, amount: float) -> None:
    from config import DB_PATH
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE invoices SET amount_eur = ? WHERE number = ?", (amount, number))
    con.commit()
    con.close()


# ---------------------------------------- Scenario 2: unknown number

def test_scenario2_unknown_number_becomes_an_exception_case(app, thread, monkeypatch):
    """Unknown number -> exception case -> approver corrects -> booking."""
    _reset_status("RE-2026-4201")
    _set_amount("RE-2026-4201", 2_000.0)
    _mock_classification(
        monkeypatch, type=DocumentType.PAYMENT_CONFIRMATION,
        number="RE-2026-9999", amount_eur=2_000.0,
    )

    from langgraph.types import Command
    state = app.invoke(
        {"path": _pdf("A_zahlung_unbekannte_nummer.pdf"),
         "actor": "m.keller@chg-meridian.com", "log": []},
        thread,
    )

    assert "__interrupt__" in state
    request = state["__interrupt__"][0].value
    assert request["finding"] == "unbekannt"

    # The approver corrects it to an existing, open number.
    state = app.invoke(
        Command(resume={"decision": "freigegeben",
                        "approver": "s.hofmann@chg-meridian.com",
                        "number": "RE-2026-4201"}),
        thread,
    )
    assert state["outcome"] == "verbucht"


def test_scenario2_rejecting_does_not_book(app, thread, monkeypatch):
    """The approver can also reject the exception case -- then no booking."""
    _mock_classification(
        monkeypatch, type=DocumentType.PAYMENT_CONFIRMATION,
        number="RE-2026-9999", amount_eur=None,
    )
    from langgraph.types import Command
    state = app.invoke(
        {"path": _pdf("A_zahlung_unbekannte_nummer.pdf"),
         "actor": "m.keller@chg-meridian.com", "log": []},
        thread,
    )
    state = app.invoke(
        Command(resume={"decision": "verworfen",
                        "approver": "s.hofmann@chg-meridian.com"}),
        thread,
    )
    assert state["outcome"] == "verworfen"


# ------------------------------------------- Scenario 3: happy path B

def test_scenario3_unique_cost_center_is_archived_automatically(app, thread, monkeypatch):
    """Invoice -> unique cost center -> automatic archiving in ELO.

    Process B (diagram part 3): the cost-center agent is human-on-the-loop.
    On a unique assignment, the case runs through WITHOUT approval all the
    way to the tamper-evident filing -- ELO is the end of the process, there
    is no Navision booking left in process B.
    """
    _mock_classification(
        monkeypatch, type=DocumentType.INCOMING_INVOICE,
        number="ER-2026-7102", amount_eur=37_940.0,
        supplier="Microsoft Deutschland GmbH",
        line_items=["Microsoft 365 E5, 1200 Lizenzen", "Azure Cloud Hosting"],
        cost_center_reference="KTR-ITINFRA",  # resolves uniquely to KST-1000
    )

    state = app.invoke(
        {"path": _pdf("B_rechnung_ok_02.pdf"), "actor": "m.keller@chg-meridian.com",
         "log": []},
        thread,
    )

    # Reference resolves uniquely -> human-on-the-loop -> no interrupt.
    assert "__interrupt__" not in state
    assert state["outcome"] == "archiviert"
    assert state["cost_center_id"] == "KST-1000"
    assert state["archive_id"].startswith("ELO-")

    from config import DB_PATH
    con = sqlite3.connect(DB_PATH)
    row = con.execute("SELECT archive_id FROM archive WHERE archive_id = ?",
                      (state["archive_id"],)).fetchone()
    assert row is not None  # filed tamper-evidently
    assert verify_chain(con).valid
    con.close()


# ---------------------------------------- Scenario 4: reference missing

def test_scenario4_missing_reference_lets_a_human_decide(app, thread, monkeypatch):
    """No document reference -> lookup fails -> exception case -> human picks.

    The exact lookup is not unique as soon as the reference is missing.
    Then the four-eyes approval kicks in; the human choice determines the
    cost center and is traceable in the audit trail.
    """
    _mock_classification(
        monkeypatch, type=DocumentType.INCOMING_INVOICE,
        number="ER-2026-7200", amount_eur=24_400.0,
        supplier="SAP Deutschland SE",
        line_items=["SAP Lizenzverlaengerung Modul FI", "Anwenderschulung SAP FI"],
        cost_center_reference=None,  # no reference on the document
    )

    from langgraph.types import Command
    state = app.invoke(
        {"path": _pdf("B_rechnung_ohne_referenz.pdf"),
         "actor": "t.brandt@chg-meridian.com", "log": []},
        thread,
    )

    assert "__interrupt__" in state
    request = state["__interrupt__"][0].value
    assert request["unique"] is False
    # The approver gets the full catalog to choose from.
    assert any(k["id"] == "KST-5000" for k in request["catalog"])

    # Human picks HR training.
    state = app.invoke(
        Command(resume={"decision": "freigegeben",
                        "approver": "s.hofmann@chg-meridian.com",
                        "cost_center_id": "KST-5000"}),
        thread,
    )
    assert state["outcome"] == "archiviert"
    assert state["archive_id"].startswith("ELO-")
    assert state["cost_center_id"] == "KST-5000"  # human choice in the state

    from config import DB_PATH

    from governance.audit import read_all
    con = sqlite3.connect(DB_PATH)
    # The human choice is traceable in the audit trail.
    approvals = [e for e in read_all(con)
                if e.action == "kostenstelle_freigegeben"]
    assert any("KST-5000" in e.reason for e in approvals)
    assert verify_chain(con).valid
    con.close()


# ---------------------------------------- Scenario 5: without a model

def test_scenario5_unauthorized_submitter(app, thread):
    """AD check denies -> no model, no target system, one audit entry."""
    state = app.invoke(
        {"path": _pdf("A_zahlung_unberechtigt.pdf"),
         "actor": "e.extern@partner-consulting.de", "log": []},
        thread,
    )
    assert state["outcome"] == "zugriff_verweigert"
    assert "__interrupt__" not in state
    # Exactly one step: the reader node, nothing else.
    assert [s["node"] for s in state["log"]] == ["reader"]


# ------------------------------ Beyond the five: total extraction failure

def _mock_extraction_failure(monkeypatch, *,
                             escalation: str = "Modell nicht erreichbar: Testfehler.") -> None:
    """Replaces the extraction agent with a total failure (R1 escalation:
    data=None), not merely a successful result with a null field -- exactly
    what llm/extraction.py::extract returns once both schema-retry attempts
    fail, or the model is unreachable."""
    result = ExtractionResult(data=None, attempts=2, model="mock", provider="mock",
                              escalation=escalation)
    monkeypatch.setattr("agents.shared.classification.extract", lambda *a, **k: result)


def test_total_extraction_failure_approved_ends_cleanly_not_booked(app, thread, monkeypatch):
    """A total classification failure (nothing extracted at all) must not
    reach node_booking, even if the resulting exception case is approved --
    there is nothing to book.

    Regression test: this used to crash the graph with `KeyError:
    'amount_eur'` in node_booking, because route_exception_case's only
    guard checked document_type, not whether reconciliation's fields
    (number, amount_eur) were ever actually extracted.
    """
    _mock_extraction_failure(monkeypatch)

    from langgraph.types import Command
    state = app.invoke(
        {"path": _pdf("A_zahlung_ok_01.pdf"), "actor": "m.keller@chg-meridian.com",
         "log": []},
        thread,
    )

    assert "__interrupt__" in state
    request = state["__interrupt__"][0].value
    assert request["kind"] == "klaerfall"

    # Approved anyway -- there is still nothing to book.
    state = app.invoke(
        Command(resume={"decision": "freigegeben",
                        "approver": "s.hofmann@chg-meridian.com"}),
        thread,
    )
    assert state["outcome"] == "verworfen"
    assert state["completed"] is True

    from config import DB_PATH
    from governance.audit import read_all
    con = sqlite3.connect(DB_PATH)
    entries = [e for e in read_all(con) if e.action == "klaerfall_entschieden"]
    assert any("keine Buchung" in e.reason for e in entries)
    assert verify_chain(con).valid
    con.close()


def test_unreachable_navision_is_audited_from_the_caller_side(app, thread, monkeypatch):
    """A transport-level failure talking to Navision (connection refused,
    timeout, DNS) must itself be audited -- from the caller's side.

    Navision logs its own accept/reject decision when it actually receives
    a request (mocks/navision.py), but an unreachable Navision never runs
    that handler at all, so it never gets the chance to log anything about
    it. Before this fix, that specific failure mode left no audit trace of
    its own -- only the case's outcome/error state reflected it.
    """
    _reset_status("RE-2026-4200")
    _set_amount("RE-2026-4200", 1_500.0)
    _mock_classification(
        monkeypatch, type=DocumentType.PAYMENT_CONFIRMATION,
        number="RE-2026-4200", amount_eur=1_500.0,
    )

    from langgraph.types import Command
    state = app.invoke(
        {"path": _pdf("A_zahlung_ok_01.pdf"), "actor": "m.keller@chg-meridian.com",
         "log": []},
        thread,
    )
    assert "__interrupt__" in state

    import httpx as httpx_module

    def unreachable(*args, **kwargs):
        raise httpx_module.ConnectError("Verbindung verweigert")

    # Overrides the app fixture's routing to the in-process mock for this
    # one call -- simulating Navision being down, not just rejecting.
    monkeypatch.setattr("agents.payment_confirmation.booking.httpx.post", unreachable)

    from config import DB_PATH
    from governance.audit import read_all
    con = sqlite3.connect(DB_PATH)
    # Watermark: the production audit table persists across test runs, so
    # "any entry ever logged" would trivially pass once this fix has run
    # successfully once. Only entries written by *this* call count.
    before_ids = {e.id for e in read_all(con)}
    con.close()

    state = app.invoke(
        Command(resume={"decision": "freigegeben",
                        "approver": "s.hofmann@chg-meridian.com",
                        "number": "RE-2026-4200"}),
        thread,
    )
    assert state["outcome"] == "abgelehnt"

    con = sqlite3.connect(DB_PATH)
    new_entries = [e for e in read_all(con) if e.id not in before_ids]
    assert any(e.action == "zahlung_verbuchen" and e.decision.value == "verweigert"
              and "nicht erreichbar" in e.reason for e in new_entries), (
        f"no matching new audit entry among {[(e.action, e.decision.value) for e in new_entries]}"
    )
    assert verify_chain(con).valid
    con.close()


def test_unreachable_elo_is_audited_from_the_caller_side(app, thread, monkeypatch):
    """Mirrors the Navision case for process B: an unreachable ELO must be
    audited from the caller's side, since its own handler never runs to
    log anything about it either."""
    _mock_classification(
        monkeypatch, type=DocumentType.INCOMING_INVOICE,
        number="ER-2026-9100", amount_eur=12_000.0,
        supplier="Microsoft Deutschland GmbH",
        line_items=["Azure Cloud Hosting"],
        cost_center_reference="KTR-ITINFRA",  # resolves uniquely -> no interrupt
    )

    import httpx as httpx_module

    def unreachable(*args, **kwargs):
        raise httpx_module.ConnectError("Verbindung verweigert")

    monkeypatch.setattr("agents.incoming_invoice.archiving.httpx.post", unreachable)

    from config import DB_PATH
    from governance.audit import read_all
    con = sqlite3.connect(DB_PATH)
    # Watermark -- see test_unreachable_navision_is_audited_from_the_caller_side.
    before_ids = {e.id for e in read_all(con)}
    con.close()

    state = app.invoke(
        {"path": _pdf("B_rechnung_ok_02.pdf"), "actor": "m.keller@chg-meridian.com",
         "log": []},
        thread,
    )
    assert "__interrupt__" not in state
    assert state["outcome"] == "archivierung_fehlgeschlagen"

    con = sqlite3.connect(DB_PATH)
    new_entries = [e for e in read_all(con) if e.id not in before_ids]
    assert any(e.action == "dokument_archivieren" and e.decision.value == "verweigert"
              and "nicht erreichbar" in e.reason for e in new_entries), (
        f"no matching new audit entry among {[(e.action, e.decision.value) for e in new_entries]}"
    )
    assert verify_chain(con).valid
    con.close()


def test_number_still_missing_after_approval_ends_cleanly_not_booked(app, thread, monkeypatch):
    """Classification succeeds (amount_eur is known) but finds no invoice
    number, and the approver does not correct it -- there is still nothing
    to book.

    Symmetric case to the total-extraction-failure test above: before this
    fix, this would not crash (Navision's mock schema already rejects a
    missing `number`), but it would silently rely on that downstream
    rejection instead of the domain layer's own logic, and would not carry
    an accurate audit reason.
    """
    _mock_classification(
        monkeypatch, type=DocumentType.PAYMENT_CONFIRMATION,
        number=None, amount_eur=2_000.0,
    )

    from langgraph.types import Command
    state = app.invoke(
        {"path": _pdf("A_zahlung_ok_01.pdf"), "actor": "m.keller@chg-meridian.com",
         "log": []},
        thread,
    )
    assert "__interrupt__" in state
    assert state["__interrupt__"][0].value["finding"] == "keine_nummer"

    # Approved without a correction -- still nothing to book.
    state = app.invoke(
        Command(resume={"decision": "freigegeben",
                        "approver": "s.hofmann@chg-meridian.com"}),
        thread,
    )
    assert state["outcome"] == "verworfen"
    assert state["completed"] is True

    from config import DB_PATH
    from governance.audit import read_all
    con = sqlite3.connect(DB_PATH)
    entries = [e for e in read_all(con) if e.action == "klaerfall_entschieden"]
    assert any("keine Buchung" in e.reason for e in entries)
    assert verify_chain(con).valid
    con.close()
