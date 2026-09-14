# CHG-MERIDIAN Multi-Agent System — Technical Prototype

Demonstration and feasibility artifact for the master's thesis *"Role- and
risk-based multi-agent architecture for automating internal business
processes in IT companies"* (CHG-MERIDIAN case study), in the spirit of the
Design Science Research methodology per Hevner et al. (2004).

The prototype automates two internal financial processes (payment receipt,
incoming invoice) with a multi-agent system and technically substantiates
the thesis's five central architectural claims:

1. **Role- and risk-based agent configuration** — every agent has a type,
   autonomy level, oversight mode, and model class ([agent_registry.py](agent_registry.py)).
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
> (see [docs/limitations.md](docs/limitations.md)).

**New here?** [docs/guide.md](docs/guide.md) is the step-by-step
operator's guide -- setup, running the demo/UI, and how to configure AI
models per agent. This README stays the terser reference.

## Stack

| Component | Choice | As of |
|---|---|---|
| Language | Python 3.12+ (tested on 3.14) | |
| Orchestration | LangGraph 1.2 (`interrupt()` + SQLite checkpointer) | May 2026 |
| PDF → Markdown | PyMuPDF4LLM (primary), Docling (via config) | |
| Models | Ollama (local), Google, Anthropic, OpenAI; separate process profiles | |
| Persistence / mocks | SQLite, FastAPI | |
| UI | Streamlit (case cockpit, approval as a modal dialog) | |

Details and rationale for the stack validation: [docs/architecture.md](docs/architecture.md).

## Setup

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
```

The repository already contains an immutable synthetic demo bundle under
`data/demo/`. The UI, CLI and target-system mocks automatically install
missing writable copies in `data/masterdata.db`, `data/manifest.json` and
`data/inbox/`; no data-generation step is required for a first run.

**On Windows (PowerShell),** the venv layout and copy command differ; every
other command in this README is otherwise identical -- replace `.venv/bin/`
with `.venv\Scripts\` and `python3` with `python` throughout:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
Copy-Item .env.example .env
```

To reset only the writable demo runtime to a fresh deterministic state, run
`.venv/bin/python -m data.generate`. Maintainers regenerate the versioned
bundle intentionally with `.venv/bin/python -m data.generate --seed-bundle`.

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
`OLLAMA_MODEL_SMALL` / `OLLAMA_MODEL_VISION`. Whether everything is ready
is checked with:

```bash
.venv/bin/python demo.py --check
```

`MODEL_MODE` remains supported for existing installations. The UI page
**Agentenkonfiguration** is the preferred configuration path. Each of the
three AI agents has its own area with provider-specific connection fields,
connection status, dynamically discovered models and a custom model-id option.
Google supports API key or Cloud OAuth, Anthropic API key or a
developer-workspace profile, and OpenAI an API key. Consumer ChatGPT and
Claude subscriptions do not include API usage. See
[docs/guide.md](docs/guide.md#4-configuring-ai-models-per-agent).

## Demo

**On language:** `demo.py`'s CLI output (prompts, scenario labels, the
approval dialog) is deliberately German, same as the UI -- see "On
language" under UI below. Only this paragraph and the rest of the
documentation are English.

The target-system mocks must be running for the write-path scenarios:

```bash
.venv/bin/uvicorn mocks.navision:app --port 8001 &
.venv/bin/uvicorn mocks.elo:app --port 8002 &
```

**On Windows,** trailing `&` does not background a process the same way --
open two separate PowerShell windows and run one command in each instead:

```powershell
.venv\Scripts\python.exe -m uvicorn mocks.navision:app --port 8001
.venv\Scripts\python.exe -m uvicorn mocks.elo:app --port 8002
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
| **Aufgaben** | Benachrichtigungen | `/notifications` | personal queue of waiting cases the signed-in user may approve; navigation count and toast for new tasks |
| **Upload** | Neuer Beleg | `/` | drop documents via drag-and-drop (multi-select, intake check) and start processing |
| | Alle Vorgänge | `/cases` | all cases of both processes with search, filter, and date range |
| **Vorgangsarten** | Zahlungsbestätigung | `/payment-confirmation` | metrics, open and completed cases — process A only |
| | Eingangsrechnung | `/incoming-invoice` | the same for process B |
| **Nachweis** | Protokoll | `/record` | hash-chained audit trail, filterable by case, step, and decision; CSV export |
| | Architektur | `/architecture` | both processes as a flow plus the agent registry (autonomy level, oversight, model class) |
| **System** | Einstellungen | `/preferences` | personal interface settings, including language and light/dark appearance |
| | Agentenkonfiguration | `/settings` | provider connection, status and selectable models per agent profile; parser and payment tolerance; only configuration admins may edit |

**German or English**, switchable under **System → Einstellungen** at
any time. The catalogs
are one flat JSON per language under [ui/locales/](ui/locales/); the rules
for what belongs in them live in
[ui/shared/i18n.py](ui/shared/i18n.py). Two of those rules matter beyond
the mechanics:

- **The interface is translated, the record is not.** Headings, buttons,
  and column names follow the chosen language. What a node wrote into the
  run log and what the audit trail recorded stays in the wording it was
  written in -- evidence that gets rephrased for display is not evidence.
  Number and date formats *do* follow the language, because "1.341,96" and
  "1,341.96" are different numbers to different readers.
- **German lives in exactly one place.** Process names, agent names, and
  status labels stay in their registries; the catalogs carry only the other
  languages, and [tests/test_i18n.py](tests/test_i18n.py) pins that a new
  process or agent cannot silently stay German in the English interface.

**On vocabulary:** the working views get by without the thesis's domain
terms -- no "Prozess A", no "Human-in-the-loop", no security groups.
Whoever needs those terms finds them bundled on the **Architektur** page; a
test ([tests/test_ui_language.py](tests/test_ui_language.py)) keeps the
separation in place, in both languages. That second language is where the
rule earns its keep: the obvious English word for "Protokoll" *is* "audit
trail", and the test is what stops it from getting there.

A single case lives at `/case?id=…` -- linkable and reload-proof, with a
process stepper, approval, confirmation, and a jump into the filtered audit
trail. Routes stay in one language regardless of the interface language: an
address that moves when someone switches language cannot be shared.

The user signed in via the sidebar is also the submitter. That makes both
governance claims visible in the interaction flow, not just in the test: a
user without `SG-CHG-DocIngest` cannot upload and is turned away at the
reader when starting an existing document (scenario 5); without
`SG-CHG-Freigabe`, the approval buttons stay locked. Even a member of that
group cannot approve their own submission; this is enforced again when the
workflow consumes the resume payload, not only in the UI. Only the consequence of
that appears on screen -- "Sie haben nur Leserechte", "Ihr Konto ist nicht
zum Hochladen von Belegen berechtigt" -- never the name of the group.

A run takes one to three minutes with a local model and blocks the starting
browser tab meanwhile; progress is shown node by node. While the router and
the process-specific extraction model are running, the sidebar opens and stays
visible with the PDF name, the active provider/model, and the completed AI
steps. Once extraction finishes, its structured fields appear in a compact
two-column table. The final overview remains
available after navigation until it is closed. Approvals from a
second tab are unaffected by this, because the state lives in the
checkpoint (see [docs/limitations.md](docs/limitations.md), L8).

**One more process** follows the same pattern throughout the codebase: one
entry in [process_registry.py](process_registry.py) (which produces
navigation, route, working view, stepper, and filter), its own agents under
`agents/<process>/`, its own nodes under `graph/nodes/<process>.py`, and its
own case-detail fragment under `ui/cases/process_views/<process>.py`. Wiring the
new file in touches exactly three shared places: `graph/workflow.py`
(`add_node`/`add_conditional_edges`), `graph/nodes/shared.py`'s
`route_document_type` (one more routing branch), and
`ui/cases/process_views/__init__.py`'s `VIEWS` registry -- plus, only if the new
process has a step that can be conditionally skipped the way process B's
`freigabe` is, `ui/cases/steps.py::_step_status`. `ui/cases/detail.py` itself
needs no change: it already resolves everything process-specific through
the registries above -- nothing to edit inside the other processes' own
files.

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
the FastAPI mocks run via ASGI in-process. A temporary runtime database and
temporary inbox are generated for the test session, so local demo data under
`data/` is not modified. What is tested is the
architecture, not model quality. Particularly relevant for the thesis:

- `tests/test_layer_boundaries.py` -- the governance layer imports no LLM
  client (enforced via AST analysis).
- `tests/test_process_separation.py` -- process A and process B stay
  separated at the file level: A's node module never imports B's agents
  and vice versa (same AST technique, one level down).
- `tests/test_audit.py::test_verify_chain_detects_*` -- the tamper-evidence
  proof.
- `tests/test_scenarios.py` -- all five scenarios end-to-end.

Coverage (optional, `pytest-cov` is in `requirements.txt`):

```bash
.venv/bin/python -m pytest -q --cov=agents --cov=governance --cov=graph \
  --cov=llm --cov=tools --cov=mocks --cov=ui --cov-report=term-missing
```

As of this writing: 82% overall, 95-97% across `agents/`, `governance/`,
`graph/`, and `llm/` -- the layers the thesis's architectural claims rest
on. The honest, expected gap is the Streamlit UI's decision screens
(`ui/cases/detail.py`, `ui/cases/run.py`, `ui/cases/approval_dialog.py`)
and some interactive decision screens, which have less UI-level coverage
(see `tests/test_ui_smoke.py`'s own docstring).
The logic behind them is covered directly at its source all the same: the
authorization checks by `tests/test_scenarios.py`'s unauthorized-approver
tests and `tests/test_booking.py`; provider/profile configuration is covered
by `tests/test_settings.py` and `tests/test_ui_smoke.py`.

## Project structure

```
agents/       domain agents
  shared/       schemas + document router (shared by A and B)
  payment_confirmation/  process A: extraction, reconciliation, booking
  incoming_invoice/      process B: extraction, cost-center assignment, archiving
governance/   deterministic, NO LLM: policy, ad, audit
tools/        reader tool (PDF -> markdown, AD check as entry condition)
llm/          provider abstraction, validated extraction, profile routing, preflight
mocks/        FastAPI: Navision (ERP), ELO (DMS)
graph/        LangGraph workflow, state model, case overview, target-system effect
  nodes/        graph nodes: shared.py (intake stretch) + one module per process
data/         data generator (seed-fixed), SQLite, generated PDFs
ui/           Streamlit UI
  shared/       style, formatting, filter, i18n, runtime context (knows no business logic)
  locales/      translation catalogs, one flat JSON per language (de, en)
  cases/        case list, shared detail-view shell, run, step derivation
    process_views/  per-process detail-view fragments (approval input, outcome text, metric)
  intake/       upload check and storage
  pages/        upload, history, process, audit, architecture, agent configuration
tests/        pytest
docs/         architecture, concept->code mapping, limitations, operator's guide
agent_registry.py    agent configuration table (effective, not just documented)
process_registry.py  processes as configuration: step sequence, target system, fields
config.py     .env configuration
contracts.py  cross-boundary vocabulary: interrupt kind, approval decision, case outcome
demo.py       CLI runner for the five scenarios
```

Model IDs and prices in the documentation are marked with the retrieval
date **2026-07-17** and change quarterly.
