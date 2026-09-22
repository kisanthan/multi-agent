#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_PYTHON="$PROJECT_ROOT/.venv/bin/python"
RESET_DEMO_DATA=0

if [[ "${1:-}" == "--reset-demo-data" ]]; then
  RESET_DEMO_DATA=1
elif [[ $# -gt 0 ]]; then
  printf 'Unbekannter Parameter: %s\n' "$1" >&2
  exit 2
fi

find_python() {
  local candidate
  for candidate in python3 python; do
    if command -v "$candidate" >/dev/null 2>&1 && \
       "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))' 2>/dev/null; then
      command -v "$candidate"
      return 0
    fi
  done
  printf 'Python 3.12 oder neuer wurde nicht gefunden.\n' >&2
  printf 'Unter Linux kann zusätzlich das Paket python3-venv erforderlich sein.\n' >&2
  return 1
}

cd "$PROJECT_ROOT"
SYSTEM_PYTHON="$(find_python)"
"$SYSTEM_PYTHON" scripts/check_environment.py --mode setup

if [[ ! -x "$VENV_PYTHON" ]]; then
  printf 'Virtuelle Umgebung .venv wird erstellt ...\n'
  "$SYSTEM_PYTHON" -m venv .venv
fi

"$VENV_PYTHON" -m pip install --disable-pip-version-check -r requirements.txt

if [[ ! -f .env ]]; then
  cp .env.example .env
  printf '.env wurde aus .env.example erzeugt.\n'
else
  printf 'Vorhandene .env bleibt unverändert.\n'
fi

if [[ "$RESET_DEMO_DATA" -eq 1 || ! -f data/masterdata.db ]]; then
  "$VENV_PYTHON" -m data.generate
else
  printf 'Vorhandene Demodaten bleiben unverändert. Für einen Reset --reset-demo-data verwenden.\n'
fi

if ! "$VENV_PYTHON" scripts/check_environment.py --mode runtime; then
  printf 'Installation abgeschlossen; Ollama oder ein Modell fehlt noch.\n' >&2
  exit 1
fi
"$VENV_PYTHON" demo.py --check

printf '\nInstallation abgeschlossen. Start:\n  ./scripts/start.sh\n'
