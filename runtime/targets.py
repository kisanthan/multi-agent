"""Atomic local mock target effects and receipts; no network inside transactions."""
import hmac
import time
import uuid
from datetime import datetime, timezone
from fastapi import HTTPException
from governance import control
from governance.audit_contract import canonical
from governance.step_policy import PolicyDenied
from runtime.tool_gateway import service_key


def execute(con, *, command_id: str, digest: str, token: str, supplied_key: str, audience: str) -> dict:
    if not supplied_key or not hmac.compare_digest(supplied_key, service_key()):
        raise HTTPException(401, "Dienstidentität fehlt oder ist ungültig.")
    try:
        with control.atomic(con):
            cmd = control.authorize_command(con, command_id)
            if digest != cmd["payload_hash"]:
                raise PolicyDenied("Payload-Hash stimmt nicht mit dem Kommando überein.")
            control.consume_grant(con, token, command_id, audience)
            if cmd["status"] in {"succeeded", "rejected"}:
                return cmd["receipt"]
            p = cmd["payload"]
            try:
                control.validate_payload(con, cmd["step"], p)
                result = _book(con, p) if audience == "navision" else _archive(con, cmd)
                status = "succeeded"
            except PolicyDenied as error:
                status, result = "rejected", {"reason": str(error)}
            receipt = {"command_id": command_id, "status": status, **result}
            control._log(con, cmd["case_id"], cmd["step"],
                         "zahlung_verbuchen" if audience == "navision" else "dokument_archivieren", status,
                         approval=control.approval_event(con, cmd["approval_id"]), command_id=command_id,
                         reason=canonical(result))
            con.execute("UPDATE execution_commands SET status=?,receipt=? WHERE command_id=?",
                        (status, canonical(receipt), command_id))
            return receipt
    except PolicyDenied as error:
        try:
            cmd = control.command(con, command_id)
            with control.atomic(con):
                control._log(con, cmd["case_id"], cmd["step"], "werkzeug_verweigert", "rejected",
                             reason=str(error), command_id=command_id)
        except PolicyDenied:
            pass
        raise HTTPException(403, str(error)) from error


def _book(con, p):
    timestamp = datetime.now(timezone.utc).isoformat()
    n = con.execute("UPDATE invoices SET status='bezahlt',paid_at=? WHERE number=? AND status='offen'",
                    (timestamp, p["number"])).rowcount
    if n != 1:
        raise PolicyDenied("Posten wurde bereits verändert.")
    return {"number": p["number"], "before": "offen", "after": "bezahlt", "paid_at": timestamp,
            "amount_cents": p["amount_cents"], "currency": "EUR"}


def _archive(con, cmd):
    p = cmd["payload"]
    original = con.execute("SELECT content FROM document_objects WHERE document_hash=?", (p["document_hash"],)).fetchone()
    import hashlib
    if not original or hashlib.sha256(original[0]).hexdigest() != p["document_hash"]:
        raise PolicyDenied("Originaldokument fehlt oder Hash ist ungültig.")
    # ELO treats the immutable document hash as the archival identity. A
    # repeated submission with the same filing assignment returns the same
    # logical archive object; a divergent assignment requires the explicit,
    # versioned correction path.
    existing = con.execute("SELECT a.archive_id,x.cost_center_id,x.filing_plan FROM archive a "
                           "LEFT JOIN archive_assignments x ON x.archive_id=a.archive_id AND x.active=1 "
                           "WHERE a.document_hash=?", (p["document_hash"],)).fetchall()
    if len(existing) > 1:
        raise PolicyDenied("Historische Dubletten erfordern manuelle Migration.")
    if existing:
        aid, center, plan = existing[0]
        if (center, plan) != (p["cost_center_id"], p["filing_plan"]):
            raise PolicyDenied("Abweichende oder historische Zuordnung: kontrollierte Korrektur erforderlich.")
        return {"archive_id": aid, "cost_center_id": center, "document_hash": p["document_hash"], "already_existed": True}
    aid = "ELO-" + uuid.uuid4().hex[:16].upper()
    con.execute("INSERT INTO archive VALUES(?,?,?,?)",
                (aid, p["filename"], p["document_hash"], datetime.now(timezone.utc).isoformat()))
    con.execute("INSERT INTO archive_assignments VALUES(?,?,?,?,?,1,1,?,?)",
                (uuid.uuid4().hex, aid, cmd["case_id"], p["cost_center_id"], p["filing_plan"], cmd["command_id"], time.time()))
    return {"archive_id": aid, "cost_center_id": p["cost_center_id"], "document_hash": p["document_hash"], "already_existed": False}
