"""Deterministic DMS adapter: confirmed assignment and immutable original."""
from dataclasses import dataclass
import sqlite3
import httpx  # transport injection remains possible without a live server
from governance import control
from governance.audit import CaseReference, NO_REFERENCE
from governance.policy import check_write_action
from governance.step_policy import PolicyDenied
from runtime.tool_gateway import dispatch

ELO_AGENT_ID = "elo"


@dataclass(frozen=True)
class TargetSystemResult:
    successful: bool
    reference_id: str | None
    reason: str
    error: str | None = None
    command_id: str | None = None
    uncertain: bool = False


def archive_document(con: sqlite3.Connection, *, filename: str, document_hash: str,
                     actor: str, reference: CaseReference = NO_REFERENCE,
                     cost_center_id: str | None = None, approval_id: str | None = None,
                     candidate_version: int | None = None, command_id: str | None = None) -> TargetSystemResult:
    ruling = check_write_action(con, agent_id=ELO_AGENT_ID, actor=actor, action="dokument_archivieren")
    if not ruling.allowed:
        return TargetSystemResult(False, None, ruling.reason, ruling.rule)
    try:
        c = control.require_active(con, reference.case_id)
        proposal = control.get_candidate(con, reference.case_id, "elo")
        if c["actor"] != actor or c["document_hash"] != document_hash:
            raise PolicyDenied("Vorgangs- oder Dokumentkontext verändert.")
        if proposal["version"] != candidate_version or proposal["approval_id"] != approval_id:
            raise PolicyDenied("Veraltete Zuordnung oder Freigabe.")
        if proposal["payload"]["cost_center_id"] != cost_center_id:
            raise PolicyDenied("Kostenstelle wurde nach der Prüfung verändert.")
        cid = command_id or control.prepare_command(con, proposal)
        receipt = dispatch(con, cid)
        success = receipt["status"] == "succeeded"
        return TargetSystemResult(success, receipt.get("archive_id"),
                                  "Original und Kostenstellenzuordnung abgelegt." if success else receipt.get("reason", "Ablage abgelehnt."),
                                  None if success else receipt.get("reason"), cid,
                                  receipt["status"] == "in_doubt")
    except PolicyDenied as error:
        return TargetSystemResult(False, None, str(error), str(error), command_id)
