"""The processes of the functional concept as an effective configuration table.

Counterpart to `registry.py`: that module states *who* acts (agents, roles,
oversight); this one states *what* is being acted on* (process A payment
receipt, process B incoming invoice).

This module deliberately lives at the top level and not inside `ui/`. The
step sequence of a process is domain knowledge, not a presentation detail --
if it lived in the UI, a third process would require touching the UI.
So the rule holds: **one more process = one entry here plus the nodes in
the graph.** Page, navigation, list, stepper, and filter follow from that.

Pure configuration with no behavior, no LLM dependency, and no Streamlit
import.
"""

from __future__ import annotations

from dataclasses import dataclass

from agents.schemas import DocumentType


@dataclass(frozen=True)
class ProcessStep:
    """A step in the flow.

    `node` is the node name from `graph/workflow.py`. It is the key the UI
    uses to look up in the run log whether the step has already happened --
    the link between the flow model and the display.
    """

    node: str
    title: str
    agent_id: str | None


# The shared intake stretch of both processes (functional concept: shared
# reader, shared classification agent, shared master data).
SHARED_STEPS: tuple[ProcessStep, ...] = (
    ProcessStep("reader", "Beleg einlesen", "reader"),
    ProcessStep("klassifikation", "Beleg auswerten", "klassifikation"),
)


@dataclass(frozen=True)
class ProcessConfig:
    key: str                 # 'A' | 'B' -- the thesis's short designation
    route: str                # URL path; single-level, Streamlit disallows '/'
    name: str                 # process name ('Zahlungseingang')
    document_kind: str         # document name ('Zahlungsbestätigung')
    icon: str
    description: str
    document_type: DocumentType   # decides a case's process assignment
    own_steps: tuple[ProcessStep, ...]
    list_columns: tuple[str, ...]     # state fields for the case list
    detail_fields: tuple[str, ...]    # state fields for the detail-page header
    target_system: str
    process_end: str
    completion_outcome: str      # `outcome` value of a successful run

    @property
    def steps(self) -> tuple[ProcessStep, ...]:
        return (*SHARED_STEPS, *self.own_steps)


PROCESSES: dict[str, ProcessConfig] = {
    "A": ProcessConfig(
        key="A",
        route="zahlungsbestaetigung",
        name="Zahlungsbestätigung",
        document_kind="Zahlungsbestätigung",
        icon="💶",
        description="Eine Zahlungsbestätigung wird eingelesen und mit den "
        "offenen Rechnungen abgeglichen. Nach der Bestätigung durch eine "
        "Person wird die Zahlung verbucht: die Rechnung gilt als bezahlt.",
        document_type=DocumentType.PAYMENT_CONFIRMATION,
        own_steps=(
            ProcessStep("abgleich", "Mit Rechnungsdaten abgleichen", "abgleich"),
            ProcessStep("klaerfall", "Bestätigung durch eine Person", "buchung"),
            ProcessStep("buchung", "Zahlung verbuchen", "buchung"),
        ),
        list_columns=("number", "amount_eur"),
        detail_fields=("number", "amount_eur", "expected_amount_eur", "finding"),
        target_system="Buchhaltung (Navision)",
        process_end="Die Rechnung ist als bezahlt verbucht",
        completion_outcome="verbucht",
    ),
    "B": ProcessConfig(
        key="B",
        route="eingangsrechnung",
        name="Eingangsrechnung",
        document_kind="Eingangsrechnung",
        icon="🧾",
        description="Eine Eingangsrechnung wird eingelesen und anhand der "
        "Kostenstelle auf dem Beleg zugeordnet. Anschließend wird sie "
        "revisionssicher archiviert. Eine Zahlung wird hier nicht gebucht.",
        document_type=DocumentType.INCOMING_INVOICE,
        own_steps=(
            ProcessStep("kostenstelle", "Kostenstelle zuordnen", "kostenstelle"),
            ProcessStep("freigabe", "Bestätigung durch eine Person", "kostenstelle"),
            ProcessStep("elo", "Rechnung archivieren", "elo"),
        ),
        list_columns=("supplier", "amount_eur"),
        detail_fields=("supplier", "amount_eur", "cost_center_reference",
                       "cost_center_id"),
        target_system="Archiv (ELO)",
        process_end="Die Rechnung ist revisionssicher archiviert",
        completion_outcome="archiviert",
    ),
}


def get_config(key: str) -> ProcessConfig:
    """Configuration of a process. Unknown = programming error."""
    try:
        return PROCESSES[key]
    except KeyError:
        raise KeyError(
            f"Unknown process {key!r}. Known: {sorted(PROCESSES)}"
        ) from None


def for_document_type(document_type: str | None) -> ProcessConfig | None:
    """Maps a document type to its process.

    `None` as long as the type is not yet known (the classification agent
    has not run yet) or is unknown -- the case then belongs to no process
    yet, but to the shared intake stretch.
    """
    if not document_type:
        return None
    return next((p for p in PROCESSES.values() if p.document_type.value == document_type), None)


def for_route(route: str) -> ProcessConfig | None:
    return next((p for p in PROCESSES.values() if p.route == route), None)


def all_processes() -> list[ProcessConfig]:
    """All processes in stable order (for navigation and filters)."""
    return [PROCESSES[k] for k in sorted(PROCESSES)]


def document_kinds() -> list[str]:
    """The document kinds the system processes.

    Derived from the registry rather than a fixed list in prose: when a
    process is added, the UI names it on its own.
    """
    return [p.document_kind for p in all_processes()]


def document_kind_for(key: str | None) -> str | None:
    """The document kind of a process ('Zahlungsbestaetigung')."""
    return get_config(key).document_kind if key else None


def successful_outcomes() -> frozenset[str]:
    """All `outcome` values that mean a business-successful completion."""
    return frozenset(p.completion_outcome for p in PROCESSES.values())


def step_title(node: str) -> str:
    """Human-readable label of a graph node.

    The run log records technical node names (`reader`, `klassifikation`).
    They have no place on the screen -- there, what the step means in
    business terms is shown instead.
    """
    for step in (*SHARED_STEPS,
                 *(s for p in PROCESSES.values() for s in p.own_steps)):
        if step.node == node:
            return step.title
    return node.replace("_", " ").capitalize()
