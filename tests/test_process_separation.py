"""Enforces the process A / process B separation in code.

Mirrors tests/test_layer_boundaries.py's technique (static AST analysis,
not a runtime check) but at the level of individual modules: process A's
node module must not import process B's agents, and vice versa, and the
shared/wiring files must not import either process's agents at all.
Without this test, "the processes are separated" would be a claim about
the file layout that the next edit could quietly undo.
"""

from __future__ import annotations

import ast
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

PAYMENT_CONFIRMATION_NODES = PROJECT_ROOT / "graph" / "nodes" / "payment_confirmation.py"
INCOMING_INVOICE_NODES = PROJECT_ROOT / "graph" / "nodes" / "incoming_invoice.py"
SHARED_NODES = PROJECT_ROOT / "graph" / "nodes" / "shared.py"
WORKFLOW = PROJECT_ROOT / "graph" / "workflow.py"
DETAIL_VIEW = PROJECT_ROOT / "ui" / "cases" / "detail.py"


def _imported_modules(path: Path) -> set[str]:
    """Full dotted module paths imported by a file (not just the root).

    Unlike tests/test_layer_boundaries.py's `_imported_root_modules`, this
    keeps the whole path -- `agents.incoming_invoice` and
    `agents.payment_confirmation` share the same root (`agents`) and would
    be indistinguishable if only the root were kept.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                modules.add(node.module)
    return modules


def _imports_under(modules: set[str], prefix: str) -> bool:
    return any(m == prefix or m.startswith(prefix + ".") for m in modules)


def test_payment_confirmation_nodes_do_not_import_incoming_invoice_agents():
    modules = _imported_modules(PAYMENT_CONFIRMATION_NODES)
    assert not _imports_under(modules, "agents.incoming_invoice"), (
        f"{PAYMENT_CONFIRMATION_NODES.name} importiert aus agents.incoming_invoice "
        "-- Prozess A darf nicht von Prozess B abhaengen."
    )


def test_incoming_invoice_nodes_do_not_import_payment_confirmation_agents():
    modules = _imported_modules(INCOMING_INVOICE_NODES)
    assert not _imports_under(modules, "agents.payment_confirmation"), (
        f"{INCOMING_INVOICE_NODES.name} importiert aus agents.payment_confirmation "
        "-- Prozess B darf nicht von Prozess A abhaengen."
    )


def test_shared_nodes_import_neither_process_agents():
    modules = _imported_modules(SHARED_NODES)
    for prefix in ("agents.payment_confirmation", "agents.incoming_invoice"):
        assert not _imports_under(modules, prefix), (
            f"{SHARED_NODES.name} importiert aus {prefix} -- der geteilte "
            "Einstieg darf keinen Prozess kennen."
        )


def test_workflow_only_wires_nodes_together():
    """graph/workflow.py assembles the graph; it defines no node and knows
    no agent directly."""
    modules = _imported_modules(WORKFLOW)
    assert not _imports_under(modules, "agents"), (
        f"{WORKFLOW.name} importiert ein agents-Modul direkt -- das gehoert "
        "in graph/nodes/*, nicht in die Verdrahtung."
    )


def test_detail_view_knows_no_agent_directly():
    """The shared case-detail shell resolves process differences through
    ui/cases/process_views, not by importing an agent module itself."""
    modules = _imported_modules(DETAIL_VIEW)
    assert not _imports_under(modules, "agents"), (
        f"{DETAIL_VIEW.name} importiert ein agents-Modul direkt -- "
        "Prozessunterschiede gehoeren nach ui/cases/process_views/."
    )
