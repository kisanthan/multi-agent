#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
LOG_DIRECTORY="$PROJECT_ROOT/.runtime_logs"
PIDS=()

cleanup() {
  local pid
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      wait "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

port_open() {
  "$PYTHON" -c 'import socket, sys; s=socket.socket(); s.settimeout(0.5); raise SystemExit(s.connect_ex(("127.0.0.1", int(sys.argv[1]))) != 0)' "$1"
}

mock_healthy() {
  "$PYTHON" -c 'import json, sys, urllib.request; data=json.load(urllib.request.urlopen(sys.argv[1], timeout=1)); raise SystemExit(data.get("status") != "ok" or data.get("system") != sys.argv[2])' "$1" "$2" 2>/dev/null
}

streamlit_healthy() {
  "$PYTHON" -c 'import sys, urllib.request; body=urllib.request.urlopen("http://127.0.0.1:8501", timeout=1).read().decode("utf-8", "ignore"); raise SystemExit("streamlit" not in body.casefold())' 2>/dev/null
}

wait_for_health() {
  local url="$1"
  local expected_system="$2"
  local pid="$3"
  local attempt
  for attempt in $(seq 1 30); do
    if ! kill -0 "$pid" 2>/dev/null; then
      printf 'Dienst wurde vor der Bereitschaft beendet: %s\n' "$url" >&2
      return 1
    fi
    if mock_healthy "$url" "$expected_system"; then
      return 0
    fi
    sleep 0.5
  done
  printf 'Dienst wurde nicht rechtzeitig bereit: %s\n' "$url" >&2
  return 1
}

cd "$PROJECT_ROOT"
if [[ ! -x "$PYTHON" ]]; then
  printf '.venv fehlt. Zuerst ./scripts/setup.sh ausführen.\n' >&2
  exit 1
fi
"$PYTHON" scripts/check_environment.py --mode start

NAVISION_READY=0
ELO_READY=0
STREAMLIT_READY=0
mock_healthy "http://127.0.0.1:8001/health" "navision-mock" && NAVISION_READY=1 || true
mock_healthy "http://127.0.0.1:8002/health" "elo-mock" && ELO_READY=1 || true
streamlit_healthy && STREAMLIT_READY=1 || true
if port_open 8001 && [[ "$NAVISION_READY" -eq 0 ]]; then
  printf 'Port 8001 ist durch einen anderen Dienst belegt.\n' >&2
  exit 1
fi
if port_open 8002 && [[ "$ELO_READY" -eq 0 ]]; then
  printf 'Port 8002 ist durch einen anderen Dienst belegt.\n' >&2
  exit 1
fi
if port_open 8501 && [[ "$STREAMLIT_READY" -eq 0 ]]; then
  printf 'Port 8501 ist durch einen anderen Dienst belegt.\n' >&2
  exit 1
fi
if [[ "$NAVISION_READY" -eq 1 && "$ELO_READY" -eq 1 && "$STREAMLIT_READY" -eq 1 ]]; then
  printf 'Der Prototyp läuft bereits unter http://127.0.0.1:8501.\n'
  exit 0
fi

mkdir -p "$LOG_DIRECTORY"
STAMP="$(date +%Y%m%d-%H%M%S)"
if [[ "$NAVISION_READY" -eq 0 ]]; then
  "$PYTHON" -m uvicorn mocks.navision:app --port 8001 >"$LOG_DIRECTORY/navision-$STAMP.out.log" 2>"$LOG_DIRECTORY/navision-$STAMP.err.log" &
  PIDS+=("$!")
  NAVISION_PID="$!"
  wait_for_health "http://127.0.0.1:8001/health" "navision-mock" "$NAVISION_PID"
else
  printf 'Vorhandener Navision-Mock wird wiederverwendet.\n'
fi
if [[ "$ELO_READY" -eq 0 ]]; then
  "$PYTHON" -m uvicorn mocks.elo:app --port 8002 >"$LOG_DIRECTORY/elo-$STAMP.out.log" 2>"$LOG_DIRECTORY/elo-$STAMP.err.log" &
  PIDS+=("$!")
  ELO_PID="$!"
  wait_for_health "http://127.0.0.1:8002/health" "elo-mock" "$ELO_PID"
else
  printf 'Vorhandener ELO-Mock wird wiederverwendet.\n'
fi
printf 'Mocks sind bereit. Streamlit startet; Beenden mit Ctrl+C.\n'
"$PYTHON" -m streamlit run ui/app.py --server.port 8501
