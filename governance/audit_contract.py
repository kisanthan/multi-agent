"""Versioned seven-category events, linked to the untouched legacy chain."""
import hashlib
import json
import sqlite3
from dataclasses import dataclass

CATEGORIES = ("requester", "component", "source", "tool", "policy", "approval", "result")


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def payload_hash(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def append(con: sqlite3.Connection, event: dict, legacy_event: int, legacy_previous: str) -> None:
    if any(name not in event or event[name] is None for name in CATEGORIES):
        raise ValueError("Seven audit categories are mandatory.")
    approval = event["approval"]
    if set(("status", "person", "time", "reference")) - approval.keys():
        raise ValueError("Structured approval event is mandatory.")
    if not approval["status"]:
        raise ValueError("Approval status must be explicit.")
    if approval["status"] in {"approved", "consumed", "rejected", "revoked"}:
        if not all(approval[k] is not None for k in ("person", "time", "reference")):
            raise ValueError("Approval evidence is incomplete.")
    row = con.execute("SELECT hash FROM audit_v2 ORDER BY id DESC LIMIT 1").fetchone()
    prev = row[0] if row else "legacy:" + legacy_previous
    body = canonical(event)
    digest = hashlib.sha256((prev + "\n" + body).encode()).hexdigest()
    con.execute("INSERT INTO audit_v2(event,prev_hash,hash,legacy_event) VALUES(?,?,?,?)",
                (body, prev, digest, legacy_event))


@dataclass(frozen=True)
class Verification:
    valid: bool
    checked: int
    reason: str = ""


def verify(con: sqlite3.Connection) -> Verification:
    previous = None
    count = 0
    for body, prev, digest, legacy_id in con.execute("SELECT event,prev_hash,hash,legacy_event FROM audit_v2 ORDER BY id"):
        count += 1
        event = json.loads(body)
        if any(k not in event or event[k] is None for k in CATEGORIES):
            return Verification(False, count, "incomplete categories")
        legacy = con.execute("SELECT prev_hash,hash FROM audit WHERE id=?", (legacy_id,)).fetchone()
        if not legacy or event.get("legacy_hash") != legacy[1]:
            return Verification(False, count, "legacy link")
        expected = previous if previous else "legacy:" + legacy[0]
        if prev != expected or hashlib.sha256((prev + "\n" + body).encode()).hexdigest() != digest:
            return Verification(False, count, "chain mismatch")
        previous = digest
    return Verification(True, count)
