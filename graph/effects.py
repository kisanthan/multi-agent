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
    """Only a receipt belonging to this case proves its own target effect."""
    import json
    if not state.get("case_id") or not state.get("command_id"):
        return Effect()
    exists = con.execute("SELECT 1 FROM sqlite_master WHERE name='execution_commands'").fetchone()
    if not exists:
        return Effect()
    row = con.execute("SELECT receipt FROM execution_commands WHERE command_id=? AND case_id=? AND status='succeeded'",
                      (state["command_id"], state["case_id"])).fetchone()
    if not row:
        return Effect()
    receipt = json.loads(row[0])
    return Effect(navision_number=receipt.get("number"), navision_status=receipt.get("after"),
                  navision_paid_at=receipt.get("paid_at"), elo_archive_id=receipt.get("archive_id"), elo_filed_at=receipt.get("filed_at"))
