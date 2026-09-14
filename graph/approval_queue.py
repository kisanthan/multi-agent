"""Personal projection of waiting cases that an actor may decide."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import process_registry
from governance.policy import check_approval
from graph.cases import CaseOverview, Status, overview


@dataclass(frozen=True)
class ApprovalTask:
    """A waiting case plus the approval point governing its decision."""

    case: CaseOverview
    request: dict
    agent_id: str


def available_from_cases(
    app,
    con: sqlite3.Connection,
    *,
    actor: str,
    cases: Iterable[CaseOverview],
) -> list[ApprovalTask]:
    """Return only waiting cases the actor may approve right now.

    This is deliberately policy-backed instead of filtering only by status:
    approval membership and separation of duties must match the decision
    form and the server-side resume guard.
    """
    tasks: list[ApprovalTask] = []
    for case in cases:
        if case.status is not Status.WAITING_FOR_APPROVAL:
            continue

        snapshot = app.get_state({"configurable": {"thread_id": case.thread_id}})
        if not snapshot.interrupts:
            continue
        request = snapshot.interrupts[0].value
        if not isinstance(request, dict):
            continue

        process = process_registry.for_interrupt(request.get("kind"))
        agent_id = process.approval_agent_id if process else None
        if not agent_id:
            continue

        ruling = check_approval(
            con,
            actor=actor,
            agent_id=agent_id,
            submitter=case.actor,
        )
        if ruling.allowed:
            tasks.append(ApprovalTask(case=case, request=request, agent_id=agent_id))

    return tasks


def available_for(
    app,
    checkpoint_path: Path | str,
    con: sqlite3.Connection,
    *,
    actor: str,
) -> list[ApprovalTask]:
    """Build the current personal queue from the checkpoint projection."""
    return available_from_cases(
        app,
        con,
        actor=actor,
        cases=overview(app, checkpoint_path),
    )
