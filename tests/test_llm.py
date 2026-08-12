"""Tests of the LLM abstraction and the validation layer (risk R1).

All tests run without a real model: the transport is mocked. That is
deliberate -- what is tested is the *behavior in response to* model
answers, not the model. Exactly this separation is what makes the
architecture testable.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from config import ModelMode, settings
from governance.audit import read_all, verify_chain
from llm.client import AnthropicClient, LLMUnreachable, ModelChoice, OllamaClient, choose_model
from llm.extraction import MAX_ATTEMPTS, extract
from llm.model_overrides import clear_override, load_overrides, save_override

ACTOR = "einspeiser@chg-meridian.com"


class Payment(BaseModel):
    number: str = Field(description="Rechnungs- oder Bestellnummer")
    amount_eur: float


@contextmanager
def model_responds(*responses, model: str = "qwen3:8b", provider: str = "ollama"):
    """Replaces the transport with fixed responses.

    `client_for` returns a tuple (client, ModelChoice); the mock must
    therefore return a real tuple with a real ModelChoice -- a MagicMock
    cannot be unpacked.

    Multiple arguments = consecutive responses. An exception instance is
    raised instead of returned.
    """
    client = MagicMock()
    if len(responses) == 1 and not isinstance(responses[0], BaseException):
        client.ask_json.return_value = responses[0]
    else:
        client.ask_json.side_effect = list(responses)

    choice = ModelChoice(provider=provider, model_id=model, risk_class="test")
    with patch("llm.extraction.client_for", return_value=(client, choice)) as factory:
        yield client, factory


# ------------------------------------------------- Model assignment (part 2)

def test_local_mode_uses_ollama_everywhere():
    with patch.object(settings, "model_mode", ModelMode.LOCAL):
        for agent in ("orchestrator", "klassifikation", "buchung", "elo"):
            assert choose_model(agent).provider == "ollama"


def test_hybrid_mode_splits_by_risk_class():
    """The core claim of teil2_ki_modelle.png, followed through in code."""
    with patch.object(settings, "model_mode", ModelMode.HYBRID):
        # Reading/uncritical roles stay local -> data sovereignty.
        assert choose_model("orchestrator").provider == "ollama"
        assert choose_model("elo").provider == "ollama"
        # Risk-bearing roles get a frontier model.
        assert choose_model("buchung").provider == "anthropic"
        assert choose_model("klassifikation").provider == "anthropic"


def test_cloud_mode_uses_anthropic_everywhere():
    with patch.object(settings, "model_mode", ModelMode.CLOUD):
        assert choose_model("klassifikation").provider == "anthropic"
        assert choose_model("buchung").provider == "anthropic"


def test_frontier_agent_gets_frontier_model():
    with patch.object(settings, "model_mode", ModelMode.HYBRID):
        assert choose_model("buchung").model_id == settings.cloud_model_frontier


@pytest.mark.parametrize("agent_id", ["reader", "policy", "audit", "abgleich", "kostenstelle"])
def test_deterministic_components_get_no_model(agent_id):
    """Reader/Policy/Audit AND the deterministically working domain agents
    (reconciliation, cost-center -- exact lookup) never call a language
    model."""
    with pytest.raises(ValueError, match="kein Sprachmodell"):
        choose_model(agent_id)


# ------------------------------------------------- Per-agent model overrides

@pytest.fixture(autouse=True)
def _overrides_file(tmp_path, monkeypatch):
    """Every override test gets its own scratch file -- never the real one."""
    monkeypatch.setattr("llm.model_overrides.MODEL_OVERRIDES_PATH",
                        tmp_path / "model_overrides.json")


def test_no_override_falls_back_to_default():
    with patch.object(settings, "model_mode", ModelMode.LOCAL):
        assert choose_model("elo").provider == "ollama"


def test_override_wins_over_mode():
    save_override("buchung", "ollama", "qwen3:8b")
    with patch.object(settings, "model_mode", ModelMode.CLOUD):
        choice = choose_model("buchung")
    assert choice.provider == "ollama"
    assert choice.model_id == "qwen3:8b"


def test_clear_override_restores_default():
    save_override("elo", "anthropic", "claude-haiku-4-5")
    clear_override("elo")
    with patch.object(settings, "model_mode", ModelMode.LOCAL):
        assert choose_model("elo").provider == "ollama"


def test_save_override_rejects_unknown_agent():
    with pytest.raises(KeyError):
        save_override("nicht-vorhanden", "ollama", "qwen3:8b")


def test_save_override_rejects_model_less_agent():
    with pytest.raises(ValueError, match="kein Sprachmodell"):
        save_override("policy", "ollama", "qwen3:8b")


def test_save_override_rejects_unsupported_provider():
    with pytest.raises(ValueError, match="Anbieter"):
        save_override("elo", "openai", "gpt-x")


def test_save_override_rejects_empty_model_id():
    with pytest.raises(ValueError, match="Modell-ID"):
        save_override("elo", "ollama", "  ")


def test_load_overrides_empty_when_file_missing():
    assert load_overrides() == {}


# --------------------------------------------------- Provider clients (transport)
#
# Everything above replaces client_for() wholesale with a MagicMock -- it
# tests the routing decision, never the two concrete clients themselves.
# These tests exercise OllamaClient/AnthropicClient.ask_json directly: the
# actual provider-neutral abstraction the thesis's sub-question 2 (cloud vs.
# open-source) rests on.

def test_ollama_client_returns_message_content(monkeypatch):
    class FakeResponse:
        status_code = 200

        def json(self):
            return {"message": {"content": '{"number": "RE-2026-4200", "amount_eur": 1.0}'}}

    def fake_post(url, **kwargs):
        assert url == f"{settings.ollama_base_url}/api/chat"
        assert kwargs["json"]["model"] == "qwen3:8b"
        return FakeResponse()

    monkeypatch.setattr("httpx.post", fake_post)
    client = OllamaClient("qwen3:8b")
    result = client.ask_json(system="s", prompt="p", schema=Payment)
    assert result == '{"number": "RE-2026-4200", "amount_eur": 1.0}'


def test_ollama_client_missing_model_gives_actionable_message(monkeypatch):
    """Ollama reports a missing model as HTTP 404 -- must become a message
    naming `ollama pull`, not a generic transport error."""
    class FakeResponse:
        status_code = 404
        text = "model not found"

    monkeypatch.setattr("httpx.post", lambda *a, **k: FakeResponse())
    client = OllamaClient("nicht-geladenes-modell")
    with pytest.raises(LLMUnreachable, match="ollama pull"):
        client.ask_json(system="s", prompt="p", schema=Payment)


def test_ollama_client_other_http_error(monkeypatch):
    class FakeResponse:
        status_code = 500
        text = "internal error"

    monkeypatch.setattr("httpx.post", lambda *a, **k: FakeResponse())
    client = OllamaClient("qwen3:8b")
    with pytest.raises(LLMUnreachable, match="HTTP 500"):
        client.ask_json(system="s", prompt="p", schema=Payment)


def test_ollama_client_unreachable_gives_actionable_message(monkeypatch):
    import httpx as httpx_module

    def unreachable(*args, **kwargs):
        raise httpx_module.ConnectError("Verbindung verweigert")

    monkeypatch.setattr("httpx.post", unreachable)
    client = OllamaClient("qwen3:8b")
    with pytest.raises(LLMUnreachable, match="ollama serve"):
        client.ask_json(system="s", prompt="p", schema=Payment)


def test_anthropic_client_returns_parsed_output_as_json(monkeypatch):
    import anthropic

    parsed = Payment(number="RE-2026-4200", amount_eur=1_341.96)

    class FakeMessages:
        def parse(self, **kwargs):
            assert kwargs["model"] == "claude-haiku-4-5"
            return SimpleNamespace(stop_reason="end_turn", parsed_output=parsed, content=[])

    class FakeAnthropic:
        def __init__(self, *, api_key):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    client = AnthropicClient("claude-haiku-4-5")
    result = client.ask_json(system="s", prompt="p", schema=Payment)
    assert json.loads(result) == {"number": "RE-2026-4200", "amount_eur": 1341.96}


def test_anthropic_client_falls_back_to_text_content(monkeypatch):
    """When parsed_output is None (the model did not honor output_format),
    the raw text content is returned instead -- validation happens
    upstream in llm/extraction.py, not here."""
    import anthropic

    class FakeMessages:
        def parse(self, **kwargs):
            return SimpleNamespace(
                stop_reason="end_turn", parsed_output=None,
                content=[SimpleNamespace(type="text", text="raw text")],
            )

    class FakeAnthropic:
        def __init__(self, *, api_key):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    client = AnthropicClient("claude-haiku-4-5")
    assert client.ask_json(system="s", prompt="p", schema=Payment) == "raw text"


def test_anthropic_client_refusal_is_unreachable(monkeypatch):
    import anthropic

    class FakeMessages:
        def parse(self, **kwargs):
            return SimpleNamespace(stop_reason="refusal", parsed_output=None, content=[])

    class FakeAnthropic:
        def __init__(self, *, api_key):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    client = AnthropicClient("claude-haiku-4-5")
    with pytest.raises(LLMUnreachable, match="Sicherheitsgruenden"):
        client.ask_json(system="s", prompt="p", schema=Payment)


def test_anthropic_client_missing_api_key(monkeypatch):
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    client = AnthropicClient("claude-haiku-4-5")
    with pytest.raises(LLMUnreachable, match="ANTHROPIC_API_KEY"):
        client.ask_json(system="s", prompt="p", schema=Payment)


def test_anthropic_client_api_error(monkeypatch):
    import anthropic
    import httpx as httpx_module

    class FakeMessages:
        def parse(self, **kwargs):
            raise anthropic.APIError(
                "boom", httpx_module.Request("POST", "https://api.anthropic.com/v1/messages"),
                body=None,
            )

    class FakeAnthropic:
        def __init__(self, *, api_key):
            self.messages = FakeMessages()

    monkeypatch.setattr(anthropic, "Anthropic", FakeAnthropic)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

    client = AnthropicClient("claude-haiku-4-5")
    with pytest.raises(LLMUnreachable, match="Anthropic-API-Fehler"):
        client.ask_json(system="s", prompt="p", schema=Payment)


# ------------------------------------- Validation / retry / escalation (R1)

def test_valid_response_on_first_attempt(con):
    with model_responds('{"number": "RE-2026-4200", "amount_eur": 1341.96}'):
        e = extract(con, agent_id="klassifikation", actor=ACTOR,
                    system="s", prompt="p", schema=Payment)

    assert e.succeeded
    assert e.attempts == 1
    assert e.data.number == "RE-2026-4200"
    assert e.data.amount_eur == 1341.96
    assert e.escalation is None


def test_schema_violation_gets_one_retry(con):
    """R1: first allow a correction, only then escalate."""
    with model_responds(
        '{"number": "RE-2026-4200"}',                        # amount_eur missing
        '{"number": "RE-2026-4200", "amount_eur": 1341.96}',  # correction
    ) as (client, _):
        e = extract(con, agent_id="klassifikation", actor=ACTOR,
                    system="s", prompt="p", schema=Payment)

    assert e.succeeded
    assert e.attempts == 2
    assert client.ask_json.call_count == 2


def test_retry_names_the_concrete_error(con):
    """The retry prompt must name the missing field, otherwise the model just guesses."""
    with model_responds(
        '{"number": "RE-2026-4200"}',
        '{"number": "RE-2026-4200", "amount_eur": 1341.96}',
    ) as (client, _):
        extract(con, agent_id="klassifikation", actor=ACTOR,
               system="s", prompt="p", schema=Payment)

    second_prompt = client.ask_json.call_args_list[1].kwargs["prompt"]
    assert "amount_eur" in second_prompt


def test_persistent_schema_violation_escalates_instead_of_guessing(con):
    """The decisive test for R1.

    If the model fails twice, no partial result is delivered and nothing is
    guessed -- the case goes to a human. A model failure thereby becomes an
    approval case, not a silent data error.
    """
    with model_responds('{"quatsch": true}', model="gemma4:26b") as (client, _):
        e = extract(con, agent_id="klassifikation", actor=ACTOR,
                    system="s", prompt="p", schema=Payment)

    assert not e.succeeded
    assert e.data is None
    assert e.escalation is not None
    assert e.attempts == MAX_ATTEMPTS
    assert client.ask_json.call_count == MAX_ATTEMPTS  # no third attempt


def test_non_json_escalates(con):
    """Per #15540, Ollama occasionally returns prose instead of JSON."""
    with model_responds("Klar! Die Nummer lautet RE-2026-4200."):
        e = extract(con, agent_id="klassifikation", actor=ACTOR,
                    system="s", prompt="p", schema=Payment)

    assert not e.succeeded


def test_unreachable_model_is_not_retried(con):
    """A transport error is an operational problem -- retrying does not help."""
    with model_responds(LLMUnreachable("ollama serve laeuft nicht")) as (client, _):
        e = extract(con, agent_id="klassifikation", actor=ACTOR,
                    system="s", prompt="p", schema=Payment)

    assert not e.succeeded
    assert "nicht erreichbar" in e.escalation
    assert client.ask_json.call_count == 1


# ------------------------------------------------------ Audit coupling

def test_escalation_is_traceable_in_the_audit_trail(con):
    """A model failure must be in the trail too -- otherwise the audit is missing it."""
    with model_responds('{"quatsch": true}', model="gemma4:26b"):
        extract(con, agent_id="klassifikation", actor=ACTOR,
               system="s", prompt="p", schema=Payment)

    actions = [e.action for e in read_all(con)]
    assert actions.count("llm_schemaverletzung") == MAX_ATTEMPTS
    assert "llm_eskalation" in actions
    assert verify_chain(con).valid


def test_successful_extraction_logs_the_model(con):
    """Traceability: which model delivered which result?"""
    with model_responds('{"number": "RE-2026-4200", "amount_eur": 1341.96}'):
        extract(con, agent_id="klassifikation", actor=ACTOR,
               system="s", prompt="p", schema=Payment)

    entry = read_all(con)[-1]
    assert entry.action == "llm_extraktion"
    assert entry.agent == "klassifikation"
    assert verify_chain(con).valid
