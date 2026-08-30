"""Process B (Eingangsrechnung / incoming invoice) nodes.

Cost-center assignment -> (on ambiguity) four-eyes approval -> archiving in
ELO. Imports only process B's own agents (`agents.incoming_invoice`) plus
the shared helpers in `graph.nodes.shared` -- nothing from process A.
"""

from __future__ import annotations

from langgraph.types import interrupt

from agents.incoming_invoice import archiving, cost_center, extraction
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


def node_invoice_extraction(state: Case) -> dict:
    """Use process B's independently configured extraction profile."""
    con = connection()
    try:
        result = extraction.extract_invoice(
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
                "log": note(state, "extraktion_rechnung",
                            "Rechnungsextraktion nicht erreichbar – sicher angehalten."),
            }
        return {
            "number": None, "amount_eur": None, "supplier": None,
            "line_items": [], "cost_center_reference": None,
            "exception_case": True,
            "exception_reason": result.escalation or "Extraktion fehlgeschlagen",
            "escalation": result.escalation,
            "log": note(state, "extraktion_rechnung",
                        "Rechnungsdaten konnten nicht sicher ausgelesen werden."),
        }
    data = result.data
    return {
        "number": data.number,
        "amount_eur": data.amount_eur,
        "supplier": data.supplier,
        "line_items": data.line_items,
        "cost_center_reference": data.cost_center_reference,
        "log": note(state, "extraktion_rechnung", "Rechnungsdaten ausgelesen."),
    }


def route_invoice_extraction(state: Case) -> str:
    return "ende" if state.get("completed") else "kostenstelle"


def node_cost_center(state: Case) -> dict:
    """Cost-center agent (level 2): exact referential lookup.

    Deterministic -- no language model (Thesis §7.4, see
    agents/incoming_invoice/cost_center.py). Resolves the reference
    extracted from the document against the catalog.
    """
    con = connection()
    try:
        z = cost_center.assign(con, cost_center_reference=state.get("cost_center_reference"),
                               actor=state["actor"],
                               line_items=state.get("line_items", []),
                               reference=case_reference(state))
    finally:
        con.close()

    return {
        "cost_center_id": z.cost_center_id,
        "cost_center_reason": z.reason,
        "cost_center_unique": z.unique,
        "log": note(state, "kostenstelle", z.reason),
    }


def route_cost_center(state: Case) -> str:
    """Assignment unique? (diagram part 3).

    The cost-center agent is human-on-the-loop: if it resolves the document
    reference to a unique cost center, the case proceeds automatically to
    archiving. If the reference is missing or unknown, the four-eyes
    approval kicks in. Mirrors process A (number present? -> direct or
    exception case).
    """
    if state.get("cost_center_unique"):
        return "elo"
    return "freigabe"


def node_cost_center_approval(state: Case) -> dict:
    """HITL point of process B: four-eyes approval on ambiguity.

    Only reached when the assignment is NOT unique (exception case). On a
    unique assignment, route_cost_center skips this node -- the cost-center
    agent is human-on-the-loop.
    """
    # If the document reference is missing, the human picks from the full catalog.
    con = connection()
    try:
        catalog = cost_center.catalog(con)
    finally:
        con.close()

    response = ApprovalResponse.from_resume(interrupt(ApprovalRequest(
        kind=InterruptKind.COST_CENTER_APPROVAL,
        # Always an escalation: the cost-center agent is human-on-the-loop
        # and only ever reaches this node when it could not resolve the
        # reference itself (see route_cost_center).
        trigger=ApprovalTrigger.ESCALATION,
        filename=state.get("filename"),
        supplier=state.get("supplier"),
        amount_eur=state.get("amount_eur"),
        line_items=tuple(state.get("line_items", [])),
        reference=state.get("cost_center_reference"),
        reason=state.get("cost_center_reason"),
        catalog=tuple({"id": k[0], "name": k[1], "reference": k[2]} for k in catalog),
        unique=state.get("cost_center_unique"),
    ).as_payload()))

    # Four-eyes principle, enforced here and not just in the UI -- see the
    # matching comment in
    # graph/nodes/payment_confirmation.py::node_exception_case.
    con = connection()
    try:
        permission = check_approval(con, actor=response.approver, agent_id="kostenstelle")
        if not permission.allowed:
            log_entry(con, actor=response.approver, agent="kostenstelle",
                     action="freigabe_verweigert",
                     decision=Decision.DENIED,
                     reason=permission.reason,
                     payload={"cost_center_id": response.cost_center_id},
                     reference=case_reference(state), outcome=CaseOutcome.REJECTED.value)
            con.commit()
    finally:
        con.close()

    if not permission.allowed:
        return {
            "completed": True,
            "outcome": CaseOutcome.REJECTED.value,
            "approved_by": response.approver,
            "log": note(state, "freigabe",
                       f"Freigabe verweigert: {permission.reason}"),
        }

    con = connection()
    try:
        log_entry(
            con, actor=response.approver, agent="kostenstelle",
            # Two action names, not one: mirrors process A, where an
            # approval is logged as `freigabe_erteilt` and a rejection as
            # `klaerfall_entschieden` (agents/payment_confirmation/booking.py,
            # graph/nodes/payment_confirmation.py). A single name for both
            # outcomes here previously meant "…freigegeben" was written even
            # when the human had just rejected the case.
            action=("kostenstelle_freigegeben" if response.approved
                   else "kostenstelle_verworfen"),
            decision=Decision.ALLOWED if response.approved else Decision.DENIED,
            reason=f"{response.approver} hat "
                   f"{response.cost_center_id} {response.decision.value}.",
            payload={"cost_center_id": response.cost_center_id,
                    "vorschlag_agent": state.get("cost_center_id")},
            reference=case_reference(state), outcome=response.decision.value,
        )
        con.commit()
    finally:
        con.close()

    if not response.approved:
        return {
            "completed": True,
            "outcome": CaseOutcome.REJECTED.value,
            "approved_by": response.approver,
            "log": note(state, "freigabe",
                       f"{response.approver} hat abgelehnt."),
        }

    # Falls back to the agent's own proposal if the approver's pick did not
    # make it into the resume payload (e.g. an empty catalog) -- previously
    # a hard `response["cost_center_id"]` index, which would have raised
    # KeyError in exactly that case instead of degrading gracefully.
    cost_center_id = response.cost_center_id or state.get("cost_center_id")
    return {
        "cost_center_id": cost_center_id,
        "approved_by": response.approver,
        "approval_decision": ApprovalDecision.APPROVED.value,
        "log": note(state, "freigabe",
                   f"{response.approver} hat "
                   f"{cost_center_id} bestätigt."),
    }


def route_cost_center_approval(state: Case) -> str:
    return "ende" if state.get("completed") else "elo"


def node_elo(state: Case) -> dict:
    """ELO agent (level 3): tamper-evident archiving. End of process B.

    Per diagram part 3, process B ends here -- a balance-sheet-effective
    booking in Navision does not happen in process B. Navision (NAV) is only
    ever addressed in process A (booking agent, open -> paid).
    """
    con = connection()
    try:
        e = archiving.archive_document(con, filename=state["filename"],
                                       document_hash=state["document_hash"],
                                       actor=state["actor"], reference=case_reference(state))
    finally:
        con.close()

    if not e.successful:
        return {
            "completed": True,
            "outcome": CaseOutcome.ARCHIVING_FAILED.value,
            "error": e.error,
            "log": note(state, "elo", e.reason),
        }
    return {
        "completed": True,
        "outcome": CaseOutcome.ARCHIVED.value,
        "archive_id": e.reference_id,
        "log": note(state, "elo", e.reason),
    }
