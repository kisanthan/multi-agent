"""Effect of a completed case in the target system.

The actual evidence of a run is not the log, but the changed state in the
target system: the invoice sits in Navision as 'bezahlt', the document sits
in ELO under an archive ID. CLI and UI must show the same evidence -- that
is why the query lives here and not in `demo.py` or in the UI.

Pure read query: this module changes nothing and calls no model.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass


@dataclass(frozen=True)
class Effect:
    """What the case left behind in the target system.

    All fields are optional, because a case touches only one of the target
    systems depending on process and outcome -- or none (scenario 5: the AD
    check denies access before any access happens).
    """

    navision_number: str | None = None
    navision_status: str | None = None
    navision_paid_at: str | None = None
    elo_archive_id: str | None = None
    elo_filed_at: str | None = None

    @property
    def has_effect(self) -> bool:
        return bool(self.navision_status or self.elo_archive_id)


def read_effect(con: sqlite3.Connection, state: dict) -> Effect:
    """Reads the target-system state for a case.

    Deliberately tolerant: a number that is not in the master data
    (scenario 'unknown number') is a regular business case and must not
    raise an error here -- it simply returns no Navision status.
    """
    number = state.get("number")
    navision_status = navision_paid_at = None
    if number:
        row = con.execute(
            "SELECT status, paid_at FROM invoices WHERE number = ?", (number,)
        ).fetchone()
        if row:
            navision_status, navision_paid_at = row

    archive_id = state.get("archive_id")
    filed_at = None
    if archive_id:
        row = con.execute(
            "SELECT filed_at FROM archive WHERE archive_id = ?", (archive_id,)
        ).fetchone()
        if row:
            filed_at = row[0]

    return Effect(
        navision_number=number if navision_status else None,
        navision_status=navision_status,
        navision_paid_at=navision_paid_at,
        elo_archive_id=archive_id,
        elo_filed_at=filed_at,
    )
