"""Erzwingt die zentrale Architekturaussage der Arbeit im Code.

"Berechtigungs- und Policy-Pruefungen laufen als regulaere Logik, NICHT im
Sprachmodell" (Abschnitt 7). Ohne diesen Test waere das eine Aussage ueber den
Code, die beim naechsten Import still kaputtgehen kann. Mit diesem Test ist es
eine Eigenschaft des Codes.

Geprueft wird statisch ueber den AST, nicht zur Laufzeit: ein bedingter Import
in einem selten genommenen Zweig wuerde einem Laufzeit-Check entgehen.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

PROJEKT_WURZEL = Path(__file__).parent.parent
GOVERNANCE_DIR = PROJEKT_WURZEL / "governance"

# Module, die ein Sprachmodell erreichbar machen -- direkt oder ueber einen
# Anbieter-SDK. `llm` ist die projekteigene Abstraktion.
VERBOTENE_MODULE = {
    "llm", "anthropic", "openai", "ollama", "langchain", "langchain_core",
    "langgraph", "httpx", "requests",
}

# Ebenen, die unterhalb der Governance liegen und daher nicht importiert
# werden duerfen (sonst entstuende ein Zyklus Governance -> Agent -> Governance).
VERBOTENE_PAKETE = {"agents", "graph", "tools", "mocks", "ui"}


def _governance_module() -> list[Path]:
    return sorted(p for p in GOVERNANCE_DIR.glob("*.py") if p.name != "__init__.py")


def _importierte_wurzelmodule(pfad: Path) -> set[str]:
    """Sammelt alle importierten Top-Level-Modulnamen einer Datei."""
    baum = ast.parse(pfad.read_text(encoding="utf-8"), filename=str(pfad))
    namen: set[str] = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.Import):
            for alias in knoten.names:
                namen.add(alias.name.split(".")[0])
        elif isinstance(knoten, ast.ImportFrom):
            # level > 0 sind relative Importe innerhalb von governance/ -- erlaubt.
            if knoten.level == 0 and knoten.module:
                namen.add(knoten.module.split(".")[0])
    return namen


def test_governance_module_existieren():
    """Schuetzt vor einem gruenen Test durch ein leeres Verzeichnis."""
    namen = {p.stem for p in _governance_module()}
    assert {"policy", "ad", "audit"} <= namen, f"Gefunden: {namen}"


@pytest.mark.parametrize("pfad", _governance_module(), ids=lambda p: p.name)
def test_governance_hat_keine_llm_abhaengigkeit(pfad: Path):
    """Kein Governance-Modul darf ein Sprachmodell erreichen koennen."""
    verboten = _importierte_wurzelmodule(pfad) & VERBOTENE_MODULE
    assert not verboten, (
        f"{pfad.name} importiert {sorted(verboten)}. Die Governance-Schicht muss "
        "deterministisch bleiben (Abschnitt 7 des Fachkonzepts): eine "
        "Berechtigungspruefung, die ein Sprachmodell entscheidet, ist keine."
    )


@pytest.mark.parametrize("pfad", _governance_module(), ids=lambda p: p.name)
def test_governance_importiert_keine_hoehere_schicht(pfad: Path):
    """Governance liegt unter den Agenten, nicht neben ihnen."""
    verboten = _importierte_wurzelmodule(pfad) & VERBOTENE_PAKETE
    assert not verboten, (
        f"{pfad.name} importiert {sorted(verboten)}. Die Governance-Schicht darf "
        "nicht von den Komponenten abhaengen, die sie kontrolliert -- sonst ist "
        "die Kontrolle umgehbar."
    )


def test_registry_ist_llm_frei():
    """Die Agenten-Konfigurationstabelle ist reine Konfiguration.

    Sie wird von der Governance gelesen und muesste sonst die Schichtgrenze
    ueber Umwege durchbrechen.
    """
    verboten = _importierte_wurzelmodule(PROJEKT_WURZEL / "registry.py") & VERBOTENE_MODULE
    assert not verboten, f"registry.py importiert {sorted(verboten)}"


def test_config_ist_llm_frei():
    """config.py wird ebenfalls von der Governance gelesen (Betragsschwelle)."""
    verboten = _importierte_wurzelmodule(PROJEKT_WURZEL / "config.py") & VERBOTENE_MODULE
    assert not verboten, f"config.py importiert {sorted(verboten)}"
