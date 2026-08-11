"""Audit/monitoring component: hash-chained, append-only audit trail.

Satisfies the thesis's "traceability" evaluation criterion. Every entry
hashes its predecessor; `verify_chain()` therefore detects any subsequent
change, any deletion, and any insertion -- not just the change itself, but
also the point from which the chain breaks.

No LLM. Pure Python logic (chapter 3.4 / section 7 of the functional
concept).
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum

GENESIS_HASH = "0" * 64


class Decision(str, Enum):
    ALLOWED = "erlaubt"
    DENIED = "verweigert"
    INFO = "info"


@dataclass(frozen=True)
class CaseReference:
    """Where an entry comes from: which case, which source.

    Its own object rather than two parameters, because the reference is
    passed through the entire agent chain -- one argument per function
    instead of two.

    A case is a single run, not a document: the same file can be processed
    more than once. So the source alone is not enough to find the entries
    of one run.
    """

    case_id: str | None = None
    source: str | None = None


# For entries that belong to no case (system events, tests).
NO_REFERENCE = CaseReference()


@dataclass(frozen=True)
class AuditEntry:
    id: int
    ts: str
    actor: str
    agent: str | None
    action: str
    decision: Decision
    reason: str
    case_id: str | None
    source: str | None
    outcome: str | None
    payload_hash: str
    prev_hash: str
    hash: str


def _canonical(payload: dict) -> str:
    """Serializes deterministically.

    sort_keys is not cosmetic here: without a stable key order, the hash
    would depend on the dict's insertion order and the chain would not be
    reproducibly verifiable.
    """
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _payload_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def _entry_hash(ts: str, actor: str, agent: str | None, action: str,
                decision: str, reason: str, case_id: str | None,
                source: str | None, outcome: str | None,
                payload_hash: str, prev_hash: str) -> str:
    """Hashes the complete entry content, including the predecessor hash.

    All content fields go into it -- if only payload_hash were chained,
    actor or decision could be changed unnoticed. This explicitly also
    holds for case reference, source, and outcome: if they were excluded,
    an entry could be attributed to a different case without breaking the
    chain.
    """
    material = "|".join([
        ts, actor, agent or "", action, decision, reason,
        case_id or "", source or "", outcome or "",
        payload_hash, prev_hash,
    ])
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def last_hash(con: sqlite3.Connection) -> str:
    row = con.execute("SELECT hash FROM audit ORDER BY id DESC LIMIT 1").fetchone()
    return row[0] if row else GENESIS_HASH


def log_entry(con: sqlite3.Connection, *, actor: str, action: str,
              decision: Decision, reason: str,
              agent: str | None = None, payload: dict | None = None,
              reference: CaseReference = NO_REFERENCE,
              outcome: str | None = None) -> AuditEntry:
    """Appends an entry to the chain.

    Deliberately without `commit()`: the caller decides the transaction
    boundary, so that the booking and the audit entry become valid together
    or roll back together.
    """
    payload = payload or {}
    ts = datetime.now(timezone.utc).isoformat()
    p_hash = _payload_hash(payload)
    prev = last_hash(con)
    h = _entry_hash(ts, actor, agent, action, decision.value, reason,
                    reference.case_id, reference.source, outcome, p_hash, prev)

    cur = con.execute(
        "INSERT INTO audit (ts, actor, agent, action, decision, reason,"
        " case_id, source, outcome, payload_hash, prev_hash, hash)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (ts, actor, agent, action, decision.value, reason,
         reference.case_id, reference.source, outcome, p_hash, prev, h),
    )
    return AuditEntry(
        id=cur.lastrowid, ts=ts, actor=actor, agent=agent, action=action,
        decision=decision, reason=reason,
        case_id=reference.case_id, source=reference.source,
        outcome=outcome, payload_hash=p_hash, prev_hash=prev, hash=h,
    )


@dataclass(frozen=True)
class VerificationResult:
    valid: bool
    checked: int
    broken_at: int | None = None
    reason: str | None = None

    def __str__(self) -> str:
        if self.valid:
            return f"Audit-Kette intakt ({self.checked} Eintraege)"
        return f"Audit-Kette gebrochen bei Eintrag {self.broken_at}: {self.reason}"


def verify_chain(con: sqlite3.Connection) -> VerificationResult:
    """Verifies the hash chain in full.

    The thesis's tamper-evidence proof. Two checks per entry:
    1. Does prev_hash point to the actual predecessor?  (delete/insert)
    2. Does the stored hash match the content?           (change)
    """
    rows = con.execute(
        "SELECT id, ts, actor, agent, action, decision, reason,"
        " case_id, source, outcome, payload_hash, prev_hash, hash"
        " FROM audit ORDER BY id"
    ).fetchall()

    expected_prev = GENESIS_HASH
    for i, r in enumerate(rows):
        (eid, ts, actor, agent, action, decision, reason,
         case_id, source, outcome, p_hash, prev_hash, h) = r

        if prev_hash != expected_prev:
            return VerificationResult(
                False, i, eid,
                f"prev_hash verweist nicht auf den Vorgaenger "
                f"(erwartet {expected_prev[:12]}..., gefunden {prev_hash[:12]}...). "
                "Deutet auf einen geloeschten oder eingefuegten Eintrag hin.",
            )

        new = _entry_hash(ts, actor, agent, action, decision, reason,
                          case_id, source, outcome, p_hash, prev_hash)
        if new != h:
            return VerificationResult(
                False, i, eid,
                f"Inhalt passt nicht zum gespeicherten Hash "
                f"(erwartet {new[:12]}..., gefunden {h[:12]}...). "
                "Deutet auf eine nachtraegliche Aenderung hin.",
            )
        expected_prev = h

    return VerificationResult(True, len(rows))


def read_all(con: sqlite3.Connection, limit: int | None = None, *,
             case_id: str | None = None) -> list[AuditEntry]:
    """Read-only access to the trail (the audit component's oversight mode).

    `case_id` restricts to a single run. Careful: a filtered view is not
    proof of integrity -- `verify_chain()` always checks the complete
    chain.
    """
    sql = ("SELECT id, ts, actor, agent, action, decision, reason,"
           " case_id, source, outcome, payload_hash, prev_hash, hash"
           " FROM audit")
    params: tuple = ()
    if case_id:
        sql += " WHERE case_id = ?"
        params = (case_id,)
    sql += " ORDER BY id"
    if limit:
        sql += f" LIMIT {int(limit)}"

    return [
        AuditEntry(
            id=r[0], ts=r[1], actor=r[2], agent=r[3], action=r[4],
            decision=Decision(r[5]), reason=r[6],
            case_id=r[7], source=r[8], outcome=r[9],
            payload_hash=r[10], prev_hash=r[11], hash=r[12],
        )
        for r in con.execute(sql, params).fetchall()
    ]


def cases_in_trail(con: sqlite3.Connection) -> list[str]:
    """All case IDs that have entries (for the filter)."""
    return [r[0] for r in con.execute(
        "SELECT DISTINCT case_id FROM audit WHERE case_id IS NOT NULL"
        " ORDER BY case_id"
    ).fetchall()]
