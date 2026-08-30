"""Tests for llm/preflight.py -- operational readiness before a case starts.

Previously untested: demo.py --check and the UI's own model-status guard
both rely on this module, but nothing exercised it beyond "the file exists"
(tests/test_structure.py). These tests mock the Ollama HTTP transport the
same way tests/test_llm.py mocks the provider clients -- what is tested is
the *decision logic* (ready/not ready, which message), not a real Ollama
instance.
"""

from __future__ import annotations

import pytest

from config import ModelMode, settings
from llm import preflight


@pytest.fixture(autouse=True)
def pinned_model_names(monkeypatch):
    """Fixes both Ollama model names for every test in this file.

    Without this, the assertions below read whatever `.env` happens to say
    on the machine running them -- and one of them requires the small and
    the vision model to be *different* names, which no configuration
    promises. Pointing both at one model is legitimate and deliberate: the
    reader hands the classification agent markdown, not an image, so a text
    model covers both roles. This suite went red on exactly that the day a
    stale `.env` stopped being silently ignored.
    """
    monkeypatch.setattr(settings, "ollama_model_small", "test-klein:1b")
    monkeypatch.setattr(settings, "ollama_model_vision", "test-vision:1b")


# ------------------------------------------------------------ required_models()

def test_required_models_under_local_mode_includes_both_roles(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", ModelMode.LOCAL)
    needed = preflight.required_models()
    assert settings.ollama_model_vision in needed


def test_required_models_under_cloud_mode_is_empty(monkeypatch):
    """Nothing local is needed -- every model-using role goes to Anthropic."""
    monkeypatch.setattr(settings, "model_mode", ModelMode.CLOUD)
    assert preflight.required_models() == []


def test_required_models_under_hybrid_mode_excludes_risk_bearing_roles(monkeypatch):
    """Hybrid: only the local/uncritical roles need an Ollama model; the
    risk-bearing roles (klassifikation, buchung) go to Anthropic."""
    monkeypatch.setattr(settings, "model_mode", ModelMode.HYBRID)
    needed = preflight.required_models()
    assert needed == []


# ------------------------------------------------------------------------ check()

def test_check_cloud_mode_without_key_is_not_ready(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", ModelMode.CLOUD)
    monkeypatch.setattr(settings, "anthropic_api_key", "")
    readiness = preflight.check()
    assert readiness.ready is False


def test_check_cloud_mode_with_key_is_ready(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", ModelMode.CLOUD)
    monkeypatch.setattr(settings, "anthropic_api_key", "sk-test")
    readiness = preflight.check()
    assert readiness.ready is True


def test_check_local_mode_ollama_unreachable_gives_actionable_message(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", ModelMode.LOCAL)

    import httpx as httpx_module

    def unreachable(*args, **kwargs):
        raise httpx_module.ConnectError("Verbindung verweigert")

    monkeypatch.setattr("httpx.get", unreachable)

    readiness = preflight.check()
    assert readiness.ready is False
    assert any("nicht erreichbar" in m for m in readiness.messages)
    assert any("ollama serve" in m for m in readiness.messages)


def test_check_local_mode_missing_models_are_named(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", ModelMode.LOCAL)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "irgendein-anderes-modell:1b"}]}

    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse())

    readiness = preflight.check()
    assert readiness.ready is False
    assert settings.ollama_model_vision in readiness.required_models
    assert any(settings.ollama_model_vision in m for m in readiness.messages)


def test_check_local_mode_all_models_loaded_is_ready(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", ModelMode.LOCAL)

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": settings.ollama_model_vision}]}

    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse())

    readiness = preflight.check()
    assert readiness.ready is True


def test_check_local_mode_accepts_latest_tag_normalization(monkeypatch):
    """Ollama lists an untagged pull as 'name:latest'; a required model
    named without a tag must still match."""
    monkeypatch.setattr(settings, "model_mode", ModelMode.LOCAL)
    monkeypatch.setattr(settings, "ollama_model_vision", "qwen2.5vl")

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"models": [{"name": "qwen2.5vl:latest"}]}

    monkeypatch.setattr("httpx.get", lambda *a, **k: FakeResponse())

    readiness = preflight.check()
    assert readiness.ready is True


def test_check_hybrid_mode_needs_api_key_in_addition_to_ollama(monkeypatch):
    monkeypatch.setattr(settings, "model_mode", ModelMode.HYBRID)
    monkeypatch.setattr(settings, "anthropic_api_key", "")

    readiness = preflight.check()
    assert readiness.ready is False
    assert any("ANTHROPIC_API_KEY" in m for m in readiness.messages)


def test_readiness_report_names_ready_state():
    ready = preflight.Readiness(True, ["alles gut"])
    not_ready = preflight.Readiness(False, ["kaputt"])
    assert "OK" in ready.report()
    assert "NICHT BEREIT" in not_ready.report()
