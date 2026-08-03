"""Enforces the thesis's central architectural claim in code.

"Permission and policy checks run as regular logic, NOT inside the language
model" (section 7). Without this test, that would be a statement about the
code that could silently break on the next import. With this test, it is a
property of the code.

Checked statically via the AST, not at runtime: a conditional import in a
rarely taken branch would escape a runtime check.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
GOVERNANCE_DIR = PROJECT_ROOT / "governance"

# Modules that make a language model reachable -- directly or via a
# provider SDK. `llm` is the project's own abstraction.
FORBIDDEN_MODULES = {
    "llm", "anthropic", "openai", "ollama", "langchain", "langchain_core",
    "langgraph", "httpx", "requests",
}

# Layers that sit below governance and therefore must not be imported
# (otherwise a cycle governance -> agent -> governance would arise).
FORBIDDEN_PACKAGES = {"agents", "graph", "tools", "mocks", "ui"}


def _governance_modules() -> list[Path]:
    return sorted(p for p in GOVERNANCE_DIR.glob("*.py") if p.name != "__init__.py")


def _imported_root_modules(path: Path) -> set[str]:
    """Collects all imported top-level module names of a file."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            # level > 0 are relative imports within governance/ -- allowed.
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def test_governance_modules_exist():
    """Guards against a green test due to an empty directory."""
    names = {p.stem for p in _governance_modules()}
    assert {"policy", "ad", "audit"} <= names, f"Gefunden: {names}"


@pytest.mark.parametrize("path", _governance_modules(), ids=lambda p: p.name)
def test_governance_has_no_llm_dependency(path: Path):
    """No governance module may be able to reach a language model."""
    forbidden = _imported_root_modules(path) & FORBIDDEN_MODULES
    assert not forbidden, (
        f"{path.name} importiert {sorted(forbidden)}. Die Governance-Schicht muss "
        "deterministisch bleiben (Abschnitt 7 des Fachkonzepts): eine "
        "Berechtigungspruefung, die ein Sprachmodell entscheidet, ist keine."
    )


@pytest.mark.parametrize("path", _governance_modules(), ids=lambda p: p.name)
def test_governance_does_not_import_a_higher_layer(path: Path):
    """Governance sits below the agents, not next to them."""
    forbidden = _imported_root_modules(path) & FORBIDDEN_PACKAGES
    assert not forbidden, (
        f"{path.name} importiert {sorted(forbidden)}. Die Governance-Schicht darf "
        "nicht von den Komponenten abhaengen, die sie kontrolliert -- sonst ist "
        "die Kontrolle umgehbar."
    )


def test_registry_is_llm_free():
    """The agent configuration table is pure configuration.

    It is read by governance and would otherwise break the layer boundary
    through a detour.
    """
    forbidden = _imported_root_modules(PROJECT_ROOT / "registry.py") & FORBIDDEN_MODULES
    assert not forbidden, f"registry.py importiert {sorted(forbidden)}"


def test_config_is_llm_free():
    """config.py is also read by governance (amount threshold)."""
    forbidden = _imported_root_modules(PROJECT_ROOT / "config.py") & FORBIDDEN_MODULES
    assert not forbidden, f"config.py importiert {sorted(forbidden)}"
