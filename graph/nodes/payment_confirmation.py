"""Process A (Zahlungsbestätigung / payment confirmation) nodes.

Reconciliation -> booking, with the exception-case HITL point that
guards both. Imports only process A's own agents
(`agents.payment_confirmation`) plus the shared helpers in
`graph.nodes.shared` -- nothing from process B.
"""

from __future__ import annotations

from langgraph.types import interrupt

from agents.payment_confirmation import booking, reconciliation, extraction
from agents.shared.schemas import DocumentType
from contracts import (
    ApprovalDecision,
    ApprovalRequest,
    ApprovalResponse,
    ApprovalTrigger,
    CaseOutcome,
    InterruptKind,
)
from governance.audit import Decision, log_entry
from governance.policy import check_approval
from graph.nodes.shared import case_reference, connection, note
from graph.state import Case


def node_payment_extraction(state: Case) -> dict:
    """Use process A's independently configured extraction profile."""
    con = connection()
    try:
        result = extraction.extract_payment(
            con, markdown=state["markdown"], actor=state["actor"],
            reference=case_reference(state),
            profile_snapshot=state.get("model_profiles"),
        )
    finally:
        con.close()
    if not result.succeeded:
        if result.unreachable:
            return {
                "completed": True,
                "outcome": CaseOutcome.MODEL_UNAVAILABLE.value,
                "error": result.escalation,
                "log": note(state, "extraktion_zahlung",
                            "Zahlungsextraktion nicht erreichbar – sicher angehalten."),
            }
        return {
            "number": None, "amount_eur": None,
            "exception_case": True,
            "exception_reason": result.escalation or "Extraktion fehlgeschlagen",
            "escalation": result.escalation,
            "log": note(state, "extraktion_zahlung",
                        "Zahlungsdaten konnten nicht sicher ausgelesen werden."),
        }
    data = result.data
    return {
        "number": data.number,
        "amount_eur": data.amount_eur,
        "log": note(state, "extraktion_zahlung", "Zahlungsdaten ausgelesen."),
    }


def route_payment_extraction(state: Case) -> str:
    return "ende" if state.get("completed") else "abgleich"


def node_reconciliation(state: Case) -> dict:
    """Reconciliation agent (level 1). Deterministic -- see agents/payment_confirmation/reconciliation.py."""
    con = connection()
    try:
        e = reconciliation.reconcile(con, number=state.get("number"),
                                     amount_eur=state.get("amount_eur"),
                                     actor=state["actor"], reference=case_reference(state))
    finally:
        con.close()

    return {
        "finding": e.finding.value,
        "number": e.number,
        "expected_amount_eur": e.expected_amount_eur,
        "exception_case": e.is_exception_case,
        "exception_reason": e.reason if e.is_exception_case else "",
        # The reconciliation agent is human-on-the-loop; if it stops the
        # case, it is because it could not resolve the number itself.
        "approval_trigger": ApprovalTrigger.ESCALATION.value,
        "log": note(state, "abgleich", e.reason),
    }


def route_reconciliation(state: Case) -> str:
    return "hitl" if state.get("exception_case") else "buchung"


def node_booking(state: Case) -> dict:
    """Booking agent (level 3). Asks the policy -- which decides on HITL."""
    con = connection()
    try:
        e = booking.book(
            con, number=state["number"], amount_eur=state["amount_eur"],
            actor=state["actor"], document=state["filename"],
            approved_by=state.get("approved_by"),
            reference=case_reference(state),
        )
    finally:
        con.close()

    if e.approval_needed:
        return {
            "exception_case": True,
            "exception_reason": e.reason,
            # Not an escalation: the booking agent is human-in-the-loop by
            # mode and stops on the happy path too (thesis §7.4, table 11).
            "approval_trigger": ApprovalTrigger.OVERSIGHT_MODE.value,
            "log": note(
                state, "buchung",
                "Die Buchung muss von einer Person bestätigt werden."),
        }

    return {
        "completed": True,
        "outcome": (CaseOutcome.BOOKED if e.booked else CaseOutcome.BOOKING_REFUSED).value,
        "error": e.error,
        "log": note(state, "buchung", e.reason),
    }


def route_booking(state: Case) -> str:
    """After the booking attempt: either done, or approval needed."""
    if state.get("completed"):
        return "ende"
    return "hitl"


def node_exception_case(state: Case) -> dict:
    """HITL point of process A: exception case or booking approval.

    Covers both cases because they ask the same question of the same
    human: 'Book this case anyway?' The reason is in the payload.
    """
    response = ApprovalResponse.from_resume(interrupt(ApprovalRequest(
        kind=InterruptKind.EXCEPTION_CASE,
        trigger=ApprovalTrigger(state.get("approval_trigger")
                                or ApprovalTrigger.ESCALATION.value),
        filename=state.get("filename"),
        reason=state.get("exception_reason"),
        finding=state.get("finding"),
        number=state.get("number"),
        amount_eur=state.get("amount_eur"),
        expected_amount_eur=state.get("expected_amount_eur"),
        escalation=state.get("escalation"),
    ).as_payload()))

    # Four-eyes principle, enforced here and not just in the UI: a resume
    # payload is untrusted input -- it can come from a second browser tab,
    # `demo.py --pruefer`, or a hand-built Command(resume=...). The UI
    # already grays out the approval buttons for a non-member
    # (ui/cases/detail.py), but that is a convenience, not the enforcement
    # point; without this check, an unauthorized or unknown UPN could
    # approve a booking simply by being named in the resume payload.
    con = connection()
    try:
        permission = check_approval(
            con, actor=response.approver, agent_id="buchung",
            submitter=state.get("actor"),
        )
        if not permission.allowed:
            log_entry(con, actor=response.approver, agent="buchung",
                     action="freigabe_verweigert",
                     decision=Decision.DENIED,
                     reason=permission.reason,
                     payload={"number": state.get("number")},
                     reference=case_reference(state), outcome=CaseOutcome.REJECTED.value)
            con.commit()
    finally:
        con.close()

    if not permission.allowed:
        return {
            "completed": True,
            "outcome": CaseOutcome.REJECTED.value,
            "approved_by": response.approver,
            "log": note(state, "klaerfall",
                       f"Freigabe verweigert: {permission.reason}"),
        }

    if not response.approved:
        con = connection()
        try:
            log_entry(con, actor=response.approver, agent="buchung",
                     action="klaerfall_entschieden",
                     decision=Decision.DENIED,
                     reason=f"{response.approver} hat den Vorgang verworfen.",
                     payload={"number": state.get("number")},
                     reference=case_reference(state), outcome=CaseOutcome.REJECTED.value)
            con.commit()
        finally:
            con.close()
        return {
            "completed": True,
            "outcome": CaseOutcome.REJECTED.value,
            "approved_by": response.approver,
            "log": note(state, "klaerfall",
                       f"{response.approver} hat abgelehnt."),
        }

    # The approver may correct the number (case 'unknown number').
    number = response.number or state.get("number")
    if state.get("amount_eur") is None or not number:
        # Nothing to book: either classification failed entirely (R1 --
        # node_classification's failure branch sets neither field), or the
        # number/amount was never found and the approver did not correct
        # it. "Confirm" cannot mean "book it" without both -- proceeding to
        # node_booking would either crash on a missing amount_eur, or send
        # a request Navision's own schema already rejects (a required
        # `number: str` and `amount_eur: float = Field(gt=0)`, see
        # mocks/navision.py). Ending the case the same way an outright
        # rejection does is the only sound reading of an approval with no
        # bookable data behind it -- and gives an honest audit reason
        # instead of a round trip to a target system that was always going
        # to refuse it.
        con = connection()
        try:
            log_entry(con, actor=response.approver, agent="buchung",
                     action="klaerfall_entschieden",
                     decision=Decision.DENIED,
                     reason=f"{response.approver} hat bestätigt, aber der Beleg "
                            "lieferte keine verwertbaren Angaben -- keine Buchung "
                            "möglich.",
                     payload={"escalation": state.get("escalation"),
                             "number": number, "amount_eur": state.get("amount_eur")},
                     reference=case_reference(state), outcome=CaseOutcome.REJECTED.value)
            con.commit()
        finally:
            con.close()
        return {
            "completed": True,
            "outcome": CaseOutcome.REJECTED.value,
            "approved_by": response.approver,
            "log": note(state, "klaerfall",
                       "Keine verwertbaren Angaben aus dem Beleg -- keine "
                       "Buchung möglich."),
        }

    return {
        "number": number,
        "approved_by": response.approver,
        "approval_decision": ApprovalDecision.APPROVED.value,
        "exception_case": False,
        "log": note(state, "klaerfall",
                   f"{response.approver} hat bestätigt."),
    }


def route_exception_case(state: Case) -> str:
    if state.get("completed"):
        return "ende"
    # Guard, not a live path today: a failed classification always sets
    # document_type to 'unbekannt' (graph/nodes/shared.py::node_classification),
    # never 'eingangsrechnung' -- so this branch is not currently reachable.
    # It stays as a safety net: if classification ever preserves a
    # provisional type on failure, an incoming invoice must still be routed
    # back to its own process instead of wrongly booked as a payment.
    if state.get("document_type") == DocumentType.INCOMING_INVOICE.value:
        return "kostenstelle"
    return "buchung"
