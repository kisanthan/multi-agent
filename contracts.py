"""The contracts that cross a boundary in this system.

Three vocabularies leave one layer and are read by another. Until now each
existed only as a string literal repeated at both ends:

- **InterruptKind** -- what a paused case is waiting for. Written into the
  checkpoint by an approval node, read by `process_registry.for_interrupt()`,
  by `ui/cases/detail.py`, and by `demo.py`.
- **ApprovalDecision / ApprovalResponse** -- what a human sends back.
  Produced in the UI and the CLI, consumed by both approval nodes.
- **CaseOutcome** -- how a case ended. Written by whichever node completes
  it, read by `graph/cases.py::determine_status()` and the result texts.

`ApprovalRequest`/`ApprovalResponse` cross the *checkpoint*, not just a
module boundary: LangGraph persists them and hands them back hours later.
They are therefore declared as frozen dataclasses but travel as plain dicts
(`as_payload()`/`from_payload()`, `as_resume()`/`from_resume()`). A
dataclass instance handed to `interrupt()` round-trips through the
checkpointer, but LangGraph 1.2 already warns when deserializing an
unregistered type ("This will be blocked in a future version") -- so the
checkpoint file would end up carrying this module's import path as part of
its content. A dict has no class identity to break.

Imports nothing from this project on purpose: every layer may read this
module, so it may depend on none of them.

NOT here: graph node names and conditional-edge routing labels (e.g.
"buchung", "prozess_a", "hitl"). A node name is produced and consumed
entirely inside `graph/`; a routing label is returned in `graph/nodes/*`
and read exactly once, in `graph/workflow.py`, right where it is spent.
*Which* steps a process has is already stated by
`process_registry.ProcessStep`, *which agent* governs a step by
`agent_registry.py`. A fourth table of the same names here would be a fourth
source of truth, not a contract -- see `graph/workflow.py` and
`tests/test_flow.py` for how that vocabulary is instead pinned against the
compiled graph itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class InterruptKind(str, Enum):
    """What a paused case is waiting for.

    Persisted as the payload key `kind`; the join key of
    `process_registry.ProcessConfig.interrupt_kind`.
    """

    EXCEPTION_CASE = "klaerfall"                     # process A
    COST_CENTER_APPROVAL = "kostenstellen_freigabe"  # process B


class ApprovalDecision(str, Enum):
    """A human's verdict at a HITL point.

    Persisted twice: as the `decision` field of the resume payload, and
    (once accepted) as `state["approval_decision"]`.
    """

    APPROVED = "freigegeben"
    REJECTED = "verworfen"


class CaseOutcome(str, Enum):
    """How a case ended -- `state["outcome"]`, the last thing a node writes.

    Named `CaseOutcome`, not `Outcome`: `governance.policy.Outcome` already
    exists and means the verdict of a single policy check, imported by name
    in `agents/payment_confirmation/booking.py` and
    `agents/incoming_invoice/archiving.py`. The two are different
    vocabularies that happen to share a word in English; keeping the names
    apart is the point (see the three-vocabularies table in
    docs/architektur.md).

    This enum is the closed list of *values*; it deliberately does not say
    which of them count as a business success -- that is decided by each
    process (`process_registry.ProcessConfig.completion_outcome`), read by
    `graph/cases.py::successful_outcomes()`. Moving that decision here would
    replace "ask the processes" with "consult a constant", which is exactly
    the indirection `graph/cases.py` argues against in its own docstring.
    """

    BOOKED = "verbucht"                      # process A, success -- agents/payment_confirmation/booking.py
    ARCHIVED = "archiviert"                   # process B, success -- agents/incoming_invoice/archiving.py
    REJECTED = "verworfen"                    # either approval point, human said no
    ACCESS_DENIED = "zugriff_verweigert"       # reader, AD check denied (scenario 5)
    BOOKING_REFUSED = "abgelehnt"              # process A, Navision refused the booking
    ARCHIVING_FAILED = "archivierung_fehlgeschlagen"  # process B, ELO refused


@dataclass(frozen=True)
class ApprovalRequest:
    """What an approval node shows a human when it pauses the case.

    One class for both processes: they ask the same underlying question
    ("shall this case proceed?") and differ only in the evidence attached.
    Fields a process does not populate stay at their default and are
    omitted by `as_payload()`, so a process A request does not claim to
    carry an (empty) cost-center catalog, and vice versa.

    Every field is displayed somewhere: `reason`, `finding`, `escalation`,
    `line_items`, `number`, `catalog` by the Streamlit approval form
    (`ui/cases/detail.py`, `ui/cases/process_views/*`); the remainder by
    `demo.py`, which prints every non-empty field so the CLI approver sees
    the same evidence as the UI approver.
    """

    kind: InterruptKind
    filename: str | None = None
    reason: str | None = None
    # --- evidence, process A (Zahlungsbestätigung) ---
    finding: str | None = None
    number: str | None = None
    amount_eur: float | None = None
    expected_amount_eur: float | None = None
    escalation: str | None = None
    # --- evidence, process B (Eingangsrechnung) ---
    supplier: str | None = None
    line_items: tuple[str, ...] = ()
    reference: str | None = None
    unique: bool | None = None
    catalog: tuple[dict[str, str], ...] = ()

    def as_payload(self) -> dict[str, Any]:
        """The dict handed to `interrupt()` -- and stored in the checkpoint."""
        payload: dict[str, Any] = {"kind": self.kind.value}
        for name in ("filename", "reason", "finding", "number", "amount_eur",
                     "expected_amount_eur", "escalation", "supplier",
                     "reference", "unique"):
            value = getattr(self, name)
            if value is not None:
                payload[name] = value
        if self.line_items:
            payload["line_items"] = list(self.line_items)
        if self.catalog:
            payload["catalog"] = [dict(e) for e in self.catalog]
        return payload

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> ApprovalRequest:
        return cls(
            kind=InterruptKind(payload["kind"]),
            filename=payload.get("filename"),
            reason=payload.get("reason"),
            finding=payload.get("finding"),
            number=payload.get("number"),
            amount_eur=payload.get("amount_eur"),
            expected_amount_eur=payload.get("expected_amount_eur"),
            escalation=payload.get("escalation"),
            supplier=payload.get("supplier"),
            line_items=tuple(payload.get("line_items") or ()),
            reference=payload.get("reference"),
            unique=payload.get("unique"),
            catalog=tuple(payload.get("catalog") or ()),
        )


@dataclass(frozen=True)
class ApprovalResponse:
    """What the human sends back -- the `Command(resume=...)` payload.

    `cost_center_id` is the one field only process B fills, and the one
    place this contract was previously enforced only by convention: the UI
    supplies it conditionally (`ui/cases/process_views/incoming_invoice.py`
    contributes nothing when no catalog entry is selected) while the
    reading node used to index it unconditionally. Declaring it optional
    forces the reading node to say what it does when it is absent.
    """

    decision: ApprovalDecision
    approver: str
    number: str | None = None           # A: the approver may correct the number
    cost_center_id: str | None = None   # B: the approver's pick from the catalog

    @property
    def approved(self) -> bool:
        return self.decision is ApprovalDecision.APPROVED

    def as_resume(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"decision": self.decision.value,
                                   "approver": self.approver,
                                   "number": self.number}
        if self.cost_center_id is not None:
            payload["cost_center_id"] = self.cost_center_id
        return payload

    @classmethod
    def from_resume(cls, payload: dict[str, Any]) -> ApprovalResponse:
        """Reads a resume payload back.

        Tolerant in exactly one direction: an unrecognized `decision`
        counts as a rejection, never as an approval. A payload that cannot
        be understood must not book or archive anything -- the same
        default-deny rule as `governance/policy.py` rule 5.
        """
        try:
            decision = ApprovalDecision(payload.get("decision", ""))
        except ValueError:
            decision = ApprovalDecision.REJECTED
        return cls(decision=decision,
                   approver=payload.get("approver", ""),
                   number=payload.get("number"),
                   cost_center_id=payload.get("cost_center_id"))
