"""Tests of the cross-boundary contracts in contracts.py.

Two jobs: pin the exact wire shape each process produces today (so
adopting these contracts in graph/nodes/* in a later step cannot silently
change what gets persisted into the checkpoint), and check the two
invariants that keep process_registry's plain-string configuration
honest against this module's enums without coupling the two at runtime.
"""

from __future__ import annotations

from contracts import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalTrigger,
    CaseOutcome,
    InterruptKind,
)


# ------------------------------------------------- ApprovalRequest / process A

def test_payment_confirmation_request_omits_unset_fields():
    """A field that is None (here: expected_amount_eur, because this
    exception case never reached the reconciliation step) is omitted
    entirely -- not sent as `null` -- so the payload never claims evidence
    it does not have."""
    request = ApprovalRequest(
        kind=InterruptKind.EXCEPTION_CASE,
        filename="A_zahlung_unbekannte_nummer.pdf",
        reason="Nummer nicht in den Stammdaten.",
        finding="unbekannt",
        number="RE-2026-9999",
        amount_eur=2000.0,
        expected_amount_eur=None,
        escalation="Extraktion fehlgeschlagen.",
    )
    assert set(request.as_payload()) == {
        "kind", "trigger", "filename", "reason", "finding", "number",
        "amount_eur", "escalation",
    }


def test_payment_confirmation_request_full_key_set():
    """With every process-A field populated, the key set matches exactly
    what graph/nodes/payment_confirmation.py declares (9 keys).

    `kind` and `trigger` are the two that are always present: what the
    case is waiting for, and which oversight rule stopped it.
    """
    request = ApprovalRequest(
        kind=InterruptKind.EXCEPTION_CASE,
        trigger=ApprovalTrigger.OVERSIGHT_MODE,
        filename="A_zahlung_ok_01.pdf", reason="…", finding="ok",
        number="RE-2026-4200", amount_eur=1500.0, expected_amount_eur=1500.0,
        escalation="…",
    )
    assert set(request.as_payload()) == {
        "kind", "trigger", "filename", "reason", "finding", "number",
        "amount_eur", "expected_amount_eur", "escalation",
    }


def test_incoming_invoice_request_full_key_set():
    """With every process-B field populated, the key set matches exactly
    what graph/nodes/incoming_invoice.py declares (10 keys)."""
    request = ApprovalRequest(
        kind=InterruptKind.COST_CENTER_APPROVAL,
        filename="B_rechnung_ohne_referenz.pdf", supplier="SAP Deutschland SE",
        amount_eur=24400.0, line_items=("Pos 1", "Pos 2"), reference=None,
        reason="Der Beleg nennt keine Kostenstellenreferenz.",
        catalog=({"id": "KST-1000", "name": "IT", "reference": "KTR-ITINFRA"},),
        unique=False,
    )
    assert set(request.as_payload()) == {
        "kind", "trigger", "filename", "supplier", "amount_eur", "line_items",
        "reason", "catalog", "unique",
    }


def test_request_round_trips_through_its_payload():
    for request in (
        ApprovalRequest(kind=InterruptKind.EXCEPTION_CASE, filename="x.pdf",
                        reason="r", finding="ok", number="RE-1",
                        amount_eur=1.0, expected_amount_eur=1.0, escalation="e"),
        ApprovalRequest(kind=InterruptKind.COST_CENTER_APPROVAL, filename="y.pdf",
                        supplier="s", amount_eur=2.0, line_items=("a", "b"),
                        reference="KTR-X", reason="r",
                        catalog=({"id": "KST-1", "name": "n", "reference": "KTR-X"},),
                        unique=True),
    ):
        assert ApprovalRequest.from_payload(request.as_payload()) == request


def test_trigger_defaults_to_escalation():
    """A stop is an exception unless a node declares otherwise.

    The safe default matters because the value is shown to the approver:
    calling an escalation "routine oversight" would understate it, while
    the reverse only overstates the unusualness of a routine stop.
    """
    request = ApprovalRequest(kind=InterruptKind.EXCEPTION_CASE)
    assert request.trigger is ApprovalTrigger.ESCALATION
    assert request.as_payload()["trigger"] == "eskalation"


def test_trigger_survives_the_checkpoint_round_trip():
    """Both values must come back as themselves -- the dialog's whole
    headline hangs off this one field."""
    for trigger in ApprovalTrigger:
        request = ApprovalRequest(kind=InterruptKind.EXCEPTION_CASE,
                                  trigger=trigger, number="RE-1")
        assert ApprovalRequest.from_payload(request.as_payload()).trigger is trigger


def test_legacy_payload_without_trigger_reads_as_escalation():
    """Checkpoints written before the field existed must stay readable.

    A case paused in the checkpoint outlives a code change -- that is the
    point of the checkpointer -- so `from_payload` has to cope with a
    payload that predates the field.
    """
    legacy = {"kind": "klaerfall", "number": "RE-2026-4200"}
    assert ApprovalRequest.from_payload(legacy).trigger is ApprovalTrigger.ESCALATION


# ------------------------------------------------------------ ApprovalResponse

def test_response_always_carries_a_number_key_even_when_none():
    """ui/cases/detail.py and demo.py both always include `number` in the
    resume dict, even for process B where it means nothing -- preserved so
    a reading node need not guess whether the key exists."""
    response = ApprovalResponse(decision=ApprovalDecision.APPROVED, approver="a@b.c")
    payload = response.as_resume()
    assert "number" in payload and payload["number"] is None


def test_response_omits_cost_center_id_when_absent():
    response = ApprovalResponse(decision=ApprovalDecision.APPROVED, approver="a@b.c",
                                number="RE-1")
    assert "cost_center_id" not in response.as_resume()


def test_response_round_trips_through_its_resume_payload():
    response = ApprovalResponse(decision=ApprovalDecision.REJECTED, approver="a@b.c",
                                number="RE-1", cost_center_id="KST-5000")
    assert ApprovalResponse.from_resume(response.as_resume()) == response


def test_unrecognized_decision_is_rejected_not_approved():
    """Fail-closed, like governance/policy.py's default-deny rule: a resume
    payload this code cannot understand must not book or archive anything."""
    response = ApprovalResponse.from_resume({"approver": "a@b.c"})
    assert response.decision is ApprovalDecision.REJECTED
    assert not response.approved

    response = ApprovalResponse.from_resume({"decision": "garbage", "approver": "a@b.c"})
    assert response.decision is ApprovalDecision.REJECTED


def test_approved_property():
    assert ApprovalResponse(decision=ApprovalDecision.APPROVED, approver="a").approved
    assert not ApprovalResponse(decision=ApprovalDecision.REJECTED, approver="a").approved


# --------------------------------------------- process_registry vocabulary

def test_process_outcomes_use_the_declared_vocabulary():
    import process_registry

    completion_outcomes = {p.completion_outcome for p in process_registry.PROCESSES.values()}
    assert completion_outcomes <= {o.value for o in CaseOutcome}


def test_every_process_interrupt_kind_is_declared_and_unique():
    import process_registry

    interrupt_kinds = [p.interrupt_kind for p in process_registry.PROCESSES.values()]
    assert set(interrupt_kinds) == {k.value for k in InterruptKind}
    assert len(interrupt_kinds) == len(set(interrupt_kinds)), (
        "two processes claiming the same interrupt kind would make "
        "process_registry.for_interrupt() ambiguous"
    )
