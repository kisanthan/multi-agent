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

This module only wires the graph together -- it defines no node itself.
The nodes live in `graph.nodes.shared` (the intake stretch both processes
share), `graph.nodes.payment_confirmation` (process A), and
`graph.nodes.incoming_invoice` (process B); each node is referenced here
through its module, so which process a node belongs to is visible at the
call site.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from graph.nodes import incoming_invoice, payment_confirmation, shared
from graph.state import Case


def build_graph() -> StateGraph:
    """Assembles the graph. Without a checkpointer -- the caller sets that.

    Built in the order the case actually travels, one section per node
    module: the shared intake stretch, then process A, then process B.
    Each node sits right next to its own outgoing edges, and every routing
    label is commented where it is consumed -- not where the diagram would
    otherwise force you to go looking for it. (LangGraph resolves edge
    targets at `.compile()`, not when `add_conditional_edges()` is called,
    so a target named here but added in a later section is not a forward
    reference at runtime.)
    """
    g = StateGraph(Case)

    # ------------------------------------------------- Shared intake stretch
    # reader -> classification -> orchestrator routing (graph/nodes/shared.py).
    # Both processes pass through here; from "klassifikation" on, the two
    # diverge by document type.
    g.add_node("reader", shared.node_reader)
    g.add_edge(START, "reader")
    # Scenario 5 ends directly after the reader: AD check denied.
    g.add_conditional_edges(
        "reader",
        lambda z: "ende" if z.get("completed") else "klassifikation",
        {"ende": END, "klassifikation": "klassifikation"},
    )

    g.add_node("klassifikation", shared.node_classification)
    # Orchestrator agent: routing by document type, no model call (the
    # classification agent already determined the type; see
    # shared.route_document_type).
    g.add_conditional_edges(
        "klassifikation", shared.route_document_type,
        {"prozess_a": "abgleich",       # -> process A
         "prozess_b": "kostenstelle",   # -> process B
         "hitl": "klaerfall",           # extraction failed, see node_classification
         "ende": END},
    )

    # ------------------------------------ Process A: Zahlungsbestätigung
    # abgleich -> buchung -> Navision. `klaerfall` is the only HITL point
    # and guards both callers. The booking node runs on the approval path
    # TWICE: once to request approval, once -- after a human decides -- to
    # actually book (see ui/cases/steps.py for how the stepper shows this).
    g.add_node("abgleich", payment_confirmation.node_reconciliation)
    g.add_conditional_edges("abgleich", payment_confirmation.route_reconciliation,
                            {"hitl": "klaerfall", "buchung": "buchung"})

    g.add_node("buchung", payment_confirmation.node_booking)
    g.add_conditional_edges("buchung", payment_confirmation.route_booking,
                            {"hitl": "klaerfall", "ende": END})

    g.add_node("klaerfall", payment_confirmation.node_exception_case)
    g.add_conditional_edges(
        "klaerfall", payment_confirmation.route_exception_case,
        {"buchung": "buchung",           # approved -> book (closes the cycle)
         "kostenstelle": "kostenstelle", # guard only, see route_exception_case
         "ende": END},                   # rejected
    )

    # ------------------------------------- Process B: Eingangsrechnung
    # kostenstelle -> (on ambiguity) freigabe_kostenstelle -> elo. Ends at
    # ELO (diagram part 3) -- no balance-sheet-effective booking happens in
    # process B; Navision is only ever addressed in process A.
    g.add_node("kostenstelle", incoming_invoice.node_cost_center)
    # A unique assignment proceeds automatically to archiving; only on
    # ambiguity does the four-eyes approval kick in.
    g.add_conditional_edges("kostenstelle", incoming_invoice.route_cost_center,
                            {"elo": "elo", "freigabe": "freigabe_kostenstelle"})

    g.add_node("freigabe_kostenstelle", incoming_invoice.node_cost_center_approval)
    g.add_conditional_edges("freigabe_kostenstelle", incoming_invoice.route_cost_center_approval,
                            {"elo": "elo", "ende": END})

    g.add_node("elo", incoming_invoice.node_elo)
    g.add_edge("elo", END)

    return g


def compile_graph(
    checkpoint_path: Path | str | None = None,
) -> tuple[CompiledStateGraph, sqlite3.Connection]:
    """Compiles the graph with the SQLite checkpointer.

    The checkpointer is not optional: without it, `interrupt()` could not
    hold the state and there would be no human-in-the-loop.
    """
    from langgraph.checkpoint.sqlite import SqliteSaver

    from config import CHECKPOINT_PATH

    path = Path(checkpoint_path or CHECKPOINT_PATH)
    con = sqlite3.connect(path, check_same_thread=False)
    return build_graph().compile(checkpointer=SqliteSaver(con)), con
