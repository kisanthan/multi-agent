"""Pins both process flows against the compiled graph itself.

Three things could otherwise drift apart unnoticed: the routing labels a
graph node module returns, the step list `process_registry.py` declares for
the UI, and the two copies of the generated diagram (`docs/flow.mmd` and
its embed in `docs/architektur.md`). All three are checked here against
LangGraph's own `get_graph()` -- the one thing that cannot be out of date,
because it *is* the running graph, not a description of it.
"""

from __future__ import annotations

import re
from pathlib import Path

import process_registry
from graph.workflow import build_graph

PROJECT_ROOT = Path(__file__).parent.parent
FLOW_MMD = PROJECT_ROOT / "docs" / "flow.mmd"
ARCHITEKTUR_MD = PROJECT_ROOT / "docs" / "architektur.md"


# The compiled graph's edges, one section per node module (see
# graph/workflow.py). A (source, target, label) triple changes only when
# the graph itself changes -- `get_graph().edges` is stable public API,
# unlike the `draw_mermaid()` string used further down.
FLOW = {
    ("__start__", "reader", None),
    ("reader", "__end__", "ende"),
    ("reader", "klassifikation", None),
    ("klassifikation", "__end__", "ende"),
    ("klassifikation", "abgleich", "prozess_a"),
    ("klassifikation", "kostenstelle", "prozess_b"),
    ("klassifikation", "klaerfall", "hitl"),
    ("abgleich", "buchung", None),
    ("abgleich", "klaerfall", "hitl"),
    ("buchung", "__end__", "ende"),
    ("buchung", "klaerfall", "hitl"),
    ("klaerfall", "__end__", "ende"),
    ("klaerfall", "buchung", None),
    ("klaerfall", "kostenstelle", None),
    ("kostenstelle", "elo", None),
    ("kostenstelle", "freigabe_kostenstelle", "freigabe"),
    ("freigabe_kostenstelle", "elo", None),
    ("freigabe_kostenstelle", "__end__", "ende"),
    ("elo", "__end__", None),
}


def test_graph_matches_the_declared_flow():
    """FLOW above is not prose -- it is checked against the compiled
    graph. Adding, removing, or rewiring a node in graph/workflow.py fails
    this test until FLOW is updated to match, so the table can never just
    fall out of sync with what actually runs."""
    edges = build_graph().compile().get_graph().edges
    assert {(e.source, e.target, e.data) for e in edges} == FLOW


def test_every_process_step_maps_to_a_graph_node():
    """process_registry.ProcessStep entries describe the UI-facing step
    list; this checks they name every actual LangGraph node exactly once --
    via `graph_node` where the run-log namespace and the graph namespace
    differ (today only `freigabe` / `freigabe_kostenstelle`, see
    ProcessStep's docstring)."""
    nodes = set(build_graph().compile().get_graph().nodes) - {"__start__", "__end__"}
    all_steps = (*process_registry.SHARED_STEPS,
                *(s for p in process_registry.PROCESSES.values() for s in p.own_steps))
    declared = {s.graph_node or s.node for s in all_steps}
    assert declared == nodes


def _edge_lines(mermaid: str) -> set[str]:
    """The edge lines of a `draw_mermaid()` string, whitespace- and
    `&nbsp;`-normalized.

    Deliberately not a byte comparison: the YAML frontmatter, the
    `classDef` lines, and the node-shape markup (`name(name)` vs.
    `name([<p>name</p>])`) are pure presentation and can change with a
    LangGraph version bump without the graph itself changing. A line is an
    edge if it contains an arrow (`->`) -- node declarations and classDef
    lines never do.
    """
    lines: set[str] = set()
    for raw in mermaid.splitlines():
        line = raw.strip().rstrip(";")
        if "->" not in line:
            continue
        lines.add(" ".join(line.replace("&nbsp;", " ").split()))
    return lines


def _current_flow_edges() -> set[str]:
    return _edge_lines(build_graph().compile().get_graph().draw_mermaid())


def test_flow_mmd_matches_the_compiled_graph():
    """docs/flow.mmd is generated, not hand-authored (see the regeneration
    command in its own header comment) -- this is the tripwire for when
    graph/workflow.py changes and nobody regenerates it."""
    stored = FLOW_MMD.read_text(encoding="utf-8")
    assert _edge_lines(stored) == _current_flow_edges(), (
        "docs/flow.mmd is stale -- regenerate it with the command in its "
        "own header comment."
    )


def test_architektur_md_embeds_the_current_flow_diagram():
    """docs/architektur.md keeps its own copy of the diagram so it renders
    inline without following a link to docs/flow.mmd. Checked separately
    from docs/flow.mmd (both against the compiled graph, not against each
    other) so a failure here points at exactly which copy went stale."""
    text = ARCHITEKTUR_MD.read_text(encoding="utf-8")
    match = re.search(r"```mermaid\n(.*?)```", text, re.DOTALL)
    assert match, "docs/architektur.md no longer embeds a ```mermaid block."
    assert _edge_lines(match.group(1)) == _current_flow_edges(), (
        "The flow diagram embedded in docs/architektur.md is stale -- "
        "regenerate docs/flow.mmd and paste its graph body back in."
    )
