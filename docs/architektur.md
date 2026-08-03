# Prototype architecture

## Overview

The prototype implements a multi-agent system for two of CHG-MERIDIAN's
internal financial processes. Both processes run through **one shared
LangGraph graph** with shared components (reader, orchestrator,
classification, data layer). Processing is separated into layers whose
boundaries are enforced in code.

```
Intake (PDF + submitter UPN)
        │
        ▼
   [Reader tool]  ── AD check (Least Privilege) ──► denied → end + audit
        │  PDF → Markdown (deterministic, not an AI agent)
        ▼
   [Classification & extraction]  ── LLM, validated, R1 escalation
        │
        ▼
   [Orchestrator]  ── conditional edge on document type
        ├──────────────► Process A                └──────────────► Process B
        │  [Reconciliation] (level 1, deterministic)  [Cost center] (level 2, deterministic)
        │      │ Number present?                          │ Reference unique?
        │      │   no → exception case (HITL)              │   no → exception case/approval (HITL)
        │      ▼                                           ▼
        │  [Booking] (level 3)                        [ELO] (level 3)
        │      │ Booking approval (HITL, always)            │
        │      ▼                                           ▼
        │   Navision /booking (open→paid)             ELO /archive  ── end of process
        │
        ▼
   Cross-cutting: [Policy] (deterministic) · [Audit] (hash-chained, read-only)
```

> **Process B ends at ELO** (diagram part 3): tamper-evident archiving is
> the end of the process, there is no Navision booking in process B.
> Navision is only addressed in process A. Cost center and ELO are
> human-on-the-loop -- the four-eyes approval only kicks in when the
> cost-center reference is missing.
>
> **Two deterministic domain agents:** reconciliation (process A, invoice
> number) and cost center (process B, cost-center reference) are exact
> referential lookups without a language model (Thesis §7.4). Extracting
> the number or reference itself is done by the classification agent (with
> a model).
>
> **Booking agent always human-in-the-loop:** the financially effective
> booking step (process A) requires a human approval for every booking --
> no amount threshold (Thesis §7.4, table 11).

## Layers and their boundaries

| Layer | Directory | LLM? | Boundary |
|---|---|---|---|
| Configuration | `registry.py`, `config.py` | no | read by governance |
| Governance | `governance/` | **no, enforced** | imports no higher layer, no LLM |
| Tools | `tools/`, `llm/` | LLM encapsulated | AD check as entry condition |
| Agents | `agents/` | some | call governance + LLM + mocks |
| Orchestration | `graph/` | no | wires up agents, sets HITL interrupts |
| Target systems | `mocks/` | no | check their own preconditions |

The most important boundary is that of the **governance layer**:
`governance/policy.py`, `ad.py`, and `audit.py` import no LLM client and
nothing from `agents/`. This is not a style principle but the thesis's
central technical claim, and it is enforced via an AST test
(`tests/test_layer_boundaries.py`). The practical evidence: every governance
decision is deterministic and reproducibly verifiable with a unit test --
with a language model, it would not be.

## Why LangGraph

The graph-based approach with explicit state and a checkpointer maps three
of the thesis's requirements directly:

- **Human-in-the-loop:** `interrupt()` pauses the case at a risk point; the
  checkpointer persists the state, and a human later resumes it via
  `Command(resume=...)`. No HITL without a checkpointer -- the checkpointer
  is therefore not optional (`graph/workflow.py::compile_graph`).
- **Risk-based approval points:** modeled as conditional edges whose
  condition comes from the policy (amount threshold) or from the
  registry's oversight mode (four-eyes principle).
- **Audit trail:** every node writes hash-chained into the trail; the graph
  state keeps a run log for the UI and CLI.

Stack validation (as of 2026-07-17): LangGraph 1.2.9 confirmed; PyMuPDF4LLM
instead of Docling as the default, because the synthetic PDFs are native
and Docling would load 1-2 GB of model weights for no added value (Docling
remains selectable via `READER_PARSER=docling`). Details in
[mapping.md](mapping.md).

## Model provisioning

The model choice follows from two inputs: an agent's **risk class**
(`registry.py`, `ModelClass`) and the **deployment mode** (`.env`,
`MODELL_MODUS`). `llm/client.py::choose_model` combines both:

| Mode | reading/uncritical roles | risk-bearing roles |
|---|---|---|
| `lokal` | Ollama | Ollama |
| `hybrid` | Ollama (data sovereignty) | Anthropic (frontier) |
| `cloud` | Anthropic | Anthropic |

No agent knows its provider -- that is the point of the abstraction and the
technical basis for the thesis's sub-question 2 (cloud vs. open-source by
risk class). The prototype loads no models itself; it connects to an Ollama
instance (`OLLAMA_BASE_URL`) whose models are provisioned outside it.
`demo.py --check` checks the provisioning.

## Data flow and persistence

A shared SQLite database (`data/stammdaten.db`) holds master data, the AD
mock, target-system state, and the audit trail -- deliberately a single
file, because the thesis argues from a *shared* data layer. The LangGraph
checkpointer uses a separate file (`data/checkpoints.sqlite`).

## Model IDs (as of 2026-07-17, change quarterly)

| Role | local (Ollama) | Cloud (Anthropic) | Cloud price (in/out per 1M) |
|---|---|---|---|
| reading/small | `qwen3:8b` | `claude-haiku-4-5` | $1 / $5 |
| classification (vision) | `llama3.2-vision:11b` | `claude-opus-4-8` | $5 / $25 |
| critical writing | — | `claude-opus-4-8` | $5 / $25 |
