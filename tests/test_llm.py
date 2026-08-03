"""Tests of the LLM abstraction and the validation layer (risk R1).

All tests run without a real model: the transport is mocked. That is
deliberate -- what is tested is the *behavior in response to* model
answers, not the model. Exactly this separation is what makes the
architecture testable.
"""

from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from pydantic import BaseModel, Field

from config import ModelMode, settings
from governance.audit import read_all, verify_chain
from llm.client import LLMUnreachable, ModelChoice, choose_model
from llm.extraction import MAX_ATTEMPTS, extract

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
