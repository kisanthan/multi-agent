"""Deriving process progress from the run log.

The stepper is where a viewer reads off what happened -- a wrongly marked
step claims something that did not happen. The derivation is therefore kept
separate from the rendering and returns pure data.

*Which* steps exist is not stated here, but in `process_registry`. This
module only answers: what state is each of them in?
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import process_registry
from graph.cases import Status
from process_registry import SHARED_STEPS, ProcessStep


class StepStatus(str, Enum):
    DONE = "erledigt"
    ACTIVE = "aktiv"
    OPEN = "offen"
    SKIPPED = "uebersprungen"
    FAILED = "gescheitert"


@dataclass(frozen=True)
class Step:
    """A process step with its state in a concrete case."""

    node: str
    title: str
    agent_id: str | None
    status: StepStatus = StepStatus.OPEN
    hint: str = ""


# Maps the kind of an interrupt to the step it hangs on.
WAIT_POINTS = {"klaerfall": "klaerfall", "kostenstellen_freigabe": "freigabe"}


def _raw_steps(process: str | None) -> tuple[ProcessStep, ...]:
    """If the process is not yet known, only the shared stretch is known."""
    if process is None:
        return SHARED_STEPS
    return process_registry.get_config(process).steps


def _step_status(node: str, counts: dict[str, int], *, waiting_at: str | None,
                 status: Status | None, final_node: str) -> tuple[StepStatus, str]:
    """Rule per node. Deliberately one rule per line instead of a heuristic.

    Two cases do not behave the way mere presence in the log would suggest,
    and get their own rule:

    - The **booking node runs twice**: the first pass only reports "approval
      required" and sends the case into the exception case
      (graph/workflow.py::node_booking). A log entry alone is therefore not
      a booking -- what matters is the overall outcome.
    - The **approval in process B is skipped** when the document reference
      resolves uniquely. That is the normal case (human-on-the-loop), not a
      skipped step.
    """
    if node == waiting_at:
        return StepStatus.ACTIVE, "Wartet auf Entscheidung"

    ran = counts.get(node, 0)
    done = status is Status.COMPLETED

    if node == "reader":
        if status is Status.DENIED:
            return StepStatus.FAILED, "Zugriff verweigert"
        return (StepStatus.DONE, "") if ran else (StepStatus.OPEN, "")

    # The last step carries the overall outcome: it counts as done exactly
    # when the case completed successfully.
    if node == final_node:
        if done:
            return StepStatus.DONE, ""
        if status is Status.FAILED and ran:
            return StepStatus.FAILED, "Zielsystem hat abgelehnt"
        return StepStatus.OPEN, ""

    if node == "freigabe" and not ran:
        if counts.get(final_node) or done:
            return (StepStatus.SKIPPED,
                    "Nicht nötig – die Kostenstelle war eindeutig")
        return StepStatus.OPEN, ""

    if node == "klaerfall" and not ran and done:
        return StepStatus.SKIPPED, ""

    return (StepStatus.DONE, "") if ran else (StepStatus.OPEN, "")


def steps_for(
    process: str | None,
    log: list[dict],
    *,
    waiting_on: str | None = None,
    status: Status | None = None,
) -> list[Step]:
    """State of every process step.

    `waiting_on` is the kind of the active interrupt, `status` the overall
    business status of the case.
    """
    counts: dict[str, int] = {}
    for entry in log:
        node = entry.get("node", "")
        counts[node] = counts.get(node, 0) + 1

    raw_steps = _raw_steps(process)
    waiting_at = WAIT_POINTS.get(waiting_on or "")
    final_node = raw_steps[-1].node if process else ""

    return [
        Step(s.node, s.title, s.agent_id,
             *_step_status(s.node, counts, waiting_at=waiting_at,
                           status=status, final_node=final_node))
        for s in raw_steps
    ]
