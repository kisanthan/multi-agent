# Limitations of the prototype

The prototype is a **demonstration and feasibility artifact** (Design
Science Research per Hevner et al. 2004), not production-ready. These
limitations belong in the case-study text (chapter 6) and in the thesis's
limitations section.

## What the prototype demonstrates -- and what it does not

**Demonstrated:** the *architecture* is feasible. Role-/risk-based agent
configuration, human-in-the-loop at risk points, Least Privilege,
tamper-evident audit trail, and deterministic governance outside the
language model all work together in a running system.

**Not demonstrated:** *extraction quality* on real data. All documents are
synthetic, natively generated (not scanned), and structurally clean. Real
incoming invoices are more heterogeneous (scans, foreign languages,
inconsistent layouts, OCR errors). The prototype says nothing about the hit
rate of classification/extraction under real-world conditions. This
distinction is central and should be clearly stated in chapter 6.

## Concrete limitations

### L1 -- Synthetic data
Generated with a fixed seed (`data/generate.py`). Incidents (unknown
number, duplicate, implausible amount, ambiguous cost center, unauthorized
submitter) are deliberately constructed, not empirically observed. The
cost-center assignment rules are simplified keyword lists.

### L2 -- Schema adherence of local models (risk R1)
Local models do not reliably honor a supplied JSON schema; for Ollama this
is an open, documented bug
([ollama/ollama#15540](https://github.com/ollama/ollama/issues/15540), as
of April 2026), affecting Gemma 4 26B and Qwen 3 9B, among others.

The prototype treats this **not as a fixed problem, but as a caught one**:
`llm/extraction.py` validates every model response against the Pydantic
schema, retries exactly once with the concrete error on a violation, and
then escalates into the HITL queue instead of guessing. A model failure
thereby becomes an approval case, not a silent data error. This is itself
an architectural argument of the thesis -- but it remains a compensation,
not a guarantee of model quality.

### L3 -- Mocked target systems
Navision (Dynamics NAV) and ELO are FastAPI mocks. They plausibly replicate
the interfaces (including precondition checks and rejection), but not the
business logic, performance, or failure modes of the real systems. The
AD/Entra connection is a SQLite table, not a real directory; there is no
real authentication -- the "signed-in user" is a selection in the
prototype.

### L3b -- Cost-center reference as an operational assumption
The cost-center agent is an exact referential lookup (Thesis §7.4): it
assumes the document carries a machine-readable cost-center reference (in
the prototype a code `KTR-…` that the extraction agent reads). Real
incoming invoices do not always carry such a reference explicitly -- then
the exception case (human assignment) correctly kicks in more often. The
prototype demonstrates the deterministic path; the frequency of the
exception case on real documents is empirically open.

### L4 -- Governance scope
The policy engine covers the rules named in the functional concept (RBAC,
autonomy levels, amount thresholds, four-eyes principle). It is not a
complete ABAC/Zero-Trust system; just-in-time privilege grants and Zero
Standing Privilege are conceptually intended but not implemented.

### L5 -- Audit-trail protection
The hash chaining reliably detects subsequent tampering (`verify_chain()`),
and DB triggers prevent UPDATE/DELETE through the application. An attacker
with direct write access to the SQLite file could not *forge* the chain
unnoticed, but could *rebuild* the entire table. Real tamper-proofing would
require external anchoring (e.g., periodically publishing the head hash,
WORM storage). For a demonstration artifact, the chaining is sufficient and
the proof is delivered.

### L6 -- No concurrency / no multi-user operation
SQLite in WAL mode, designed for one case at a time. Parallel runs against
the same DB are not safeguarded.

### L7 -- Model versions and prices
All model IDs (`claude-opus-4-8`, `claude-haiku-4-5`, `qwen3:8b`,
`llama3.2-vision:11b`) and prices should be read as of the retrieval date
**2026-07-17** and change quarterly.

### L8 -- The UI runs cases in a blocking manner
The Streamlit UI runs a case synchronously within the starting browser
tab's request (`app.stream()` with live progress). With a local model this
takes one to three minutes, during which this tab is occupied. A
production system would have a job queue (workers) here. For the
demonstration, the blocking variant is deliberately chosen: it needs no
concurrency and makes every node visible the moment it runs. Approvals from
a second session are unaffected, because the case state lives in the
LangGraph checkpoint, not in the browser.

### L9 -- Extending the audit trail forces a chain rebuild
Since the UI rework, the trail carries the fields `case_id`, `source`, and
`outcome` as their own columns; they feed into the hash so they are just as
tamper-evident as the rest of the entry (this also closes open point O2
from
[abschlussbericht-thesis-angleichung.md](abschlussbericht-thesis-angleichung.md)).

The flip side is more fundamental and instructive for the thesis: **a
hash-chained table cannot be schema-migrated.** Existing entries were
hashed without the new fields; including them in the hash material would
break the chain for every legacy entry. In the prototype this is
consequence-free -- all data is synthetic, and `python -m data.generate`
rebuilds it from scratch. A production system would instead need a
versioned chain: the old chain is closed off and its head hash anchored as
the genesis of the new chain, with a version marker per entry. The
prototype does not implement this.

### L10 -- Four-eyes principle only partially enforced
`governance/policy.py` checks membership in `SG-CHG-Freigabe`, but not
whether the approver and the submitter are the same person. The UI visibly
flags it when both are identical; it is not technically prevented.
Enforcing it would be an extension of the policy (with its own tests) and
is deliberately not part of the UI rework.

## Environment-related notes (this machine)

- Runs on Python 3.14; all dependencies have native wheels. `uv` could not
  be installed due to broken Homebrew permissions -- venv + a pinned
  `requirements.txt` satisfy reproducibility just as well.
- The Faker import is unusually slow on this (heavily filled) filesystem
  (~40s). That is why only `data/generate.py` imports Faker; the demo and
  tests use the paths from `config.py` and stay fast. Test data is
  generated once via `python -m data.generate`.
