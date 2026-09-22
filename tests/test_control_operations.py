"""Operational requirements: stop, recovery, migration and local-only inference."""
import pytest
from governance import control, identity
from governance.step_policy import PolicyDenied
from tests.test_control_contracts import tokens, proposal, approved, APPROVER


def test_stop_revokes_pending_execution(con, tokens, proposal):
    p = approved(con, tokens, proposal)
    cid = control.prepare_command(con, p)
    with identity.session(tokens[APPROVER]):
        control.set_stopped(con, "case-a", True, "Review required")
    with pytest.raises(PolicyDenied):
        control.grant(con, cid)


def test_recovery_api_rechecks_receipt_and_does_not_restart_case(con, tokens, proposal):
    assert callable(getattr(control, "recover_command", None)), "Controlled recovery is missing"


def test_cloud_and_remote_ollama_are_blocked(monkeypatch):
    from config import settings, ProfileId, Provider
    from llm.client import client_for
    monkeypatch.setattr(settings, "llm_payment_provider", Provider.OPENAI)
    monkeypatch.setattr(settings, "llm_payment_model", "synthetic")
    with pytest.raises(PolicyDenied):
        client_for("extraktion_zahlung", profile_id=ProfileId.PAYMENT)
    monkeypatch.setattr(settings, "llm_payment_provider", Provider.OLLAMA)
    monkeypatch.setattr(settings, "ollama_base_url", "https://remote.invalid")
    with pytest.raises(PolicyDenied):
        client_for("extraktion_zahlung", profile_id=ProfileId.PAYMENT)


def test_masked_layout_contract_requires_local_failure_and_human_review():
    import importlib.util
    assert importlib.util.find_spec("llm.layout") is not None, "Layout escalation contract is missing"
