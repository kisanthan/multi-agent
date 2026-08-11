"""Filtering and sorting case lists.

Pure functions over `CaseOverview` rows: no Streamlit, no database. The
filter bar in the UI only collects the inputs and calls `apply()` -- that
way the behavior is testable without a running app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from graph.cases import Status, CaseOverview

PAGE_SIZE = 25


@dataclass(frozen=True)
class Filter:
    """The user's selection. Empty fields mean 'do not restrict'."""

    search: str = ""
    processes: frozenset[str] = field(default_factory=frozenset)
    statuses: frozenset[Status] = field(default_factory=frozenset)
    date_from: str = ""      # ISO date, inclusive
    date_to: str = ""        # ISO date, inclusive
    newest_first: bool = True

    @property
    def is_empty(self) -> bool:
        return not (self.search or self.processes or self.statuses or self.date_from or self.date_to)


def _matches_search(row: CaseOverview, term: str) -> bool:
    if not term:
        return True
    haystack = " ".join([
        row.filename, row.actor, row.status.label,
        row.outcome or "", row.approved_by or "",
    ]).lower()
    return term.lower().strip() in haystack


def _matches_date_range(row: CaseOverview, date_from: str, date_to: str) -> bool:
    """Compares at day granularity.

    ISO timestamps sort lexicographically, so a string comparison of the
    first ten characters is enough. Cases without a start time (runs from
    older states) are never excluded by a date-range filter -- otherwise
    they would vanish inexplicably.
    """
    day = (row.started_at or "")[:10]
    if not day:
        return True
    if date_from and day < date_from:
        return False
    if date_to and day > date_to:
        return False
    return True


def apply(rows: list[CaseOverview], f: Filter) -> list[CaseOverview]:
    """Filters and sorts. Does not change the input list."""
    matches = [
        z for z in rows
        if _matches_search(z, f.search)
        and (not f.processes or z.process in f.processes)
        and (not f.statuses or z.status in f.statuses)
        and _matches_date_range(z, f.date_from, f.date_to)
    ]
    return sorted(matches, key=lambda z: z.started_at or "",
                  reverse=f.newest_first)


def open_cases(rows: list[CaseOverview]) -> list[CaseOverview]:
    """Active cases -- ones needing approval first, since they need someone."""
    active = [z for z in rows if z.status.is_open]
    return sorted(active, key=lambda z: z.status is not Status.WAITING_FOR_APPROVAL)


def closed_cases(rows: list[CaseOverview]) -> list[CaseOverview]:
    return [z for z in rows if not z.status.is_open]


def for_process(rows: list[CaseOverview],
                key: str) -> list[CaseOverview]:
    return [z for z in rows if z.process == key]


def counts(rows: list[CaseOverview]) -> dict[str, int]:
    """Counters for a page's metrics row."""
    return {
        "pending": sum(1 for z in rows if z.status is Status.WAITING_FOR_APPROVAL),
        "running": sum(1 for z in rows if z.status is Status.RUNNING),
        "completed": sum(1 for z in rows if z.status is Status.COMPLETED),
        "failed": sum(
            1 for z in rows
            if z.status in (Status.FAILED, Status.DENIED)
        ),
    }
