"""The agent configuration table from the functional concept, as effective data.

This module deliberately lives at the top level and not inside `agents/`: both
the agents and the governance layer read from it, and `governance/` must not
depend on `agents/` (see tests/test_layer_boundaries.py). The table is pure
configuration with no behavior and no LLM dependency.

Autonomy levels follow Parasuraman et al. (2000); oversight modes follow
chapter 2.2 of the thesis. A change here changes runtime behavior -- the
table is enforcement, not documentation.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AgentType(str, Enum):
    """Functional types from chapter 2.2 / 3.3 / 3.4 of the thesis.

    Personal Agents do not occur in these two processes; all domain agents
    are Shared Domain Agents. A `System Agent` as a functional type does not
    exist in the thesis's typology.
    """

    SHARED_DOMAIN = "Shared Domain"
    ORCHESTRATOR = "Orchestrator"
    POLICY = "Policy-Governance"
    AUDIT = "Audit-Monitoring"
    NOT_AN_AGENT = "kein Agent (deterministisch)"


class AutonomyLevel(int, Enum):
    """Per Parasuraman et al. (2000), instantiated according to chapter 3.4."""

    READ_ACCESS = 1
    PROPOSAL = 2
    REVERSIBLE_WRITE = 3
    IRREVERSIBLE_ACTION = 4


class OversightMode(str, Enum):
    """Oversight modes per chapter 2.2."""

    HUMAN_LED = "Human-led"
    HUMAN_IN_THE_LOOP = "Human-in-the-loop"
    HUMAN_ON_THE_LOOP = "Human-on-the-loop"
    FULLY_AUTOMATED = "vollautomatisiert"
    DETERMINISTIC = "deterministisch (kein LLM)"
    READ_ONLY = "read-only"


class ModelClass(str, Enum):
    """Model assignment by risk (concept diagram `teil2_ki_modelle.png`).

    The concrete model IDs live in config.py -- only the risk class lives
    here, so the assignment stays an architectural statement and not a
    dependency on a specific provider.
    """

    NO_MODEL = "kein Modell"
    LOCAL_SMALL = "lokal/klein"
    VISION = "vision-faehig"
    FRONTIER = "Frontier"


@dataclass(frozen=True)
class AgentConfig:
    name: str
    type: AgentType
    autonomy_level: AutonomyLevel | None
    oversight: OversightMode
    model_class: ModelClass
    processes: tuple[str, ...]
    can_write: bool
    description: str


# The table from section 1 of the functional concept, 1:1.
REGISTRY: dict[str, AgentConfig] = {
    "reader": AgentConfig(
        name="Reader-Tool",
        type=AgentType.NOT_AN_AGENT,
        autonomy_level=None,
        oversight=OversightMode.DETERMINISTIC,
        model_class=ModelClass.NO_MODEL,
        processes=("A", "B"),
        can_write=False,
        description="PDF -> Markdown. Kein KI-Agent. Zugriff nur fuer Mitglieder "
        "der AD-Sicherheitsgruppe (Least Privilege).",
    ),
    "orchestrator": AgentConfig(
        name="Orchestrator-Agent",
        type=AgentType.ORCHESTRATOR,
        autonomy_level=None,
        oversight=OversightMode.HUMAN_ON_THE_LOOP,
        model_class=ModelClass.LOCAL_SMALL,
        processes=("A", "B"),
        can_write=False,
        description="Routet nach Dokumenttyp und steuert den Workflow.",
    ),
    "klassifikation": AgentConfig(
        name="Klassifikations- & Extraktions-Agent",
        type=AgentType.SHARED_DOMAIN,
        # The table names "1-2"; the upper bound governs, because the policy
        # checks against the highest claimed level.
        autonomy_level=AutonomyLevel.PROPOSAL,
        oversight=OversightMode.HUMAN_ON_THE_LOOP,
        model_class=ModelClass.VISION,
        processes=("A", "B"),
        can_write=False,
        description="Bestimmt in einem Durchgang Dokumenttyp UND extrahiert die "
        "relevanten Felder.",
    ),
    "abgleich": AgentConfig(
        name="Abgleich-Agent",
        type=AgentType.SHARED_DOMAIN,
        autonomy_level=AutonomyLevel.READ_ACCESS,
        oversight=OversightMode.HUMAN_ON_THE_LOOP,
        # No model: exact primary-key lookup (Thesis §7.4, docs/mapping.md I1)
        # -- same as the cost-center agent.
        model_class=ModelClass.NO_MODEL,
        processes=("A",),
        can_write=False,
        description="Gleicht die extrahierte Rechnungs-/Bestellnummer exakt gegen "
        "die Stammdatenbasis ab (deterministisch). Nur Lesezugriff.",
    ),
    "buchung": AgentConfig(
        name="Buchungs-Agent",
        type=AgentType.SHARED_DOMAIN,
        autonomy_level=AutonomyLevel.REVERSIBLE_WRITE,
        # Thesis §7.4 / Table 11: the financially effective booking step is
        # human-in-the-loop -- every booking requires human approval.
        # Coupling "rising autonomy -> tighter oversight" (chapter 2.2).
        oversight=OversightMode.HUMAN_IN_THE_LOOP,
        model_class=ModelClass.FRONTIER,
        processes=("A",),
        can_write=True,
        description="Verbucht die Zahlung im ERP, Status offen -> bezahlt. "
        "Finanzwirksam, daher immer freigabepflichtig (Human-in-the-loop).",
    ),
    "kostenstelle": AgentConfig(
        name="Kostenstellen-Agent",
        type=AgentType.SHARED_DOMAIN,
        autonomy_level=AutonomyLevel.PROPOSAL,
        # Diagram part 3: human-on-the-loop. If the document reference
        # resolves to exactly one cost center, the case proceeds
        # automatically to archiving; if the reference is missing or
        # unknown, the four-eyes approval kicks in (exception case). Mirrors
        # process A.
        oversight=OversightMode.HUMAN_ON_THE_LOOP,
        # No model: the assignment is an exact referential lookup (Thesis
        # §7.4), not semantic matching -- same as the reconciliation agent.
        # Extracting the reference itself is done by the classification agent.
        model_class=ModelClass.NO_MODEL,
        processes=("B",),
        can_write=False,
        description="Schlaegt die Kostenstellenreferenz des Belegs exakt im "
        "Katalog nach (deterministisch). Fehlt sie, Vier-Augen-Freigabe.",
    ),
    "elo": AgentConfig(
        name="ELO-Agent",
        type=AgentType.SHARED_DOMAIN,
        autonomy_level=AutonomyLevel.REVERSIBLE_WRITE,
        oversight=OversightMode.HUMAN_ON_THE_LOOP,
        model_class=ModelClass.LOCAL_SMALL,
        processes=("B",),
        can_write=True,
        description="Archiviert die Rechnung revisionssicher im DMS. "
        "Prozessende von Prozess B (Diagramm Teil 3).",
    ),
    "policy": AgentConfig(
        name="Policy-/Governance-Komponente",
        type=AgentType.POLICY,
        autonomy_level=None,
        oversight=OversightMode.DETERMINISTIC,
        model_class=ModelClass.NO_MODEL,
        processes=("A", "B"),
        can_write=False,
        description="Deterministisches RBAC/ABAC-Enforcement. Kein LLM.",
    ),
    "audit": AgentConfig(
        name="Audit-/Monitoring-Komponente",
        type=AgentType.AUDIT,
        autonomy_level=None,
        oversight=OversightMode.READ_ONLY,
        model_class=ModelClass.NO_MODEL,
        processes=("A", "B"),
        can_write=False,
        description="Manipulationsgeschuetzter, hash-verketteter Audit-Trail.",
    ),
}


def get_config(agent_id: str) -> AgentConfig:
    """Returns the configuration for an agent.

    An unknown agent is a programming error, not a runtime case: the policy
    must never check against a guessed default configuration.
    """
    try:
        return REGISTRY[agent_id]
    except KeyError:
        raise KeyError(
            f"Unknown agent {agent_id!r}. Known: {sorted(REGISTRY)}"
        ) from None
