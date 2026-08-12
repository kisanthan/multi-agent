"""Case overview: derives the case list from the checkpoint.

LangGraph keeps no list of running threads -- the checkpointer knows them,
but does not expose them as an overview. This module reads the thread IDs
from the checkpoint database and determines the business status per
thread.

Deliberately no separate case table in `masterdata.db`: a case's state
lives in the checkpoint, and that is the thesis's claim (the case survives
the process and waits there for the human). A second table would be a
second source of truth that could drift.

`determine_status()` and `process_of()` are pure functions: they know
neither LangGraph nor Streamlit and are therefore testable without either.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from langgraph.graph.state import CompiledStateGraph

import process_registry
from contracts import CaseOutcome


class Status(str, Enum):
    """Business status of a case -- not the technical graph state."""

    RUNNING = "laeuft"
    WAITING_FOR_APPROVAL = "wartet_auf_freigabe"
    COMPLETED = "abgeschlossen"
    REJECTED = "verworfen"
    DENIED = "abgewiesen"          # AD check denied (Least Privilege)
    FAILED = "fehlgeschlagen"      # target system rejected it

    @property
    def label(self) -> str:
        """What appears on screen.

        Deliberately without jargon: the internal name
        (`wartet_auf_freigabe`) belongs in code and the audit trail; on
        screen, a case worker sees what they need to know about it.
        """
        return {
            Status.RUNNING: "In Bearbeitung",
            Status.WAITING_FOR_APPROVAL: "Wartet auf Bestätigung",
            Status.COMPLETED: "Abgeschlossen",
            Status.REJECTED: "Abgelehnt",
            Status.DENIED: "Nicht berechtigt",
            Status.FAILED: "Fehlgeschlagen",
        }[self]

    @property
    def is_open(self) -> bool:
        return self in (Status.RUNNING, Status.WAITING_FOR_APPROVAL)


def determine_status(values: dict, *, waiting: bool) -> Status:
    """Derives the business status from the case state.

    `waiting` comes from outside (from `StateSnapshot.interrupts`), so the
    function stays pure and can be called in tests without a graph.

    A waiting case always counts as waiting, even if the state still holds
    an old `outcome` value: the interrupt is the stronger statement -- that
    is where it is currently hanging, that is where a human must go.
    """
    if waiting:
        return Status.WAITING_FOR_APPROVAL

    if not values.get("completed"):
        return Status.RUNNING

    outcome = values.get("outcome")
    # What counts as success is stated by the respective process
    # (process_registry), not a list here -- otherwise a third process
    # would have to extend it.
    if outcome in process_registry.successful_outcomes():
        return Status.COMPLETED
    if outcome == CaseOutcome.REJECTED.value:
        return Status.REJECTED
    if outcome == CaseOutcome.ACCESS_DENIED.value:
        return Status.DENIED
    # 'abgelehnt', 'archivierung_fehlgeschlagen', and anything unexpected:
    # the case has ended, but not successfully. No silent success.
    return Status.FAILED


def process_of(values: dict) -> str | None:
    """Process key of the case, or None.

    The document type only comes into existence in the classification
    agent; before that, the case is on the shared intake stretch and does
    not yet belong to any process.
    """
    config = process_registry.for_document_type(values.get("document_type"))
    return config.key if config else None


@dataclass(frozen=True)
class CaseOverview:
    """One row of the case list."""

    thread_id: str
    filename: str
    actor: str
    status: Status
    process: str | None
    started_at: str
    outcome: str | None
    approved_by: str | None


def thread_ids(checkpoint_path: Path | str) -> list[str]:
    """Reads the thread IDs from the checkpoint database.

    If the file or table is missing (no run has happened yet), that is not
    an error, but an empty list.
    """
    path = Path(checkpoint_path)
    if not path.is_file():
        return []

    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute(
            "SELECT DISTINCT thread_id FROM checkpoints"
        ).fetchall()]
    except sqlite3.OperationalError:
        return []
    finally:
        con.close()


def overview(app: CompiledStateGraph, checkpoint_path: Path | str) -> list[CaseOverview]:
    """All known cases, newest first.

    Queries the checkpoint per thread. That is O(n) in the number of cases
    and reasonable for a prototype with a few dozen runs; a production
    system would have an index here.
    """
    rows = []
    for thread_id in thread_ids(checkpoint_path):
        snapshot = app.get_state({"configurable": {"thread_id": thread_id}})
        values = snapshot.values or {}
        if not values:
            continue  # created but never run thread

        rows.append(CaseOverview(
            thread_id=thread_id,
            filename=values.get("filename") or Path(values.get("path", "")).name or thread_id,
            actor=values.get("actor", "-"),
            status=determine_status(values, waiting=bool(snapshot.interrupts)),
            process=process_of(values),
            started_at=values.get("started_at", ""),
            outcome=values.get("outcome"),
            approved_by=values.get("approved_by"),
        ))

    return sorted(rows, key=lambda z: z.started_at, reverse=True)
