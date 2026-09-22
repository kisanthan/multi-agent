"""Authoritative case, proposal, approval and execution records.

Graph checkpoints are resumable workflow state, never authorization evidence.
All transitions here run in short SQLite write transactions.
"""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import json
import secrets
import sqlite3
import time
import uuid

from governance import ad, identity
from governance.audit import CaseReference, Decision, log_entry
from governance.audit_contract import canonical, payload_hash
from governance.step_policy import POLICY_VERSION, PolicyDenied, check

APPROVAL_TTL = 24 * 3600  # Explicit synthetic scenario parameter, not a company SLA.
GRANT_TTL = 15 * 60


@contextmanager
def atomic(con):
    if con.in_transaction:
        raise RuntimeError("Control operation requires a clean transaction boundary.")
    con.execute("BEGIN IMMEDIATE")
    try:
        yield
        con.commit()
    except BaseException:
        con.rollback()
        raise


def cents(value) -> int:
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount <= 0 or amount != amount.quantize(Decimal(".01")):
            raise ValueError()
        return int(amount * 100)
    except (InvalidOperation, ValueError, TypeError):
        raise PolicyDenied("Betrag muss positiv, endlich und centgenau sein.") from None


def case(con, case_id: str) -> dict:
    row = con.execute("SELECT actor,document_hash,filename,process,stopped FROM controlled_cases WHERE case_id=?", (case_id,)).fetchone()
    if not row:
        raise PolicyDenied("Vorgang ohne Kontrollnachweis: erneute Einreichung erforderlich.")
    return dict(zip(("actor", "document_hash", "filename", "process", "stopped"), row))


def require_active(con, case_id: str) -> dict:
    c = case(con, case_id)
    if c["stopped"]:
        raise PolicyDenied("Vorgang ist gestoppt.")
    if not ad.check_reader_access(con, c["actor"]).allowed:
        raise PolicyDenied("Prozessrecht des Einreichers wurde entzogen.")
    # Local credential revocation is effective at execution too.
    cred = con.execute("SELECT active FROM local_credentials WHERE upn=?", (c["actor"],)).fetchone()
    if not cred or not cred[0]:
        raise PolicyDenied("Einreicheridentität ist nicht aktiv.")
    return c


def register_case(con, *, case_id: str, actor: str, document_hash: str, filename: str, content: bytes) -> None:
    if identity.principal(con) != actor:
        raise PolicyDenied("Einreicher stimmt nicht mit der Sitzung überein.")
    if not ad.check_reader_access(con, actor).allowed:
        raise PolicyDenied("Kein Recht zur Belegannahme.")
    import hashlib
    if hashlib.sha256(content).hexdigest() != document_hash:
        raise PolicyDenied("Dokument wurde während der Verarbeitung verändert.")
    with atomic(con):
        existing = con.execute("SELECT actor,document_hash FROM controlled_cases WHERE case_id=?", (case_id,)).fetchone()
        if existing and existing != (actor, document_hash):
            raise PolicyDenied("Vorgangsidentität darf nicht verändert werden.")
        con.execute("INSERT OR IGNORE INTO controlled_cases VALUES(?,?,?,?,NULL,0,?)",
                    (case_id, actor, document_hash, filename, time.time()))
        con.execute("INSERT OR IGNORE INTO document_objects VALUES(?,?,?)", (document_hash, content, time.time()))
        check(con, "shared", "reader", case_id)
        _log(con, case_id, "reader", "vorgang_registriert", "registered")


def select_process(con, case_id: str, process: str) -> None:
    with atomic(con):
        c = require_active(con, case_id)
        if process not in {"A", "B"} or c["process"] not in {None, process}:
            raise PolicyDenied("Unzulässiger Prozesswechsel.")
        con.execute("UPDATE controlled_cases SET process=? WHERE case_id=?", (process, case_id))
        _log(con, case_id, "orchestrator", "prozess_zugeordnet", process)


def authorize_read(con, case_id: str, process: str, step: str, actor: str) -> None:
    c = require_active(con, case_id)
    if c["actor"] != actor or (process != "shared" and c["process"] != process):
        raise PolicyDenied("Prozess- oder Identitätskontext verändert.")
    check(con, process, step, case_id)


def _log(con, case_id, component, action, outcome, *, approval=None, command_id=None, reason=None):
    c = case(con, case_id)
    log_entry(con, actor=c["actor"], agent=component, action=action,
              decision=Decision.DENIED if outcome in {"rejected", "revoked"} else Decision.INFO,
              reason=reason or outcome, reference=CaseReference(case_id, c["document_hash"]),
              outcome=outcome, approval=approval, policy_version=POLICY_VERSION, command_id=command_id)


def payment_payload(con, case_id: str, number, amount) -> dict:
    import re
    c = require_active(con, case_id)
    if c["process"] != "A":
        raise PolicyDenied("Buchung gehört ausschließlich zu Prozess A.")
    normalized = re.sub(r"[^A-Z0-9-]", "", str(number or "").upper())
    row = con.execute("SELECT status,amount_eur FROM invoices WHERE number=?", (normalized,)).fetchone()
    return {"number": normalized, "amount_cents": cents(amount) if amount is not None else None,
            "currency": "EUR", "document_hash": c["document_hash"],
            "expected_status": row[0] if row else None,
            "expected_cents": cents(row[1]) if row else None}


def archive_payload(con, case_id: str, cost_center_id) -> dict:
    c = require_active(con, case_id)
    if c["process"] != "B":
        raise PolicyDenied("Archivierung gehört ausschließlich zu Prozess B.")
    return {"document_hash": c["document_hash"], "cost_center_id": cost_center_id,
            "filing_plan": "incoming_invoices", "filename": c["filename"]}


def candidate(con, case_id: str, step: str, payload: dict, approval_required: bool) -> dict:
    """Reuse an identical outstanding candidate; never reset a decided record."""
    c = require_active(con, case_id)
    p = check(con, c["process"], step, case_id)
    required = approval_required or p.approval == "always"
    digest = payload_hash(payload)
    with atomic(con):
        row = con.execute("SELECT version,payload_hash FROM case_candidates WHERE case_id=? AND step=? "
                          "ORDER BY version DESC LIMIT 1", (case_id, step)).fetchone()
        if row and row[1] == digest:
            previous = get_candidate(con, case_id, step, row[0])
            if previous["approval_status"] not in {"revoked", "expired"} and (not previous["expires"] or previous["expires"] > time.time()):
                return previous
        version = row[0] + 1 if row else 1
        con.execute("UPDATE approvals SET status='revoked' WHERE case_id=? AND step=? "
                    "AND status IN ('requested','approved')", (case_id, step))
        con.execute("INSERT INTO case_candidates VALUES(?,?,?,?,?,?,?)",
                    (case_id, step, version, canonical(payload), digest, int(required), time.time()))
        if required:
            con.execute("INSERT INTO approvals(approval_id,case_id,step,version,payload_hash,policy_version,"
                        "submitter,expires,status) VALUES(?,?,?,?,?,?,?,?,?)",
                        (uuid.uuid4().hex, case_id, step, version, digest, p.version,
                         c["actor"], time.time()+APPROVAL_TTL, "requested"))
        _log(con, case_id, step, "vorschlag_erstellt", "approval_required" if required else "validated_proposal",
             approval={"status": "requested" if required else "not_required", "person": None,
                       "time": None, "reference": None})
        return get_candidate(con, case_id, step, version)


def get_candidate(con, case_id, step, version=None) -> dict:
    clause = " AND version=?" if version is not None else ""
    args = (case_id, step, version) if version is not None else (case_id, step)
    row = con.execute("SELECT version,payload,payload_hash,approval_required FROM case_candidates "
                      "WHERE case_id=? AND step=?" + clause + " ORDER BY version DESC LIMIT 1", args).fetchone()
    if not row:
        raise PolicyDenied("Kein validierter Vorschlag vorhanden.")
    a = con.execute("SELECT approval_id,status,expires FROM approvals WHERE case_id=? AND step=? AND version=?",
                    (case_id, step, row[0])).fetchone()
    return {"case_id": case_id, "step": step, "version": row[0], "payload": json.loads(row[1]),
            "payload_hash": row[2], "approval_required": bool(row[3]),
            "approval_id": a[0] if a else None, "approval_status": a[1] if a else "not_required",
            "expires": a[2] if a else None}


def approval_event(con, approval_id):
    if not approval_id:
        return {"status": "not_required", "person": None, "time": None, "reference": None}
    row = con.execute("SELECT status,approver,decided_at FROM approvals WHERE approval_id=?", (approval_id,)).fetchone()
    if not row:
        raise PolicyDenied("Freigabereferenz unbekannt.")
    return {"status": row[0], "person": row[1], "time": row[2], "reference": approval_id}


def decide(con, proposal: dict, *, approved: bool, reason: str = "") -> str:
    person = identity.principal(con)
    with atomic(con):
        c = require_active(con, proposal["case_id"])
        from governance.policy import check_approval
        ruling = check_approval(con, actor=person, agent_id=proposal["step"], submitter=c["actor"])
        if not ruling.allowed or not c["actor"]:
            raise PolicyDenied(ruling.reason)
        current = get_candidate(con, proposal["case_id"], proposal["step"])
        if (current["version"], current["approval_id"], current["payload_hash"]) != (
                proposal["version"], proposal["approval_id"], proposal["payload_hash"]):
            raise PolicyDenied("Veralteter oder veränderter Freigabegegenstand.")
        check(con, c["process"], proposal["step"], c_id := proposal["case_id"])
        status = "approved" if approved else "rejected"
        n = con.execute("UPDATE approvals SET status=?,approver=?,decided_at=?,reason=? "
                        "WHERE approval_id=? AND status='requested' AND expires>?",
                        (status, person, time.time(), reason, proposal["approval_id"], time.time())).rowcount
        if n != 1:
            raise PolicyDenied("Freigabe ist entschieden, widerrufen oder abgelaufen.")
        _log(con, c_id, proposal["step"], "freigabe_erteilt" if approved else "klaerfall_entschieden",
             status, approval=approval_event(con, proposal["approval_id"]), reason=reason or status)
    return person


def validate_payload(con, step: str, payload: dict) -> None:
    if step == "buchung":
        row = con.execute("SELECT status,amount_eur FROM invoices WHERE number=?", (payload.get("number"),)).fetchone()
        if not row or row[0] != "offen" or payload.get("expected_status") != "offen":
            raise PolicyDenied("Posten unbekannt oder nicht offen.")
        if cents(row[1]) != payload.get("expected_cents"):
            raise PolicyDenied("Postenbetrag seit der Prüfung verändert.")
        amount = payload.get("amount_cents")
        if type(amount) is not int or amount <= 0:
            raise PolicyDenied("Kein verwertbarer Zahlbetrag.")
        from config import settings
        tolerance = Decimal(str(settings.amount_tolerance_eur)) * 100
        if not tolerance.is_finite() or abs(amount - cents(row[1])) > tolerance:
            # No company-authorized deviation policy supplied: do not invent one.
            raise PolicyDenied("Betragsabweichung außerhalb der zugelassenen Toleranz; fachliche Klärung erforderlich.")
    elif step == "elo":
        if payload.get("filing_plan") != "incoming_invoices" or not con.execute(
                "SELECT 1 FROM cost_centers WHERE id=?", (payload.get("cost_center_id"),)).fetchone():
            raise PolicyDenied("Kostenstelle oder Ablageplan ungültig.")
        if not con.execute("SELECT 1 FROM document_objects WHERE document_hash=?", (payload.get("document_hash"),)).fetchone():
            raise PolicyDenied("Originaldokument fehlt.")
    else:
        raise PolicyDenied("Unbekannte Schreibaktion.")


def prepare_command(con, proposal: dict) -> str:
    with atomic(con):
        c = require_active(con, proposal["case_id"])
        p = check(con, c["process"], proposal["step"], proposal["case_id"])
        current = get_candidate(con, proposal["case_id"], proposal["step"])
        if current != proposal:
            raise PolicyDenied("Vorschlag oder Freigabestatus wurde verändert.")
        prior = con.execute("SELECT command_id FROM execution_commands WHERE case_id=? AND step=? AND version=?",
                            (proposal["case_id"], proposal["step"], proposal["version"])).fetchone()
        if prior:
            return prior[0]
        validate_payload(con, proposal["step"], proposal["payload"])
        aid = proposal["approval_id"]
        cid = uuid.uuid4().hex
        if proposal["approval_required"] or p.approval == "always":
            if not aid:
                raise PolicyDenied("Strukturierte Freigabe fehlt.")
            _check_approval_current(con, aid, c["actor"], proposal["step"])
            n = con.execute("UPDATE approvals SET status='consumed',command_id=? WHERE approval_id=? "
                            "AND status='approved' AND expires>?", (cid, aid, time.time())).rowcount
            if n != 1:
                raise PolicyDenied("Freigabe fehlt, ist abgelaufen oder bereits verbraucht.")
        con.execute("INSERT INTO execution_commands VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (cid, proposal["case_id"], proposal["step"], proposal["version"], proposal["payload_hash"],
                     canonical(proposal["payload"]), aid, p.version, "prepared", None, time.time()))
        _log(con, proposal["case_id"], proposal["step"], "kommando_vorbereitet", "prepared",
             approval=approval_event(con, aid), command_id=cid)
        return cid


def _check_approval_current(con, aid, submitter, agent_id, command_id=None):
    row = con.execute("SELECT approver,status,expires,command_id,policy_version FROM approvals WHERE approval_id=?", (aid,)).fetchone()
    if not row or row[2] <= time.time() or row[4] != POLICY_VERSION:
        raise PolicyDenied("Freigabe abgelaufen oder falsche Regelversion.")
    if row[1] == "consumed":
        if not command_id or row[3] != command_id:
            raise PolicyDenied("Freigabe bereits verbraucht.")
    elif row[1] != "approved":
        raise PolicyDenied("Freigabe nicht erteilt.")
    from governance.policy import check_approval
    ruling = check_approval(con, actor=row[0], agent_id=agent_id, submitter=submitter)
    active = con.execute("SELECT active FROM local_credentials WHERE upn=?", (row[0],)).fetchone()
    if not ruling.allowed or not active or not active[0]:
        raise PolicyDenied("Freigaberecht wurde entzogen.")


def command(con, command_id: str) -> dict:
    row = con.execute("SELECT case_id,step,version,payload_hash,payload,approval_id,policy_version,status,receipt "
                      "FROM execution_commands WHERE command_id=?", (command_id,)).fetchone()
    if not row:
        raise PolicyDenied("Ausführungskommando unbekannt.")
    d = dict(zip(("case_id", "step", "version", "payload_hash", "payload", "approval_id", "policy_version", "status", "receipt"), row))
    d["payload"] = json.loads(d["payload"])
    d["receipt"] = json.loads(d["receipt"]) if d["receipt"] else None
    d["command_id"] = command_id
    return d


def authorize_command(con, command_id: str) -> dict:
    cmd = command(con, command_id)
    c = require_active(con, cmd["case_id"])
    p = check(con, c["process"], cmd["step"], cmd["case_id"])
    if cmd["policy_version"] != p.version or payload_hash(cmd["payload"]) != cmd["payload_hash"]:
        raise PolicyDenied("Kommando oder Regelversion verändert.")
    current = get_candidate(con, cmd["case_id"], cmd["step"])
    if current["version"] != cmd["version"] or current["payload_hash"] != cmd["payload_hash"]:
        raise PolicyDenied("Kommando gehört zu einem überholten Vorschlag.")
    if cmd["approval_id"]:
        _check_approval_current(con, cmd["approval_id"], c["actor"], cmd["step"], command_id)
    elif p.approval == "always" or current["approval_required"]:
        raise PolicyDenied("Freigabe fehlt.")
    return cmd


def grant(con, command_id: str) -> str:
    with atomic(con):
        cmd = authorize_command(con, command_id)
        c = case(con, cmd["case_id"])
        p = check(con, c["process"], cmd["step"], cmd["case_id"])
        token = secrets.token_urlsafe(32)
        con.execute("INSERT INTO scoped_grants VALUES(?,?,?,?,?,?,0)",
                    (identity.digest(token), command_id, "tool_gateway", p.target, p.tool, time.time()+GRANT_TTL))
        _log(con, cmd["case_id"], cmd["step"], "scoped_grant_erteilt", "issued", command_id=command_id)
        return token


def consume_grant(con, token: str, command_id: str, audience: str) -> None:
    """Must be called inside the same transaction as the target effect."""
    cmd = authorize_command(con, command_id)
    c = case(con, cmd["case_id"])
    p = check(con, c["process"], cmd["step"], cmd["case_id"])
    n = con.execute("UPDATE scoped_grants SET used=1 WHERE token_hash=? AND command_id=? "
                    "AND service='tool_gateway' AND audience=? AND tool=? AND expires>? AND used=0",
                    (identity.digest(token), command_id, audience, p.tool, time.time())).rowcount
    if n != 1 or p.target != audience:
        raise PolicyDenied("ScopedGrant ungültig, abgelaufen, bereits verwendet oder falscher Empfänger.")


def set_stopped(con, case_id: str, stopped: bool, reason: str) -> None:
    person = identity.principal(con)
    if not reason.strip() or not ad.check_approval_permission(con, person).allowed:
        raise PolicyDenied("Berechtigung und Begründung erforderlich.")
    with atomic(con):
        case(con, case_id)
        con.execute("UPDATE controlled_cases SET stopped=? WHERE case_id=?", (int(stopped), case_id))
        if stopped:
            con.execute("UPDATE approvals SET status='revoked' WHERE case_id=? AND status IN ('requested','approved','consumed')", (case_id,))
        _log(con, case_id, "policy", "vorgang_gestoppt" if stopped else "vorgang_fortgesetzt", "stopped" if stopped else "resumed", reason=reason)


def correct_archive(con, archive_id: str, cost_center_id: str | None, reason: str) -> None:
    """Human-only compensating assignment; original and past versions remain."""
    person = identity.principal(con)
    if not reason.strip() or not ad.check_configuration_permission(con, person).allowed:
        raise PolicyDenied("Archivkorrektur benötigt Administrationsrecht und Begründung.")
    with atomic(con):
        row = con.execute("SELECT assignment_id,case_id,cost_center_id,filing_plan,version FROM archive_assignments "
                          "WHERE archive_id=? AND active=1", (archive_id,)).fetchone()
        if not row:
            raise PolicyDenied("Keine aktive Zuordnung vorhanden.")
        c = case(con, row[1])
        from governance.policy import check_approval
        if not check_approval(con, actor=person, agent_id="elo", submitter=c["actor"]).allowed:
            raise PolicyDenied("Archivkorrektur erfordert eine andere berechtigte Person.")
        if cost_center_id is not None and not con.execute("SELECT 1 FROM cost_centers WHERE id=?", (cost_center_id,)).fetchone():
            raise PolicyDenied("Kostenstelle ungültig.")
        correction = uuid.uuid4().hex
        con.execute("UPDATE archive_assignments SET active=0 WHERE assignment_id=?", (row[0],))
        if cost_center_id is not None:
            con.execute("INSERT INTO archive_assignments VALUES(?,?,?,?,?,?,1,?,?)",
                        (uuid.uuid4().hex, archive_id, row[1], cost_center_id, row[3], row[4]+1, correction, time.time()))
        _log(con, row[1], "archive_admin", "ablagezuordnung_korrigiert", "corrected",
             command_id=correction, reason=canonical({"reason": reason, "before": row[2], "after": cost_center_id}),
             approval={"status": "approved", "person": person, "time": time.time(), "reference": correction})


def recover_command(con, command_id: str) -> dict:
    """Return the same authorized command; never create another business action."""
    person = identity.principal(con)
    if not ad.check_approval_permission(con, person).allowed:
        raise PolicyDenied("Wiederaufnahme erfordert eine berechtigte prüfende Person.")
    cmd = authorize_command(con, command_id)
    with atomic(con):
        _log(con, cmd["case_id"], "orchestrator", "wiederanlauf_geprueft", "recovery",
             command_id=command_id, approval=approval_event(con, cmd["approval_id"]))
    return cmd
