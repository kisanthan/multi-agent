"""The LangGraph workflow: both processes in one graph.

Maps the concept diagrams onto executable code:
- Each agent = one node.
- The orchestrator = a conditional edge on document type.
- HITL points = `interrupt()`; the checkpointer holds the state until a
  human decides.
- Policy checks live in the writing nodes, before the target-system call.
- Every step writes to the audit trail.

Why one graph for both processes: the thesis argues from *shared*
components (reader, orchestrator, classification, master data). Two
separate graphs would dissolve that claim in the code.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents import archiving, booking, classification, cost_center, reconciliation
from agents.reconciliation import Finding
from agents.schemas import DocumentType
from config import DB_PATH
from governance.audit import CaseReference, Decision, log_entry
from graph.state import Case
from tools.reader import AccessDenied, read_document


def _con() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH)


def _reference(state: Case) -> CaseReference:
    """Case reference for the audit trail.

    Every entry of a run carries the same case ID and the same document --
    only that way can the trail later be filtered to exactly this case. The
    filename is only known after the reader; before that, the path is
    enough.
    """
    return CaseReference(
        case_id=state.get("case_id"),
        source=state.get("filename") or Path(state.get("path", "")).name,
    )


def _extracted_fields(d) -> str:
    """What the extraction agent found -- as a sentence, not a dump.

    The text appears in the detail view under "What happened so far". Raw
    field names and `None` would not belong there; whatever was not found
    is named as such.
    """
    found = []
    if d.number:
        found.append(f"Rechnungsnummer {d.number}")
    if d.amount_eur is not None:
        found.append(f"Betrag {d.amount_eur:.2f} EUR".replace(".", ","))
    if d.supplier:
        found.append(f"Lieferant {d.supplier}")
    if d.cost_center_reference:
        found.append(f"Kostenstelle {d.cost_center_reference}")

    if not found:
        return "Beleg ausgewertet, aber keine verwertbaren Angaben gefunden."
    return "Erkannt: " + ", ".join(found) + "."


def _note(state: Case, node: str, text: str) -> list[dict]:
    """Appends a step to the run log (for UI and CLI output)."""
    return [*state.get("log", []), {"node": node, "text": text}]


# --------------------------------------------------------------- Nodes

def node_reader(state: Case) -> dict:
    """Reader tool. The AD check sits inside `read_document` (Least Privilege)."""
    con = _con()
    try:
        content = read_document(con, state["path"], actor=state["actor"],
                                reference=_reference(state))
    except AccessDenied as e:
        # Scenario 5: end of the case. No parsing, no model, no target system.
        return {
            "completed": True,
            "outcome": "zugriff_verweigert",
            "error": str(e),
            "log": _note(state, "reader",
                        f"Zugriff nicht erlaubt: {e}"),
        }
    finally:
        con.close()

    return {
        "markdown": content.markdown,
        "document_hash": content.document_hash,
        "filename": content.filename,
        "log": _note(
            state, "reader",
            f"{content.filename} eingelesen, {content.pages} Seite(n)."),
    }


def node_classification(state: Case) -> dict:
    """Classification & extraction agent: type and fields in one pass."""
    con = _con()
    try:
        e = classification.classify(con, markdown=state["markdown"],
                                    actor=state["actor"],
                                    reference=_reference(state))
    finally:
        con.close()

    if not e.succeeded:
        # R1: the model does not honor the schema -> exception case instead of guessing.
        return {
            "exception_case": True,
            "exception_reason": e.escalation or "Extraktion fehlgeschlagen",
            "escalation": e.escalation,
            "document_type": DocumentType.UNKNOWN.value,
            "log": _note(
                state, "klassifikation",
                "Der Beleg konnte nicht ausgewertet werden – eine Person "
                "muss entscheiden."),
        }

    d = e.data
    return {
        "document_type": d.type.value,
        "number": d.number,
        "amount_eur": d.amount_eur,
        "supplier": d.supplier,
        "line_items": d.line_items,
        "cost_center_reference": d.cost_center_reference,
        "log": _note(state, "klassifikation", _extracted_fields(d)),
    }


def route_document_type(state: Case) -> str:
    """Orchestrator agent: conditional edge on document type.

    No model call: the type is already known (the classification agent
    determined it). The orchestrator merely *routes* on it -- asking a
    model again here would be a second call with the potential to
    contradict the first.
    """
    if state.get("completed"):
        return "ende"
    if state.get("exception_case"):
        return "hitl"
    t = state.get("document_type")
    if t == DocumentType.PAYMENT_CONFIRMATION.value:
        return "prozess_a"
    if t == DocumentType.INCOMING_INVOICE.value:
        return "prozess_b"
    return "hitl"


# ---------------------------------------------------------- Process A

def node_reconciliation(state: Case) -> dict:
    """Reconciliation agent (level 1). Deterministic -- see agents/reconciliation.py."""
    con = _con()
    try:
        e = reconciliation.reconcile(con, number=state.get("number"),
                                     amount_eur=state.get("amount_eur"),
                                     actor=state["actor"], reference=_reference(state))
    finally:
        con.close()

    return {
        "finding": e.finding.value,
        "number": e.number,
        "expected_amount_eur": e.expected_amount_eur,
        "exception_case": e.is_exception_case,
        "exception_reason": e.reason if e.is_exception_case else "",
        "log": _note(state, "abgleich", e.reason),
    }


def route_reconciliation(state: Case) -> str:
    return "hitl" if state.get("exception_case") else "buchung"


def node_booking(state: Case) -> dict:
    """Booking agent (level 3). Asks the policy -- which decides on HITL."""
    con = _con()
    try:
        e = booking.book(
            con, number=state["number"], amount_eur=state["amount_eur"],
            actor=state["actor"], document=state["filename"],
            approved_by=state.get("approved_by"),
            reference=_reference(state),
        )
    finally:
        con.close()

    if e.approval_needed:
        return {
            "exception_case": True,
            "exception_reason": e.reason,
            "log": _note(
                state, "buchung",
                "Die Buchung muss von einer Person bestätigt werden."),
        }

    return {
        "completed": True,
        "outcome": "verbucht" if e.booked else "abgelehnt",
        "error": e.error,
        "log": _note(state, "buchung", e.reason),
    }


def route_booking(state: Case) -> str:
    """After the booking attempt: either done, or approval needed."""
    if state.get("completed"):
        return "ende"
    return "hitl"


# ---------------------------------------------------------- Process B

def node_cost_center(state: Case) -> dict:
    """Cost-center agent (level 2): exact referential lookup.

    Deterministic -- no language model (Thesis §7.4, see agents/cost_center.py).
    Resolves the reference extracted from the document against the catalog.
    """
    con = _con()
    try:
        z = cost_center.assign(con, cost_center_reference=state.get("cost_center_reference"),
                               actor=state["actor"],
                               line_items=state.get("line_items", []),
                               reference=_reference(state))
    finally:
        con.close()

    return {
        "cost_center_id": z.cost_center_id,
        "cost_center_reason": z.reason,
        "cost_center_unique": z.unique,
        "log": _note(state, "kostenstelle", z.reason),
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
    con = _con()
    try:
        catalog = cost_center.catalog(con)
    finally:
        con.close()

    response = interrupt({
        "kind": "kostenstellen_freigabe",
        "filename": state.get("filename"),
        "supplier": state.get("supplier"),
        "amount_eur": state.get("amount_eur"),
        "line_items": state.get("line_items", []),
        "reference": state.get("cost_center_reference"),
        "reason": state.get("cost_center_reason"),
        "catalog": [{"id": k[0], "name": k[1], "reference": k[2]} for k in catalog],
        "unique": state.get("cost_center_unique"),
    })

    con = _con()
    try:
        log_entry(
            con, actor=response["approver"], agent="kostenstelle",
            action="kostenstelle_freigegeben",
            decision=(Decision.ALLOWED if response["decision"] == "freigegeben"
                     else Decision.DENIED),
            reason=f"{response['approver']} hat "
                   f"{response.get('cost_center_id')} {response['decision']}.",
            payload={"cost_center_id": response.get("cost_center_id"),
                    "vorschlag_agent": state.get("cost_center_id")},
            reference=_reference(state), outcome=response["decision"],
        )
        con.commit()
    finally:
        con.close()

    if response["decision"] != "freigegeben":
        return {
            "completed": True,
            "outcome": "verworfen",
            "approved_by": response["approver"],
            "log": _note(state, "freigabe",
                        f"{response['approver']} hat abgelehnt."),
        }

    return {
        "cost_center_id": response["cost_center_id"],
        "approved_by": response["approver"],
        "approval_decision": "freigegeben",
        "log": _note(state, "freigabe",
                    f"{response['approver']} hat "
                    f"{response['cost_center_id']} bestätigt."),
    }


def route_cost_center_approval(state: Case) -> str:
    return "ende" if state.get("completed") else "elo"


def node_elo(state: Case) -> dict:
    """ELO agent (level 3): tamper-evident archiving. End of process B.

    Per diagram part 3, process B ends here -- a balance-sheet-effective
    booking in Navision does not happen in process B. Navision (NAV) is only
    ever addressed in process A (booking agent, open -> paid).
    """
    con = _con()
    try:
        e = archiving.archive_document(con, filename=state["filename"],
                                       document_hash=state["document_hash"],
                                       actor=state["actor"], reference=_reference(state))
    finally:
        con.close()

    if not e.successful:
        return {
            "completed": True,
            "outcome": "archivierung_fehlgeschlagen",
            "error": e.error,
            "log": _note(state, "elo", e.reason),
        }
    return {
        "completed": True,
        "outcome": "archiviert",
        "archive_id": e.reference_id,
        "log": _note(state, "elo", e.reason),
    }


# ------------------------------------------------------------ HITL A

def node_exception_case(state: Case) -> dict:
    """HITL point of process A: exception case or booking approval.

    Covers both cases because they ask the same question of the same
    human: 'Book this case anyway?' The reason is in the payload.
    """
    response = interrupt({
        "kind": "klaerfall",
        "filename": state.get("filename"),
        "reason": state.get("exception_reason"),
        "finding": state.get("finding"),
        "number": state.get("number"),
        "amount_eur": state.get("amount_eur"),
        "expected_amount_eur": state.get("expected_amount_eur"),
        "escalation": state.get("escalation"),
    })

    if response["decision"] != "freigegeben":
        con = _con()
        try:
            log_entry(con, actor=response["approver"], agent="buchung",
                     action="klaerfall_entschieden",
                     decision=Decision.DENIED,
                     reason=f"{response['approver']} hat den Vorgang verworfen.",
                     payload={"number": state.get("number")},
                     reference=_reference(state), outcome="verworfen")
            con.commit()
        finally:
            con.close()
        return {
            "completed": True,
            "outcome": "verworfen",
            "approved_by": response["approver"],
            "log": _note(state, "klaerfall",
                        f"{response['approver']} hat abgelehnt."),
        }

    # The approver may correct the number (case 'unknown number').
    return {
        "number": response.get("number") or state.get("number"),
        "approved_by": response["approver"],
        "approval_decision": "freigegeben",
        "exception_case": False,
        "log": _note(state, "klaerfall",
                    f"{response['approver']} hat bestätigt."),
    }


def route_exception_case(state: Case) -> str:
    if state.get("completed"):
        return "ende"
    # After approval, back to the matching process. An exception case can
    # also arise from a failed classification of an incoming invoice -- in
    # that case a payment must not be wrongly booked.
    if state.get("document_type") == DocumentType.INCOMING_INVOICE.value:
        return "kostenstelle"
    return "buchung"


# --------------------------------------------------------------- Graph

def build_graph():
    """Assembles the graph. Without a checkpointer -- the caller sets that."""
    g = StateGraph(Case)

    g.add_node("reader", node_reader)
    g.add_node("klassifikation", node_classification)
    g.add_node("abgleich", node_reconciliation)
    g.add_node("buchung", node_booking)
    g.add_node("klaerfall", node_exception_case)
    g.add_node("kostenstelle", node_cost_center)
    g.add_node("freigabe_kostenstelle", node_cost_center_approval)
    g.add_node("elo", node_elo)

    g.add_edge(START, "reader")

    # Scenario 5 ends directly after the reader.
    g.add_conditional_edges(
        "reader",
        lambda z: "ende" if z.get("completed") else "klassifikation",
        {"ende": END, "klassifikation": "klassifikation"},
    )

    # Orchestrator routing by document type.
    g.add_conditional_edges(
        "klassifikation", route_document_type,
        {"prozess_a": "abgleich", "prozess_b": "kostenstelle",
         "hitl": "klaerfall", "ende": END},
    )

    # Process A
    g.add_conditional_edges("abgleich", route_reconciliation,
                            {"hitl": "klaerfall", "buchung": "buchung"})
    g.add_conditional_edges("buchung", route_booking,
                            {"hitl": "klaerfall", "ende": END})
    g.add_conditional_edges("klaerfall", route_exception_case,
                            {"buchung": "buchung", "kostenstelle": "kostenstelle",
                             "ende": END})

    # Process B -- ends at ELO (diagram part 3).
    # A unique assignment proceeds automatically to archiving; only on
    # ambiguity does the four-eyes approval kick in.
    g.add_conditional_edges("kostenstelle", route_cost_center,
                            {"elo": "elo", "freigabe": "freigabe_kostenstelle"})
    g.add_conditional_edges("freigabe_kostenstelle", route_cost_center_approval,
                            {"elo": "elo", "ende": END})
    g.add_edge("elo", END)

    return g


def compile_graph(checkpoint_path: Path | str | None = None):
    """Compiles the graph with the SQLite checkpointer.

    The checkpointer is not optional: without it, `interrupt()` could not
    hold the state and there would be no human-in-the-loop.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    from config import CHECKPOINT_PATH

    path = Path(checkpoint_path or CHECKPOINT_PATH)
    con = sqlite3.connect(path, check_same_thread=False)
    return build_graph().compile(checkpointer=SqliteSaver(con)), con
