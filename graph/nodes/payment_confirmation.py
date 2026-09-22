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
from governance import control
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
        control.authorize_read(con, state["case_id"], "A", "abgleich", state["actor"])
        e = reconciliation.reconcile(con, number=state.get("number"),
                                     amount_eur=state.get("amount_eur"),
                                     actor=state["actor"], reference=case_reference(state))
        proposal = control.candidate(con, state["case_id"], "buchung",
                                     control.payment_payload(con, state["case_id"], e.number, state.get("amount_eur")), True)
    finally:
        con.close()

    return {
        "approval_id": proposal["approval_id"], "candidate_version": proposal["version"],
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
            approved_by=state.get("approved_by"), approval_id=state.get("approval_id"),
            candidate_version=state.get("candidate_version"), command_id=state.get("command_id"),
            reference=case_reference(state),
        )
    finally:
        con.close()

    if e.approval_needed:
        return {
            "exception_case": True,
            "exception_reason": e.reason,
            # Not an escalation: the booking agent is human-in-the-loop by
            # mode and stops on the happy path too (thesis §7.4, table 22).
            "approval_trigger": ApprovalTrigger.OVERSIGHT_MODE.value,
            "log": note(
                state, "buchung",
                "Die Buchung muss von einer Person bestätigt werden."),
        }

    return {
        "completed": e.outcome is not CaseOutcome.EFFECT_UNCERTAIN,
        "command_id": e.command_id,
        "outcome": (
            e.outcome
            or (CaseOutcome.BOOKED if e.booked else CaseOutcome.BOOKING_REFUSED)
        ).value,
        "error": e.error,
        "log": note(state, "buchung", e.reason),
    }


def route_booking(state: Case) -> str:
    """After the booking attempt: either done, or approval needed."""
    if state.get("completed") or state.get("outcome") == CaseOutcome.EFFECT_UNCERTAIN.value:
        return "ende"
    return "hitl"


def node_exception_case(state: Case) -> dict:
    """A decision is bound to the displayed persistent candidate."""
    from governance import control, identity
    from governance.step_policy import PolicyDenied
    con = connection()
    try:
        proposal = control.get_candidate(con, state["case_id"], "buchung", state.get("candidate_version"))
    except PolicyDenied as error:
        con.close()
        return {"completed": True, "outcome": CaseOutcome.CONTROL_BLOCKED.value,
                "error": str(error), "log": note(state, "klaerfall", str(error))}
    con.close()
    request = ApprovalRequest(
        kind=InterruptKind.EXCEPTION_CASE,
        trigger=ApprovalTrigger(state.get("approval_trigger") or ApprovalTrigger.ESCALATION.value),
        filename=state.get("filename"), reason=state.get("exception_reason"),
        finding=state.get("finding"), number=proposal["payload"]["number"],
        amount_eur=(proposal["payload"]["amount_cents"] / 100 if proposal["payload"]["amount_cents"] is not None else None),
        expected_amount_eur=state.get("expected_amount_eur"),
        current_status=proposal["payload"].get("expected_status"),
        escalation=state.get("escalation"),
    ).as_payload()
    request.update({k: proposal[k] for k in ("approval_id", "version", "payload_hash", "expires")})
    raw = interrupt(request)
    con = connection()
    try:
        person = identity.principal(con)
        permission = check_approval(con, actor=person, agent_id="buchung", submitter=state.get("actor"))
        if not permission.allowed:
            raise PolicyDenied(permission.reason)
        if raw.get("approver", person) != person or raw.get("approval_id") != proposal["approval_id"] or raw.get("version") != proposal["version"]:
            raise PolicyDenied("Sitzung oder angezeigte Freigabe stimmt nicht überein.")
        if raw.get("decision") != ApprovalDecision.APPROVED.value:
            duplicate = state.get("finding") == reconciliation.Finding.ALREADY_PAID.value
            reason = raw.get("reason") or (
                "Als Dublette geschlossen; keine Buchung ausgeführt."
                if duplicate else "Verworfen"
            )
            control.decide(con, proposal, approved=False, reason=reason)
            outcome = CaseOutcome.DUPLICATE_CLOSED if duplicate else CaseOutcome.REJECTED
            message = "Dublette geschlossen; es wurde nichts gebucht." if duplicate else "Vorgang verworfen."
            return {"completed": True, "outcome": outcome.value, "approved_by": person,
                    "log": note(state, "klaerfall", message)}
        number = raw.get("number") or proposal["payload"]["number"]
        amount = raw.get("amount_eur", state.get("amount_eur"))
        new_payload = control.payment_payload(con, state["case_id"], number, amount)
        control.validate_payload(con, "buchung", new_payload)
        if new_payload != proposal["payload"]:
            replacement = control.candidate(con, state["case_id"], "buchung", new_payload, True)
            return {"number": new_payload["number"], "amount_eur": amount,
                    "expected_amount_eur": new_payload["expected_cents"] / 100,
                    "candidate_version": replacement["version"], "approval_id": replacement["approval_id"],
                    "approval_decision": "", "exception_case": True, "finding": "korrigiert",
                    "exception_reason": "Korrigierter Vorschlag erneut geprüft. Bitte den neuen Inhalt bestätigen.",
                    "log": note(state, "klaerfall", "Neuer Vorschlag benötigt eine eigene Bestätigung.")}
        person = control.decide(con, proposal, approved=True, reason=raw.get("reason", "Inhalt geprüft"))
        return {"number": new_payload["number"], "amount_eur": amount, "approved_by": person,
                "approval_id": proposal["approval_id"], "candidate_version": proposal["version"],
                "approval_decision": ApprovalDecision.APPROVED.value, "exception_case": False,
                "log": note(state, "klaerfall", "Geprüfter Inhalt freigegeben.")}
    except (PolicyDenied, identity.AuthenticationError) as error:
        log_entry(con, actor=raw.get("approver") or "unauthenticated", agent="buchung", action="freigabe_verweigert",
                  decision=Decision.DENIED, reason=str(error), reference=case_reference(state), outcome="rejected")
        con.commit()
        return {"completed": True, "outcome": CaseOutcome.REJECTED.value, "error": str(error),
                "log": note(state, "klaerfall", str(error))}
    finally:
        con.close()


def route_exception_case(state: Case) -> str:
    if state.get("completed"):
        return "ende"
    return "hitl" if state.get("exception_case") else "buchung"
