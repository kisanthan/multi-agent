"""Configuration profiles, persistence, permissions, and new providers."""

from __future__ import annotations

from types import SimpleNamespace
import sqlite3

from pydantic import BaseModel

import config
from config import AuthMethod, ModelMode, ProfileId, Provider, Settings, masked, settings
from llm.client import GoogleClient, LLMUnreachable, OpenAIClient, choose_profile
from llm.extraction import ExtractionResult


class Answer(BaseModel):
    value: str


def test_legacy_mode_remains_the_default(monkeypatch):
    monkeypatch.setattr(settings, "llm_router_provider", None)
    monkeypatch.setattr(settings, "llm_router_model", "")
    monkeypatch.setattr(settings, "model_mode", ModelMode.LOCAL)
    assert settings.profile(ProfileId.ROUTER).provider is Provider.OLLAMA


def test_process_profiles_are_independent(monkeypatch):
    monkeypatch.setattr(settings, "llm_payment_provider", Provider.OPENAI)
    monkeypatch.setattr(settings, "llm_payment_model", "gpt-test")
    monkeypatch.setattr(settings, "llm_invoice_provider", Provider.GOOGLE)
    monkeypatch.setattr(settings, "llm_invoice_model", "gemini-test")
    assert choose_profile(ProfileId.PAYMENT).provider == "openai"
    assert choose_profile(ProfileId.INVOICE).provider == "google"


def test_profile_snapshot_pins_revision(monkeypatch):
    monkeypatch.setattr(settings, "configuration_revision", 17)
    snapshot = settings.profile_snapshot()
    monkeypatch.setattr(settings, "configuration_revision", 18)
    assert choose_profile(ProfileId.ROUTER, snapshot).configuration_revision == 17


def test_explicit_profile_must_have_provider_and_model_together():
    import pytest

    with pytest.raises(ValueError, match="gemeinsam gesetzt"):
        Settings(llm_router_provider=Provider.OPENAI, llm_router_model="")


def test_env_update_preserves_comments_and_unknown_values(tmp_path, monkeypatch):
    env = tmp_path / ".env"
    env.write_text("# keep me\nUNKNOWN=value\nOPENAI_API_KEY=secret\n", encoding="utf-8")
    monkeypatch.setattr(config, "ENV_PATH", env)
    monkeypatch.setattr(settings, "ollama_base_url", "http://old:11434")
    monkeypatch.setattr(settings, "configuration_revision", 4)
    config.save_settings({"ollama_base_url": "http://new:11434"})
    text = env.read_text(encoding="utf-8")
    assert "# keep me" in text and "UNKNOWN=value" in text
    assert "OPENAI_API_KEY=secret" in text
    assert 'OLLAMA_BASE_URL="http://new:11434"' in text
    assert settings.configuration_revision == 5


def test_mask_never_reveals_whole_secret():
    secret = "sk-super-secret-1234"
    result = masked(secret)
    assert secret not in result
    assert result.endswith("1234)")


def test_openai_uses_responses_structured_output(monkeypatch):
    """Table 23 blocks standard cloud inference even when credentials exist."""
    import pytest
    from governance.step_policy import PolicyDenied
    with pytest.raises(PolicyDenied, match="Cloudmodelle"):
        OpenAIClient("synthetic-model").ask_json(system="system", prompt="unmasked invoice", schema=Answer)


def test_openai_refusal_stops_as_provider_failure(monkeypatch):
    """Table 23 blocks standard cloud inference even when credentials exist."""
    import pytest
    from governance.step_policy import PolicyDenied
    with pytest.raises(PolicyDenied, match="Cloudmodelle"):
        OpenAIClient("synthetic-model").ask_json(system="system", prompt="unmasked invoice", schema=Answer)


def test_google_uses_pydantic_response_schema(monkeypatch):
    """Table 23 blocks standard cloud inference even when credentials exist."""
    import pytest
    from governance.step_policy import PolicyDenied
    with pytest.raises(PolicyDenied, match="Cloudmodelle"):
        GoogleClient("synthetic-model").ask_json(system="system", prompt="unmasked invoice", schema=Answer)


def test_auth_methods_are_part_of_effective_profile(monkeypatch):
    monkeypatch.setattr(settings, "llm_invoice_provider", Provider.ANTHROPIC)
    monkeypatch.setattr(settings, "llm_invoice_model", "claude-test")
    monkeypatch.setattr(settings, "anthropic_auth_method", AuthMethod.PROFILE)
    assert settings.profile(ProfileId.INVOICE).auth_method is AuthMethod.PROFILE


def test_provider_failure_stops_payment_without_fallback(monkeypatch):
    from graph.nodes import payment_confirmation

    monkeypatch.setattr(payment_confirmation, "connection", lambda: SimpleNamespace(close=lambda: None))
    monkeypatch.setattr(
        payment_confirmation.extraction, "extract_payment",
        lambda *a, **k: ExtractionResult(
            data=None, attempts=1, model="cloud", provider="openai",
            escalation="Modell nicht erreichbar", unreachable=True,
        ),
    )
    result = payment_confirmation.node_payment_extraction({
        "markdown": "x", "actor": "a", "case_id": "c", "path": "x.pdf", "log": []
    })
    assert result["completed"] is True
    assert result["outcome"] == "modell_nicht_erreichbar"


def test_configuration_audit_payload_excludes_secret(con, monkeypatch):
    import pytest
    from ui.settings import service
    from governance import identity
    upn = "pruefer@chg-meridian.com"
    con.execute("INSERT INTO ad_groups VALUES('SG-CHG-Konfiguration','Admin')")
    con.execute("INSERT INTO ad_memberships VALUES(?, 'SG-CHG-Konfiguration')", (upn,))
    con.commit()
    identity.set_password(con, upn, "synthetic-admin-password")
    token = identity.login(con, upn, "synthetic-admin-password")
    captured = []
    monkeypatch.setattr(service, "save_settings", lambda updates: settings)
    monkeypatch.setattr(service, "connection", lambda: con)
    monkeypatch.setattr(service, "public_snapshot", lambda: {"profile": {}})
    monkeypatch.setattr(service, "log_entry", lambda con, **kwargs: captured.append(kwargs))
    with identity.session(token):
        with pytest.raises(PermissionError, match="Cloud"):
            service.save_configuration({"openai_api_key": "top-secret", "llm_router_model": "model-x"}, upn)
        service.save_configuration({"ollama_base_url": "http://localhost:11434"}, upn)
    assert "top-secret" not in repr(captured)
    assert captured[0]["payload"]["fields"] == ["ollama_base_url"]


def test_configuration_group_migration_is_idempotent_and_assigns_sabine():
    from governance.ad import CONFIGURATION_GROUP, ensure_configuration_seed

    con = sqlite3.connect(":memory:")
    con.executescript("""
        CREATE TABLE ad_users (
            upn TEXT PRIMARY KEY, display_name TEXT NOT NULL, role TEXT NOT NULL
        );
        CREATE TABLE ad_groups (name TEXT PRIMARY KEY, description TEXT NOT NULL);
        CREATE TABLE ad_memberships (
            upn TEXT NOT NULL, group_name TEXT NOT NULL,
            PRIMARY KEY (upn, group_name)
        );
        INSERT INTO ad_users VALUES (
            's.hofmann@chg-meridian.com', 'Sabine Hofmann', 'pruefer'
        );
    """)
    ensure_configuration_seed(con)
    ensure_configuration_seed(con)
    assert con.execute(
        "SELECT COUNT(*) FROM ad_groups WHERE name = ?", (CONFIGURATION_GROUP,)
    ).fetchone()[0] == 1
    assert con.execute(
        "SELECT COUNT(*) FROM ad_memberships WHERE upn = ? AND group_name = ?",
        ("s.hofmann@chg-meridian.com", CONFIGURATION_GROUP),
    ).fetchone()[0] == 1
