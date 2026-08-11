"""ELO agent (process B): tamper-evident archiving.

The ELO agent is a Shared Domain Agent with write access and
human-on-the-loop oversight. It forms the end of process B (diagram part
3): after the cost-center assignment, the invoice is filed tamper-evidently
in the DMS -- process B does not involve a balance-sheet-effective booking.

The agent asks the policy before the write action -- an approval earlier in
the process (in case of ambiguity) does not replace the permission check at
the write site itself.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import httpx

from config import settings
from governance.audit import NO_REFERENCE, CaseReference, Decision, log_entry
from governance.policy import Outcome, check_write_action

ELO_AGENT_ID = "elo"


@dataclass(frozen=True)
class TargetSystemResult:
    successful: bool
    reference_id: str | None      # archive ID or booking reference ID
    reason: str
    error: str | None = None


def _policy_or_error(con: sqlite3.Connection, *, agent_id: str, actor: str,
                     action: str,
                     reference: CaseReference = NO_REFERENCE) -> TargetSystemResult | None:
    """Shared policy check. Returns None when allowed."""
    decision = check_write_action(con, agent_id=agent_id, actor=actor, action=action)
    if decision.outcome is Outcome.ALLOWED:
        return None

    log_entry(con, actor=actor, agent=agent_id, action=action,
              decision=Decision.DENIED, reason=decision.reason,
              payload={"rule": decision.rule},
              reference=reference, outcome="verweigert")
    con.commit()
    return TargetSystemResult(False, None, decision.reason, decision.rule)


def archive_document(con: sqlite3.Connection, *, filename: str, document_hash: str,
                     actor: str, reference: CaseReference = NO_REFERENCE) -> TargetSystemResult:
    """ELO agent: files the document tamper-evidently."""
    if (error := _policy_or_error(con, agent_id=ELO_AGENT_ID, actor=actor,
                                  action="dokument_archivieren", reference=reference)):
        return error

    try:
        response = httpx.post(
            f"{settings.elo_url}/archive",
            json={"filename": filename, "document_hash": document_hash,
                  "actor": actor, "case_id": reference.case_id},
            timeout=30.0,
        )
        response.raise_for_status()
    except httpx.HTTPError as e:
        return TargetSystemResult(False, None, f"ELO nicht erreichbar: {e}", str(e))

    data = response.json()
    note = " (war bereits abgelegt)" if data.get("already_existed") else ""
    return TargetSystemResult(
        True, data["archive_id"],
        f"Dokument abgelegt unter {data['archive_id']}{note}.",
    )
