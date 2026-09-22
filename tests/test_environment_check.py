"""Vertraege fuer die installationsunabhaengige Umgebungspruefung."""

from __future__ import annotations

import io
import json
from pathlib import Path

from scripts import check_environment as envcheck


def test_supported_python_version_starts_at_312():
    assert envcheck.python_version_supported((3, 12, 0)) is True
    assert envcheck.python_version_supported((3, 11, 9)) is False


def test_parse_env_ignores_comments_and_does_not_expand_values(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "# Kommentar\nMODEL_MODE=lokal\nAPI_TOKEN=super-secret\nEMPTY=\n",
        encoding="utf-8",
    )

    values = envcheck.parse_env(path)

    assert values == {
        "MODEL_MODE": "lokal",
        "API_TOKEN": "super-secret",
        "EMPTY": "",
    }


def test_required_models_follow_explicit_ollama_profiles():
    values = {
        "MODEL_MODE": "cloud",
        "LLM_ROUTER_PROVIDER": "ollama",
        "LLM_ROUTER_MODEL": "router:1b",
        "LLM_PAYMENT_PROVIDER": "anthropic",
        "LLM_PAYMENT_MODEL": "cloud-model",
        "LLM_INVOICE_PROVIDER": "ollama",
        "LLM_INVOICE_MODEL": "invoice:2b",
    }

    assert envcheck.required_ollama_models(values) == {"router:1b", "invoice:2b"}


def test_required_models_mirror_local_legacy_profile():
    values = {
        "MODEL_MODE": "lokal",
        "OLLAMA_MODEL_VISION": "vision:7b",
        "LLM_ROUTER_PROVIDER": "",
        "LLM_ROUTER_MODEL": "",
        "LLM_PAYMENT_PROVIDER": "",
        "LLM_PAYMENT_MODEL": "",
        "LLM_INVOICE_PROVIDER": "",
        "LLM_INVOICE_MODEL": "",
    }

    assert envcheck.required_ollama_models(values) == {"vision:7b"}


def test_cloud_legacy_mode_needs_no_ollama_model():
    assert envcheck.required_ollama_models({"MODEL_MODE": "cloud"}) == set()


def test_ollama_check_accepts_latest_tag(monkeypatch):
    payload = json.dumps({"models": [{"name": "vision:latest"}]}).encode()

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(envcheck.urllib.request, "urlopen", lambda *a, **k: Response(payload))

    result = envcheck.check_ollama_api("http://localhost:11434", {"vision"})

    assert result.status is envcheck.Status.OK


def test_ollama_check_names_missing_models_without_exposing_url_credentials(monkeypatch):
    payload = json.dumps({"models": []}).encode()

    class Response(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(envcheck.urllib.request, "urlopen", lambda *a, **k: Response(payload))

    result = envcheck.check_ollama_api(
        "http://user:password@localhost:11434", {"vision:7b"}
    )

    assert result.status is envcheck.Status.MISSING
    assert "vision:7b" in result.message
    assert "password" not in result.message


def test_project_root_is_derived_from_script_location(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    assert envcheck.PROJECT_ROOT == Path(envcheck.__file__).resolve().parent.parent


def test_summary_never_prints_environment_values(capsys):
    secret = "do-not-print-this"
    results = [envcheck.CheckResult(envcheck.Status.OK, "Konfiguration vorhanden")]

    exit_code = envcheck.print_summary(results, config_values={"API_TOKEN": secret})

    output = capsys.readouterr().out
    assert exit_code == 0
    assert secret not in output


def test_missing_result_produces_nonzero_exit_code(capsys):
    results = [envcheck.CheckResult(envcheck.Status.MISSING, "Ollama fehlt")]
    assert envcheck.print_summary(results, config_values={}) == 1


def test_occupied_port_is_a_warning_for_reuse_check(monkeypatch):
    class BusySocket:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def setsockopt(self, *args):
            pass

        def bind(self, *args):
            raise OSError("belegt")

    monkeypatch.setattr(envcheck.socket, "socket", lambda *a, **k: BusySocket())

    result = envcheck.check_port(8001)

    assert result.status is envcheck.Status.WARNING
