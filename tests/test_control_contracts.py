"""Acceptance contracts, isolated synthetic records; no real model or network."""
from dataclasses import asdict, replace
import hashlib
import time
import pytest
from fastapi import HTTPException
from governance import control, identity
from governance.step_policy import POLICIES, evaluate, PolicyDenied
from governance.audit_contract import verify

SUBMITTER = "einspeiser@chg-meridian.com"
APPROVER = "pruefer@chg-meridian.com"


@pytest.fixture
def tokens(con):
    result = {}
    for name in (SUBMITTER, APPROVER):
        identity.set_password(con, name, "synthetic-test-password-2026")
        result[name] = identity.login(con, name, "synthetic-test-password-2026")
    return result


@pytest.fixture
def proposal(con, tokens):
    con.execute("INSERT INTO invoices(number,amount_eur,due_date,status) VALUES('R-1',125,'2026-01-01','offen')")
    con.commit()
    with identity.session(tokens[SUBMITTER]):
        control.register_case(con, case_id="case-a", actor=SUBMITTER,
                              document_hash=hashlib.sha256(b"synthetic").hexdigest(), filename="a.pdf", content=b"synthetic")
    control.select_process(con, "case-a", "A")
    return control.candidate(con, "case-a", "buchung", control.payment_payload(con, "case-a", "R-1", 125), True)


def approved(con, tokens, proposal):
    with identity.session(tokens[APPROVER]):
        control.decide(con, proposal, approved=True)
    return control.get_candidate(con, "case-a", "buchung")


def test_no_forged_or_self_approval(con, tokens, proposal):
    with pytest.raises(identity.AuthenticationError):
        control.decide(con, proposal, approved=True)
    with identity.session(tokens[SUBMITTER]), pytest.raises(PolicyDenied):
        control.decide(con, proposal, approved=True)
    assert control.get_candidate(con, "case-a", "buchung")["approval_status"] == "requested"


def test_one_command_per_approval(con, tokens, proposal):
    p = approved(con, tokens, proposal)
    cid = control.prepare_command(con, p)
    current = control.get_candidate(con, "case-a", "buchung")
    assert control.prepare_command(con, current) == cid
    assert con.execute("SELECT count(*) FROM execution_commands").fetchone()[0] == 1
    assert verify(con).valid


@pytest.mark.parametrize("field,value", [("tool", "delete"), ("level", 3), ("data_class", "public"),
                                        ("process", "B"), ("audit_required", False), ("purpose", "other")])
def test_step_contract_denies_changed_attributes(con, field, value):
    request = {**asdict(POLICIES[("A", "buchung")]), "case_id": "a"}
    request[field] = value
    with pytest.raises(PolicyDenied):
        evaluate(con, request)


def test_payload_change_invalidates_approval(con, tokens, proposal):
    approved(con, tokens, proposal)
    p = control.candidate(con, "case-a", "buchung", control.payment_payload(con, "case-a", "R-1", 124), True)
    with pytest.raises(PolicyDenied):
        control.prepare_command(con, p)


def test_rights_revocation_after_approval(con, tokens, proposal, monkeypatch):
    import agent_registry
    p = approved(con, tokens, proposal)
    monkeypatch.setitem(agent_registry.REGISTRY, "buchung", replace(agent_registry.REGISTRY["buchung"], can_write=False))
    with pytest.raises(PolicyDenied):
        control.prepare_command(con, p)


def test_atomic_target_and_replay(con, tokens, proposal, monkeypatch):
    from runtime import targets
    monkeypatch.setattr(targets, "service_key", lambda: "test-service-key")
    p = approved(con, tokens, proposal)
    cid = control.prepare_command(con, p)
    token = control.grant(con, cid)
    kwargs = dict(command_id=cid, digest=p["payload_hash"], token=token,
                  supplied_key="test-service-key", audience="navision")
    first = targets.execute(con, **kwargs)
    assert first["status"] == "succeeded"
    with pytest.raises(HTTPException):
        targets.execute(con, **kwargs)
    kwargs["token"] = control.grant(con, cid)
    assert targets.execute(con, **kwargs) == first
    assert con.execute("SELECT status FROM invoices").fetchone()[0] == "bezahlt"
    assert verify(con).valid


def test_audit_failure_rolls_back_target_effect(con, tokens, proposal, monkeypatch):
    from runtime import targets
    monkeypatch.setattr(targets, "service_key", lambda: "test-service-key")
    p = approved(con, tokens, proposal)
    cid = control.prepare_command(con, p)
    token = control.grant(con, cid)
    original_log = control._log
    def fail_on_effect(*args, **kwargs):
        if args[3] == "zahlung_verbuchen":
            raise RuntimeError("audit unavailable")
        return original_log(*args, **kwargs)
    monkeypatch.setattr(control, "_log", fail_on_effect)
    with pytest.raises(RuntimeError, match="audit unavailable"):
        targets.execute(con, command_id=cid, digest=p["payload_hash"], token=token,
                        supplied_key="test-service-key", audience="navision")
    assert con.execute("SELECT status FROM invoices").fetchone()[0] == "offen"
    assert control.command(con, cid)["status"] == "prepared"


def test_expired_grant_and_service_spoof_denied(con, tokens, proposal, monkeypatch):
    from runtime import targets
    monkeypatch.setattr(targets, "service_key", lambda: "test-service-key")
    p = approved(con, tokens, proposal)
    cid = control.prepare_command(con, p)
    token = control.grant(con, cid)
    con.execute("UPDATE scoped_grants SET expires=0")
    con.commit()
    for key in ("wrong", "test-service-key"):
        with pytest.raises(HTTPException):
            targets.execute(con, command_id=cid, digest=p["payload_hash"], token=token,
                            supplied_key=key, audience="navision")
    assert con.execute("SELECT status FROM invoices").fetchone()[0] == "offen"


@pytest.mark.parametrize("amount", [None, float("nan"), float("inf"), -1, 1.001])
def test_invalid_money_is_not_a_booking(amount):
    with pytest.raises(PolicyDenied):
        control.cents(amount)


def test_archive_correction_preserves_original_and_history(con, tokens, monkeypatch):
    from runtime import targets
    import uuid
    monkeypatch.setattr(targets, "service_key", lambda: "test-service-key")
    assert callable(getattr(control, "correct_archive", None)), "Archive correction is not implemented"
    con.executemany("INSERT INTO cost_centers VALUES(?,?,?,?)",
                    [("C1", "One", "REF1", ""), ("C2", "Two", "REF2", "")])
    con.execute("INSERT INTO ad_groups VALUES('SG-CHG-Konfiguration','Synthetic admin')")
    con.execute("INSERT INTO ad_memberships VALUES(?, 'SG-CHG-Konfiguration')", (APPROVER,))
    con.commit()
    content = b"synthetic-original"
    digest = hashlib.sha256(content).hexdigest()
    with identity.session(tokens[SUBMITTER]):
        control.register_case(con, case_id="case-b", actor=SUBMITTER, document_hash=digest,
                              filename="b.pdf", content=content)
    control.select_process(con, "case-b", "B")
    p = control.candidate(con, "case-b", "elo", control.archive_payload(con, "case-b", "C1"), False)
    cid = control.prepare_command(con, p)
    token = control.grant(con, cid)
    receipt = targets.execute(con, command_id=cid, digest=p["payload_hash"], token=token,
                              supplied_key="test-service-key", audience="elo")
    aid = receipt["archive_id"]
    with identity.session(tokens[SUBMITTER]), pytest.raises(PolicyDenied):
        control.correct_archive(con, aid, "C2", "Correction")
    with identity.session(tokens[APPROVER]):
        control.correct_archive(con, aid, "C2", "Incorrect cost center")
    assert con.execute("SELECT content FROM document_objects WHERE document_hash=?", (digest,)).fetchone()[0] == content
    assert con.execute("SELECT cost_center_id,active FROM archive_assignments ORDER BY version").fetchall() == [("C1", 0), ("C2", 1)]
    assert verify(con).valid
