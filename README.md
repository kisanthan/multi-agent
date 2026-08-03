# CHG-MERIDIAN Multi-Agent System — Technical Prototype

Demonstration and feasibility artifact for the master's thesis *"Role- and
risk-based multi-agent architecture for automating internal business
processes in IT companies"* (CHG-MERIDIAN case study), in the spirit of the
Design Science Research methodology per Hevner et al. (2004).

The prototype automates two internal financial processes (payment receipt,
incoming invoice) with a multi-agent system and technically substantiates
the thesis's five central architectural claims:

1. **Role- and risk-based agent configuration** — every agent has a type,
   autonomy level, oversight mode, and model class ([registry.py](registry.py)).
2. **Human-in-the-loop at risk points** — LangGraph interrupts pause the
   case until a human decides.
3. **Least Privilege** — the AD check is the entry condition into the
   reader tool.
4. **Tamper-evident audit trail** — hash-chained, append-only.
5. **Deterministic governance outside the language model** — enforced by
   test ([tests/test_layer_boundaries.py](tests/test_layer_boundaries.py)).

> **No real data, no real systems.** All data is synthetic, all target
> systems (Navision, ELO, AD) are mocked. The prototype demonstrates the
> feasibility of the **architecture**, not extraction quality on real data
> (see [docs/grenzen.md](docs/grenzen.md)).

## Stack

| Component | Choice | As of |
|---|---|---|
| Language | Python 3.12+ (tested on 3.14) | |
| Orchestration | LangGraph 1.2 (`interrupt()` + SQLite checkpointer) | May 2026 |
| PDF → Markdown | PyMuPDF4LLM (primary), Docling (via config) | |
| Models | Ollama (local) and/or Anthropic (cloud), switchable per agent | |
| Persistence / mocks | SQLite, FastAPI | |
| UI | Streamlit (approval queue) | |

Details and rationale for the stack validation: [docs/architektur.md](docs/architektur.md).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python -m data.generate        # generate synthetic data + PDFs
```

### Model provisioning

The prototype **loads no models and starts no services** — it connects to
an Ollama instance whose address is in `.env`. Loading the models is
operations and happens outside:

```bash
ollama serve                    # start the service (unless it runs as one)
ollama pull qwen3:8b            # load a model (name freely choosable)
```

In `.env`, **`OLLAMA_BASE_URL`** matters most — local or a server on the
network. Which model names should be available there is set in
`OLLAMA_MODELL_KLEIN` / `OLLAMA_MODELL_VISION`. Whether everything is ready
is checked with:

```bash
.venv/bin/python demo.py --check
```

For cloud or hybrid operation, set `MODELL_MODUS=hybrid` (or `cloud`) and
put `ANTHROPIC_API_KEY` in `.env`.

## Demo

The target-system mocks must be running for the write-path scenarios:

```bash
.venv/bin/uvicorn mocks.navision:app --port 8001 &
.venv/bin/uvicorn mocks.elo:app --port 8002 &
```

Then the five scenarios:

```bash
.venv/bin/python demo.py --liste           # all documents + expectations
.venv/bin/python demo.py --szenario 5      # governance demo (needs NO model)
.venv/bin/python demo.py --szenario 1      # happy path process A
.venv/bin/python demo.py --szenario 2      # exception case + HITL approval
.venv/bin/python demo.py --szenario 3      # happy path process B
.venv/bin/python demo.py --szenario 4      # ambiguous cost center
.venv/bin/python demo.py --alle            # all in sequence
.venv/bin/python demo.py --audit           # audit trail + chain verification
```

## UI

```bash
.venv/bin/streamlit run ui/app.py
```

The UI shows a document's complete path -- the scenarios can be played
through there without a terminal. The layout follows the question the user
currently has:

| Area | Page | Route | Content |
|---|---|---|---|
| **Upload** | Neuer Beleg | `/` | drop documents via drag-and-drop (multi-select, intake check) and start processing; below it, the most recently submitted cases |
| | Alle Vorgänge | `/historie` | all cases of both processes with search, filter, and date range |
| **Vorgangsarten** | Zahlungsbestätigung | `/zahlungsbestaetigung` | metrics, open and completed cases — process A only |
| | Eingangsrechnung | `/eingangsrechnung` | the same for process B |
| **Nachweis** | Protokoll | `/protokoll` | hash-chained audit trail, filterable by case, step, and decision; CSV export |
| | Architektur | `/architektur` | both processes as a flow plus the agent registry (autonomy level, oversight, model class) |

**On language:** the working views get by without the thesis's domain terms
-- no "Prozess A", no "Human-in-the-loop", no security groups. Whoever
needs those terms finds them bundled on the **Architektur** page; a test
([tests/test_ui_language.py](tests/test_ui_language.py)) keeps the
separation in place. The *content* of the audit trail remains exempt: it
holds the recorded wording, because evidence that gets rephrased for
display is not evidence.

A single case lives at `/vorgang?id=…` -- linkable and reload-proof, with a
process stepper, approval, confirmation, and a jump into the filtered audit
trail.

The user signed in via the sidebar is also the submitter. That makes both
governance claims visible in the interaction flow, not just in the test: a
user without `SG-CHG-DocIngest` cannot upload and is turned away at the
reader when starting an existing document (scenario 5); without
`SG-CHG-Freigabe`, the approval buttons stay locked. Only the consequence of
that appears on screen -- "Sie haben nur Leserechte", "Ihr Konto ist nicht
zum Hochladen von Belegen berechtigt" -- never the name of the group.

A run takes one to three minutes with a local model and blocks the starting
browser tab meanwhile; progress is shown node by node. Approvals from a
second tab are unaffected by this, because the state lives in the
checkpoint (see [docs/grenzen.md](docs/grenzen.md), L8).

**One more process** needs no new page: an entry in
[process_registry.py](process_registry.py) produces navigation, route,
working view, stepper, and filter.

## The five scenarios

| # | Scenario | Demonstrates |
|---|---|---|
| 1 | Valid payment → reconciliation ok → booking approval (HITL) → open→paid | Happy path A, financially effective booking is always human-in-the-loop |
| 2 | Unknown number → exception case → HITL approval → booking | Human-in-the-loop, exception handling |
| 3 | Invoice with cost-center reference → exact lookup → automatic archiving in ELO (end of process) | Happy path B, deterministic reference lookup |
| 4 | Invoice without reference → lookup fails → four-eyes approval → ELO | HITL on a missing reference |
| 5 | Unauthorized submitter → AD check denies | Least Privilege, governance |

## Tests

```bash
.venv/bin/python -m pytest -q
```

The tests run **without** a running Ollama: the language model is mocked,
the FastAPI mocks run via ASGI in-process. What is tested is the
architecture, not model quality. Particularly relevant for the thesis:

- `tests/test_layer_boundaries.py` -- the governance layer imports no LLM
  client (enforced via AST analysis).
- `tests/test_audit.py::test_verify_chain_detects_*` -- the tamper-evidence
  proof.
- `tests/test_scenarios.py` -- all five scenarios end-to-end.

## Project structure

```
agents/       one LangGraph node + extraction schemas per agent
governance/   deterministic, NO LLM: policy, ad, audit
tools/        reader tool (PDF -> markdown, AD check as entry condition)
llm/          provider abstraction, validated extraction, preflight
mocks/        FastAPI: Navision (ERP), ELO (DMS)
graph/        LangGraph workflow, state model, case overview, target-system effect
data/         data generator (seed-fixed), SQLite, generated PDFs
ui/           Streamlit UI
  shared/       style, formatting, filter, runtime context (knows no business logic)
  cases/        case list, detail view, run, step derivation
  upload/       intake check and storage
  pages/        upload, history, process (parameterized), audit, architecture
tests/        pytest
docs/         architecture, concept->code mapping, limitations
registry.py   agent configuration table (effective, not just documented)
process_registry.py  processes as configuration: step sequence, target system, fields
config.py     .env configuration
demo.py       CLI runner for the five scenarios
```

Model IDs and prices in the documentation are marked with the retrieval
date **2026-07-17** and change quarterly.
