"""State model of the workflow.

LangGraph carries this state through every node and persists it in the
checkpointer. That is exactly what makes the HITL interruption possible:
the case pauses at an approval point, the state survives the process, and a
human resumes it hours later.

Split into one `TypedDict` per process plus a shared one, mirroring
`agents/` and `graph/nodes/`: a field's home tells you which process's node
writes it. All four classes live in this one file on purpose -- with
`from __future__ import annotations`, LangGraph resolves every annotation
as a string against this module's globals, so a base class defined
elsewhere would fail to resolve.
"""

from __future__ import annotations

from typing import Any, TypedDict


class SharedFields(TypedDict, total=False):
    """Fields written by the shared intake stretch (reader, classification)
    or by either process's HITL/outcome handling."""

    # --- Intake ---
    path: str
    actor: str              # UPN of the submitter
    filename: str
    # Thread ID of the run, kept redundantly in the state: the agents use it
    # to write their audit entries without needing to know the checkpointer.
    case_id: str
    # The uploaded file this case originated from. A file can be processed
    # more than once -- the relationship is 1:n.
    upload_id: str | None
    # ISO timestamp of the start. Lives in the state and not in the
    # checkpoint metadata, because LangGraph does not reliably expose the
    # start time -- but the case list needs it for sorting.
    started_at: str
    configuration_revision: int
    # Non-secret provider/model snapshot. Credentials are resolved centrally
    # and are never persisted in a case checkpoint.
    model_profiles: dict[str, dict[str, str]]

    # --- Reader ---
    markdown: str
    document_hash: str

    # --- Classification ---
    document_type: str     # 'zahlungsbestaetigung' | 'eingangsrechnung' | 'unbekannt'
    number: str | None
    amount_eur: float | None
    supplier: str | None
    line_items: list[str]
    # Extracted by the incoming-invoice extraction agent; meaningful only
    # for process B.
    cost_center_reference: str | None
    escalation: str | None

    # --- HITL ---
    # Written by either process's approval node (klaerfall for A,
    # freigabe_kostenstelle for B) -- same shape, same question asked of a
    # human, hence shared rather than duplicated per process.
    approval_id: str | None
    candidate_version: int
    command_id: str | None
    approved_by: str | None
    approval_decision: str        # 'freigegeben' | 'verworfen'
    exception_case: bool
    exception_reason: str
    # Which oversight rule stopped the case: the agent's standing
    # human-in-the-loop mode, or an escalation out of human-on-the-loop.
    # Set by the node that stops it, read by the approval dialog; see
    # contracts.ApprovalTrigger.
    approval_trigger: str

    # --- Outcome ---
    completed: bool
    outcome: str
    error: str | None

    # --- Traceability ---
    log: list[dict[str, Any]]


class PaymentConfirmationFields(TypedDict, total=False):
    """Fields written only by process A's nodes (agents/payment_confirmation)."""

    finding: str
    expected_amount_eur: float | None


class IncomingInvoiceFields(TypedDict, total=False):
    """Fields written only by process B's nodes (agents/incoming_invoice)."""

    cost_center_id: str | None
    cost_center_reason: str
    cost_center_unique: bool
    archive_id: str | None


class Case(SharedFields, PaymentConfirmationFields, IncomingInvoiceFields, total=False):
    """A single document's pass through process A or B."""
