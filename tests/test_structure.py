"""Pins the key paths README.md's project-structure section names.

Not a parse of that section -- markdown prose is not worth parsing. An
independent list a maintainer updates by hand alongside the README, the
same way tests/test_flow.py's FLOW set is updated alongside
graph/workflow.py. Without this, a rename can silently leave the README
describing a layout that no longer exists -- exactly what happened twice
already this session (a stale `registry.py` reference, an inaccurate
wiring claim; see docs/abschlussbericht-thesis-angleichung.md).
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent

DOCUMENTED_PATHS = [
    "agent_registry.py",
    "process_registry.py",
    "config.py",
    "contracts.py",
    "demo.py",
    "agents/shared/classification.py",
    "agents/shared/schemas.py",
    "agents/payment_confirmation",
    "agents/incoming_invoice",
    "governance/policy.py",
    "governance/ad.py",
    "governance/audit.py",
    "tools/reader.py",
    "llm/client.py",
    "llm/extraction.py",
    "llm/preflight.py",
    "mocks/navision.py",
    "mocks/elo.py",
    "graph/workflow.py",
    "graph/state.py",
    "graph/cases.py",
    "graph/effects.py",
    "graph/nodes",
    "data/generate.py",
    "ui/app.py",
    "ui/shared",
    "ui/cases",
    "ui/cases/process_views",
    "ui/intake",
    "ui/pages",
    "tests",
    "docs",
]


def test_documented_paths_exist():
    missing = [p for p in DOCUMENTED_PATHS if not (PROJECT_ROOT / p).exists()]
    assert not missing, (
        f"README.md's project-structure section names paths that no longer "
        f"exist: {missing}. Either the code moved and the README needs "
        f"updating, or this list needs updating alongside it."
    )
