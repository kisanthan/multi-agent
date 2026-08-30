"""Cost-center agent (Shared Domain, level 2 = proposal), process B.

Assigns an incoming invoice to a cost center. Per Thesis §7.4 this is an
**exact referential lookup** against structured master data: the
cost-center reference printed on the document is matched against the
catalog -- no semantic matching, no language model.

The same reasoning therefore applies to this agent as to the reconciliation
agent (cf. agents/reconciliation.py, docs/mapping.md I1): the role and
autonomy level remain valid, but the actual assignment is a deterministic
database lookup, not a model call. Extracting the reference from the
document itself is done by the incoming-invoice extraction agent.

"Assignment unique?" (diagram part 3) means here: the extracted reference
resolves to exactly one cost center. If the reference is missing or
unknown, the assignment is not unique and goes to a human as an exception
case.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from enum import Enum

from governance.audit import NO_REFERENCE, CaseReference, Decision, log_entry

AGENT_ID = "kostenstelle"


class Finding(str, Enum):
    UNIQUE_MATCH = "eindeutig"              # reference resolves to exactly one cost center
    MISSING_REFERENCE = "keine_referenz"    # document names no reference
    UNKNOWN_REFERENCE = "unbekannte_referenz"  # reference not in the catalog


@dataclass(frozen=True)
class CostCenterAssignment:
    finding: Finding
    cost_center_id: str | None
    name: str | None
    reference: str | None
    reason: str

    @property
    def unique(self) -> bool:
        return self.finding is Finding.UNIQUE_MATCH


def normalize(reference: str) -> str:
    """Strips extra characters from the markdown formatting.

    As with the reconciliation agent, this is a formatting question, not a
    business one: the parser occasionally returns the reference as
    '**KTR-ITINFRA**'.
    """
    return re.sub(r"[^A-Z0-9-]", "", reference.upper())


def assign(con: sqlite3.Connection, *, cost_center_reference: str | None, actor: str,
           line_items: list[str] | None = None,
           reference: CaseReference = NO_REFERENCE) -> CostCenterAssignment:
    """Looks up the cost-center reference exactly in the catalog. Read access only."""
    if not cost_center_reference:
        result = CostCenterAssignment(
            Finding.MISSING_REFERENCE, None, None, None,
            "Der Beleg nennt keine Kostenstellenreferenz -- keine eindeutige "
            "Zuordnung moeglich.",
        )
        _log(con, actor, result, reference)
        return result

    norm = normalize(cost_center_reference)
    row = con.execute(
        "SELECT id, name FROM cost_centers WHERE reference = ?", (norm,)
    ).fetchone()

    if row is None:
        result = CostCenterAssignment(
            Finding.UNKNOWN_REFERENCE, None, None, norm,
            f"Referenz {norm} ist im Kostenstellenkatalog nicht vorhanden.",
        )
    else:
        result = CostCenterAssignment(
            Finding.UNIQUE_MATCH, row[0], row[1], norm,
            f"Referenz {norm} loest eindeutig auf {row[0]} ({row[1]}) auf.",
        )

    _log(con, actor, result, reference)
    return result


def catalog(con: sqlite3.Connection) -> list[tuple[str, str, str]]:
    """Returns the catalog (id, name, reference) for the exception-case display."""
    return [
        (r[0], r[1], r[2])
        for r in con.execute(
            "SELECT id, name, reference FROM cost_centers ORDER BY id"
        ).fetchall()
    ]


def exists(con: sqlite3.Connection, cost_center_id: str | None) -> bool:
    """Checks whether a (human-selected) cost center is in the catalog."""
    if not cost_center_id:
        return False
    return con.execute("SELECT 1 FROM cost_centers WHERE id = ?",
                       (cost_center_id,)).fetchone() is not None


def _log(con: sqlite3.Connection, actor: str,
         r: CostCenterAssignment,
         reference: CaseReference = NO_REFERENCE) -> None:
    log_entry(
        con, actor=actor, agent=AGENT_ID, action="kostenstelle_zuordnen",
        decision=Decision.INFO, reason=r.reason,
        payload={"finding": r.finding.value, "cost_center_id": r.cost_center_id,
                 "reference": r.reference},
        reference=reference, outcome=r.finding.value,
    )
    con.commit()
