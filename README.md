# CHG-MERIDIAN Multiagentensystem — Technischer Prototyp

Demonstrations- und Machbarkeitsartefakt zur Master-Thesis *„Rollen- und
risikobasierte Multi-Agenten-Architektur zur Automatisierung interner
Business-Prozesse in IT-Unternehmen"* (Fallbeispiel CHG-MERIDIAN), im Sinne der
Design-Science-Research-Methodik nach Hevner et al. (2004).

Der Prototyp automatisiert zwei interne Finanzprozesse (Zahlungseingang,
Eingangsrechnung) mit einem Multiagentensystem und belegt technisch die fünf
zentralen Architekturaussagen der Arbeit:

1. **Rollen- und risikobasierte Agentenkonfiguration** — jeder Agent hat Typ,
   Autonomiestufe, Aufsichtsmodus und Modellklasse ([registry.py](registry.py)).
2. **Human-in-the-loop an Risikostellen** — LangGraph-Interrupts halten den
   Vorgang an, bis ein Mensch entscheidet.
3. **Least Privilege** — der AD-Check ist Eintrittsbedingung ins Reader-Tool.
4. **Manipulationsgeschützter Audit-Trail** — hash-verkettet, append-only.
5. **Deterministische Governance außerhalb des Sprachmodells** — per Test
   erzwungen ([tests/test_schichtgrenze.py](tests/test_schichtgrenze.py)).

> **Keine Echtdaten, keine echten Systeme.** Alle Daten sind synthetisch, alle
> Zielsysteme (Navision, ELO, AD) sind gemockt. Der Prototyp belegt die
> Machbarkeit der **Architektur**, nicht die Extraktionsgüte auf Echtdaten
> (siehe [docs/grenzen.md](docs/grenzen.md)).

## Stack

| Komponente | Wahl | Stand |
|---|---|---|
| Sprache | Python 3.12+ (getestet auf 3.14) | |
| Orchestrierung | LangGraph 1.2 (`interrupt()` + SQLite-Checkpointer) | Mai 2026 |
| PDF → Markdown | PyMuPDF4LLM (primär), Docling (per Config) | |
| Modelle | Ollama (lokal) und/oder Anthropic (Cloud), pro Agent umschaltbar | |
| Persistenz / Mocks | SQLite, FastAPI | |
| UI | Streamlit (Freigabe-Queue) | |

Details und Begründung der Stack-Validierung: [docs/architektur.md](docs/architektur.md).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m data.generate        # synthetische Daten + PDFs erzeugen
```

### Modell-Bereitstellung

Der Prototyp **lädt keine Modelle und startet keine Dienste** — er verbindet
sich gegen eine Ollama-Instanz, deren Adresse in `.env` steht. Das Laden der
Modelle ist Betrieb und erfolgt außerhalb:

```bash
ollama serve                    # Dienst starten (falls nicht als Service läuft)
ollama pull qwen3:8b            # Modell laden (Name frei wählbar)
```

In `.env` zählt vor allem **`OLLAMA_BASE_URL`** — lokal oder ein Server im Netz.
Welche Modellnamen dort bereitstehen sollen, steht in `OLLAMA_MODELL_KLEIN` /
`OLLAMA_MODELL_VISION`. Ob alles bereit ist, prüft:

```bash
.venv/bin/python demo.py --check
```

Für den Cloud- oder Hybridbetrieb `MODELL_MODUS=hybrid` (oder `cloud`) setzen und
`ANTHROPIC_API_KEY` in `.env` hinterlegen.

## Demo

Die Zielsystem-Mocks müssen für die schreibenden Szenarien laufen:

```bash
.venv/bin/uvicorn mocks.navision:app --port 8001 &
.venv/bin/uvicorn mocks.elo:app --port 8002 &
```

Dann die fünf Szenarien:

```bash
.venv/bin/python demo.py --liste           # alle Dokumente + Erwartungen
.venv/bin/python demo.py --szenario 5      # Governance-Demo (braucht KEIN Modell)
.venv/bin/python demo.py --szenario 1      # Happy Path Prozess A
.venv/bin/python demo.py --szenario 2      # Klärfall + HITL-Freigabe
.venv/bin/python demo.py --szenario 3      # Happy Path Prozess B
.venv/bin/python demo.py --szenario 4      # mehrdeutige Kostenstelle
.venv/bin/python demo.py --alle            # alle nacheinander
.venv/bin/python demo.py --audit           # Audit-Trail + Kettenprüfung
```

Freigabe-Queue (Human-in-the-loop) im Browser:

```bash
.venv/bin/streamlit run ui/app.py
```

## Die fünf Szenarien

| # | Szenario | Belegt |
|---|---|---|
| 1 | Gültige Zahlung → automatische Verbuchung (offen→bezahlt) | Happy Path A, schwellenbasierte Autonomie |
| 2 | Unbekannte Nummer → Klärfall → HITL-Freigabe → Verbuchung | Human-in-the-loop, Ausnahmebehandlung |
| 3 | Rechnung → eindeutige Kostenstelle → automatische Archivierung in ELO (Prozessende) | Happy Path B, Human-on-the-loop |
| 4 | Mehrdeutige Rechnung → Vier-Augen-Freigabe → Mensch entscheidet → ELO | HITL an semantischer Risikostelle |
| 5 | Unberechtigter Einspeiser → AD-Check verweigert | Least Privilege, Governance |

## Tests

```bash
.venv/bin/python -m pytest -q
```

Die Tests laufen **ohne** laufendes Ollama: das Sprachmodell ist gemockt, die
FastAPI-Mocks laufen per ASGI im Prozess. Geprüft wird die Architektur, nicht
die Modellgüte. Besonders relevant für die Arbeit:

- `tests/test_schichtgrenze.py` — die Governance-Schicht importiert keinen
  LLM-Client (per AST-Analyse erzwungen).
- `tests/test_audit.py::test_verify_chain_erkennt_*` — der Manipulationsnachweis.
- `tests/test_szenarien.py` — alle fünf Szenarien end-to-end.

## Projektstruktur

```
agents/       je Agent ein LangGraph-Knoten + Extraktionsschemata
governance/   deterministisch, KEIN LLM: policy, ad, audit
tools/        Reader-Tool (PDF -> Markdown, AD-Check als Eintrittsbedingung)
llm/          Anbieter-Abstraktion, validierte Extraktion, Preflight
mocks/        FastAPI: Navision (ERP), ELO (DMS)
graph/        LangGraph-Workflow + Zustandsmodell
data/         Datengenerator (seed-fest), SQLite, generierte PDFs
ui/           Streamlit-Freigabe-Queue
tests/        pytest
docs/         Architektur, Mapping Konzept->Code, Grenzen
registry.py   Agenten-Konfigurationstabelle (wirksam, nicht nur dokumentiert)
config.py     .env-Konfiguration
demo.py       CLI-Runner der fünf Szenarien
```

Modell-IDs und Preise in der Dokumentation sind mit Abrufdatum **17.07.2026**
gekennzeichnet und wechseln quartalsweise.
