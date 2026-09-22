"""Plattformunabhaengige Vorpruefung fuer Installation und lokalen Betrieb.

Das Modul verwendet absichtlich nur die Python-Standardbibliothek. Es kann
daher vor der Installation von ``requirements.txt`` ausgefuehrt werden.
Konfigurationswerte werden ausgewertet, aber niemals ausgegeben.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import socket
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterable, Mapping


PROJECT_ROOT = Path(__file__).resolve().parent.parent
MINIMUM_PYTHON = (3, 12)
REQUIRED_PROJECT_FILES = (
    "requirements.txt",
    ".env.example",
    "demo.py",
    "ui/app.py",
    "data/demo/manifest.json",
)
CORE_IMPORTS = ("fastapi", "fitz", "langgraph", "pydantic", "streamlit")
START_PORTS = (8001, 8002, 8501)


class Status(Enum):
    OK = "OK"
    WARNING = "HINWEIS"
    MISSING = "FEHLT"
    ERROR = "FEHLER"


@dataclass(frozen=True)
class CheckResult:
    status: Status
    message: str


def python_version_supported(version: tuple[int, ...] | None = None) -> bool:
    version = version or tuple(sys.version_info)
    return version[:2] >= MINIMUM_PYTHON


def parse_env(path: Path) -> dict[str, str]:
    """Read simple dotenv assignments without interpolating or logging them."""
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def required_ollama_models(values: Mapping[str, str]) -> set[str]:
    """Mirror the profile fallback in ``config.Settings`` using stdlib only."""
    mode = values.get("MODEL_MODE", "lokal").strip().casefold()
    fallback = values.get("OLLAMA_MODEL_VISION", "qwen2.5vl:7b").strip()
    required: set[str] = set()
    for profile in ("ROUTER", "PAYMENT", "INVOICE"):
        provider = values.get(f"LLM_{profile}_PROVIDER", "").strip().casefold()
        model = values.get(f"LLM_{profile}_MODEL", "").strip()
        if provider or model:
            if provider == "ollama" and model:
                required.add(model)
        elif mode in {"lokal", "local"} and fallback:
            required.add(fallback)
    return required


def _normalized_model(name: str) -> str:
    value = name.strip().casefold()
    return value[:-7] if value.endswith(":latest") else value


def check_ollama_api(base_url: str, required_models: set[str]) -> CheckResult:
    if not required_models:
        return CheckResult(Status.OK, "Kein lokales Ollama-Modell konfiguriert")
    endpoint = f"{base_url.rstrip('/')}/api/tags"
    request = urllib.request.Request(endpoint, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=3) as response:
            payload = json.load(response)
    except (OSError, ValueError, urllib.error.URLError) as error:
        return CheckResult(
            Status.MISSING,
            f"Ollama ist nicht erreichbar ({type(error).__name__}); `ollama serve` starten",
        )
    installed = {
        _normalized_model(str(model.get("name", "")))
        for model in payload.get("models", [])
        if isinstance(model, dict)
    }
    missing = sorted(
        model for model in required_models if _normalized_model(model) not in installed
    )
    if missing:
        commands = ", ".join(f"ollama pull {model}" for model in missing)
        return CheckResult(Status.MISSING, f"Lokale Modelle fehlen: {commands}")
    return CheckResult(Status.OK, "Ollama und konfigurierte lokale Modelle sind bereit")


def check_project_files() -> CheckResult:
    missing = [path for path in REQUIRED_PROJECT_FILES if not (PROJECT_ROOT / path).exists()]
    if missing:
        return CheckResult(Status.ERROR, "Projektdateien fehlen: " + ", ".join(missing))
    return CheckResult(Status.OK, "Projektstruktur ist vollständig")


def check_writable() -> CheckResult:
    try:
        with tempfile.NamedTemporaryFile(dir=PROJECT_ROOT, prefix=".write-check-", delete=True):
            pass
    except OSError as error:
        return CheckResult(Status.ERROR, f"Projektverzeichnis ist nicht beschreibbar ({error.errno})")
    return CheckResult(Status.OK, "Projektverzeichnis ist beschreibbar")


def check_virtual_environment() -> CheckResult:
    expected = PROJECT_ROOT / ".venv"
    executable = Path(sys.executable).resolve()
    try:
        executable.relative_to(expected.resolve())
    except ValueError:
        return CheckResult(Status.MISSING, "Prüfung muss mit dem Interpreter aus .venv laufen")
    return CheckResult(Status.OK, "Virtuelle Umgebung .venv ist aktiv")


def check_imports() -> CheckResult:
    missing = [name for name in CORE_IMPORTS if importlib.util.find_spec(name) is None]
    if missing:
        return CheckResult(Status.MISSING, "Python-Abhängigkeiten fehlen: " + ", ".join(missing))
    return CheckResult(Status.OK, "Python-Abhängigkeiten sind installiert")


def check_port(port: int) -> CheckResult:
    family = socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as probe:
        try:
            probe.bind(("127.0.0.1", port))
        except OSError:
            return CheckResult(
                Status.WARNING,
                f"Port {port} ist belegt; das Startskript prüft eine mögliche Wiederverwendung",
            )
    return CheckResult(Status.OK, f"Port {port} ist verfügbar")


def _merged_config() -> dict[str, str]:
    values = parse_env(PROJECT_ROOT / ".env.example")
    values.update(parse_env(PROJECT_ROOT / ".env"))
    return values


def run_checks(mode: str) -> tuple[list[CheckResult], dict[str, str]]:
    values = _merged_config()
    results = [
        CheckResult(
            Status.OK if python_version_supported() else Status.MISSING,
            f"Python {platform.python_version()} "
            + ("wird unterstützt" if python_version_supported() else "ist zu alt; mindestens 3.12 erforderlich"),
        ),
        CheckResult(Status.OK, f"Plattform erkannt: {platform.system()} ({platform.machine()})"),
        check_project_files(),
        check_writable(),
    ]
    ollama_command = shutil.which("ollama")
    results.append(
        CheckResult(
            Status.OK if ollama_command else Status.WARNING,
            "Ollama-Befehl ist verfügbar" if ollama_command else "Ollama-Befehl nicht im PATH gefunden",
        )
    )
    if mode == "setup":
        if not (PROJECT_ROOT / ".env").exists():
            results.append(CheckResult(Status.WARNING, ".env wird durch das Setup angelegt"))
        return results, values

    results.extend((check_virtual_environment(), check_imports()))
    if not (PROJECT_ROOT / ".env").exists():
        results.append(CheckResult(Status.MISSING, ".env fehlt; Setup erneut ausführen"))
    else:
        results.append(CheckResult(Status.OK, ".env ist vorhanden"))
    models = required_ollama_models(values)
    results.append(check_ollama_api(values.get("OLLAMA_BASE_URL", "http://localhost:11434"), models))
    if mode == "start":
        results.extend(check_port(port) for port in START_PORTS)
    return results, values


def print_summary(
    results: Iterable[CheckResult], *, config_values: Mapping[str, str]
) -> int:
    # ``config_values`` is intentionally accepted but never rendered. This is
    # an explicit boundary against accidental secret disclosure.
    del config_values
    items = list(results)
    print("Umgebungsprüfung\n")
    for result in items:
        print(f"[{result.status.value:<7}] {result.message}")
    failed = any(item.status in {Status.MISSING, Status.ERROR} for item in items)
    print("\nErgebnis: " + ("nicht bereit" if failed else "bereit"))
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Voraussetzungen des Prototyps prüfen")
    parser.add_argument(
        "--mode",
        choices=("setup", "runtime", "start"),
        default="runtime",
        help="setup: Basissystem; runtime: Installation; start: zusätzlich freie Ports",
    )
    args = parser.parse_args(argv)
    results, values = run_checks(args.mode)
    return print_summary(results, config_values=values)


if __name__ == "__main__":
    raise SystemExit(main())
