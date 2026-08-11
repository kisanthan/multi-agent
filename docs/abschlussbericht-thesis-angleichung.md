# Final report: aligning the prototype with the master's thesis

**Date:** 2026-07-27 · **Branch:** `thesis-angleichung` · **Baseline commit:** `db3ba8a`
**Reference:** `Masterarbeit.docx` (submission-ready version, 10 chapters, four sub-questions), section §7.4 "Application and analysis of the process domains"

---

## 1. Analyzed starting state

**Master's thesis.** Submission-ready since 2026-07-27 (completion note +
review in the thesis folder). DSR structure, four sub-questions, case study
= chapter 7, §7.4 with a preceding suitability step. Central point: the
thesis deliberately frames the prototype **as a conceptual artifact /
future work** -- §8 evaluates qualitatively, "since the artifact ... was
not prototypically implemented" (translated from the German); §9.4 names
the prototypical implementation as a follow-up step.

**Prototype.** Runs, LangGraph 1.2, both processes, governance core,
hash-chained audit trail, mocks (Navision, ELO), 68 tests green before this
session. Already aligned with the concept diagram (part 3) via the
process-B rework before this session.

## 2. Errors and contradictions found

- **My earlier RAG advice was wrong.** I had advised the user that RAG
  would suit the cost-center assignment. The thesis (§7.4) **explicitly**
  rejects RAG for the data layer and gives a clean rationale. → corrected.
- **Contradiction within the thesis itself (not fixed, documented):** the
  booking agent is "human-in-the-loop" in the **text** and in table 11, but
  "human-on-the-loop" in **figure 6**; the evaluation table simultaneously
  names "manual intervention only in exceptional cases" for process A
  (translated from the German). This is for the thesis itself to resolve
  (see [gap-analyse-thesis.md](gap-analyse-thesis.md) G3).
- **No factual errors found in the §7.4 text against the concept** -- the
  section is consistent and (after the process-B rework) congruent with
  the code.

## 3. Discrepancies between the master's thesis and the source code, and their resolution

The user decided: **do not touch the thesis** (submission-ready), **align
the code with the §7.4 specification**.

| # | Thesis §7.4 | Code (before) | Resolution (code now) |
|---|---|---|---|
| D1 | Booking agent human-in-the-loop, financially effective | on-the-loop + amount threshold | **always HITL**, threshold removed |
| D2 | Cost-center assignment "exact referential lookup" | LLM-/keyword-based, semantic | **deterministic reference lookup**, no model |
| — | Reconciliation = exact lookup | registry `LOCAL_SMALL` (legacy inconsistency) | model class `NO_MODEL` (consistent with D2) |

## 4. Requirements derived from the case study (§7.4)

1. Two processes A/B, shared intake stretch, shared data layer. ✅
2. Shared Domain Agents; orchestrator without full business rights; reader
   not an AI agent, AD security group at the entry point. ✅
3. Process A: reconciliation → booking (Navision, open→paid), **booking
   under human-in-the-loop**. ✅ (D1)
4. Process B: cost center → on a unique assignment, straight to ELO,
   otherwise exception case (four-eyes, HITL); **ELO = end of process**, no
   Navision booking. ✅
5. **Both lookups (reconciliation, cost center) are exact, referential,
   deterministic, outside the language model; no RAG in the data layer.**
   ✅ (D2, I1, I7)
6. Policy deterministic outside the LLM; audit logs requester, agent,
   source, tool call, policy decision, outcome, tamper-evident. ✅
   (partially, see open point O2)
7. Risk-based model assignment, provider-independent abstraction layer. ✅

## 5. Changes made to the source code

**D1 -- Booking agent always human-in-the-loop**
- `registry.py`: `buchung.oversight = HUMAN_IN_THE_LOOP`.
- `governance/policy.py`: amount-threshold rule removed; booking runs
  through the oversight-mode rule → always `APPROVAL_NEEDED`.
- `config.py`, `.env.example`, `demo.py`, `ui/app.py`: `buchung_schwelle_eur`
  removed.
- `agents/booking.py`: docstrings updated.

**D2 -- Cost center as a deterministic reference lookup**
- `data/schema.sql`: column `cost_centers.reference` (unique).
- `data/generate.py`: reference codes per cost center (`KTR-…`); invoices
  carry a cost-center reference; the exception-case document
  (`B_rechnung_ohne_referenz.pdf`) carries none.
- `agents/schemas.py`: field `Classification.cost_center_reference`;
  `Kostenstellenvorschlag` (LLM) removed.
- `agents/cost_center.py`: rewritten as a deterministic lookup (`assign`),
  no model call.
- `registry.py`: `kostenstelle.model_class = NO_MODEL`; likewise `abgleich`
  (consistency).
- `llm/client.py`: clearer error message for model-less components.
- `graph/state.py`, `graph/workflow.py`: `cost_center_reference` in the
  state; `node_cost_center` uses the lookup; the approval node offers the
  catalog.
- `demo.py`, `ui/app.py`: approval selection from the catalog instead of
  LLM alternatives.

**Tests**
- `tests/test_policy.py`: threshold tests → "booking always needs approval".
- `tests/test_llm.py`: reconciliation/cost-center as model-less components.
- `tests/test_scenarios.py`: scenario 1 (booking approval HITL), scenario 3
  (reference unique → auto), scenario 4 (reference missing → exception
  case).

> **Note (later rework):** the file paths in this section reflect the
> state at the time of this report. A subsequent restructuring split
> `agents/` and `graph/workflow.py` by process; the same modules now live
> at `agents/payment_confirmation/booking.py`,
> `agents/incoming_invoice/cost_center.py`, and
> `graph/nodes/{payment_confirmation,incoming_invoice}.py`. See the "A/B
> separation" section in [architektur.md](architektur.md) for the current
> layout.

## 6. Revised sections of the master's thesis

**None.** At the user's request, and because of the submission readiness,
`Masterarbeit.docx` remains unchanged. All alignment happened in the code.
The prototype documentation was updated: `docs/mapping.md` (I1, I2, I5,
I7), `docs/architektur.md`, `README.md`, `docs/gap-analyse-thesis.md`.

## 7. Remaining open points

- **O1 (thesis):** the booking-agent contradiction (text/table "HITL" vs.
  fig. 6 "on-the-loop"; the "exceptional case" wording). The code follows
  the text/table (always HITL). The thesis should bring fig. 6 and the
  automation-level row in line with the text. **Author's decision.**
- **O2 (small, code):** the audit fields "source" and "outcome" were stuck
  in the `payload`, not as their own columns. For a 1:1 proof against the
  thesis's exact wording (traceability criterion), they are worth carrying
  as explicit fields. *(Resolved in the English-translation pass: `case_id`,
  `source`, and `outcome` are now their own columns in the `audit` table --
  see docs/grenzen.md L9.)*
- **O3 (small):** the dynamic cloud escalation of extraction "for difficult
  layouts" (thesis) is not implemented (static model assignment).
- **O4 (operations):** a live run of scenarios 1-4 against Ollama is still
  pending (model setup on the user's side). Verification currently happens
  with a mocked model.

## 8. Risks, assumptions, recommendations

**Assumptions.**
- The cost-center reference is an explicit document code (`KTR-…`) that the
  extraction agent reads. This is the operational interpretation of "exact
  referential lookup"; the thesis names no concrete reference format.
- "Booking always HITL" follows the thesis **text**; the diverging figure 6
  is treated as a contradiction internal to the thesis for the author to
  resolve.

**Risks.**
- If O1 is resolved in the thesis in favor of "on-the-loop", D1 would need
  to be reverted in the code (small, reversible via the branch).
- The deterministic cost-center lookup assumes real documents carry a
  machine-readable reference. In practice that is not always the case --
  then the exception case kicks in more often. That is factually correct
  and should be stated in `docs/grenzen.md` as an operational assumption
  (added).

**Recommendations.**
- Resolve O1 in the thesis (recommendation: human-in-the-loop throughout
  for the financially effective booking, adjust fig. 6, relate the
  "exceptional case" wording to the exception case).
- The prototype stays cleanly outside the submitted core (as the review
  also states in §7). For a later empirical extension, the docking points
  named by the review (§8.2/table 11 "empirically open" cells, §9.4) are
  the right places -- **only after** submission.

## 9. Later rework: declared contracts and a readable per-process flow (2026-08-03)

**Date:** 2026-08-03 · **Branch:** `rafactoring`

A separate follow-up request asked for the project to be optimized for
understandability -- explicitly naming Clean Architecture, or something
better, as the target. Measurement first: the dependency rule Clean
Architecture is usually invoked for was already satisfied (`agents/`,
`governance/`, `tools/`, `llm/` had zero framework imports and zero direct
`sqlite3.connect` calls), so a directory rewrite into
domain/application/infrastructure would have solved a problem that did not
exist, at the cost of invalidating the layer table and both architecture
tests this report and `docs/architektur.md` already describe. The actual
measured problem was narrower: routing labels and the approval
request/response shape existed only as repeated string literals with no
declared contract, and no single file described either process from start
to finish in execution order.

**What changed (does not touch anything in sections 1-8 above):**
- `contracts.py` (new) declares `InterruptKind`, `ApprovalDecision`,
  `CaseOutcome`, and the `ApprovalRequest`/`ApprovalResponse` dataclasses --
  the vocabulary that crosses a process boundary or the LangGraph
  checkpoint, previously only ever a matching pair of string literals at
  the producing and consuming end. Both graph node modules
  (`graph/nodes/payment_confirmation.py`, `graph/nodes/incoming_invoice.py`)
  and both producer sites (`ui/cases/detail.py`, `demo.py`) now build and
  read these types instead of raw dicts.
- `graph/workflow.py`'s `build_graph()` is reordered into the three
  sections a case actually travels through (shared intake, process A,
  process B), each routing label commented at the point it is consumed --
  a pure reordering, verified byte-identical in `draw_mermaid()` output
  before and after.
- `process_registry.ProcessStep` gained an optional `graph_node` field for
  the one step (`freigabe`) whose run-log name and LangGraph node name
  differ; this also corrected a docstring that had been wrong since the
  process-separation rework (the later note under §5 above).
- `tests/test_flow.py` (new) pins both processes' edges and every step's
  node mapping against the *compiled graph itself*
  (`get_graph().edges`/`.nodes`), not a hand-maintained description of it,
  and checks the generated `docs/flow.mmd` diagram (embedded a second time
  in `docs/architektur.md`) for drift the same way.
- One deliberate, documented change to a persisted value: process B's
  cost-center approval now logs `kostenstelle_verworfen` on rejection,
  where it previously logged `kostenstelle_freigegeben` even when a human
  had just rejected the case. Mirrors process A, which already used two
  distinct action names for its own approve/reject branches.
  `tests/test_scenarios.py`'s only assertion on this action name checks
  solely the approved path and needed no change.
- Eight small documentation-drift corrections: stale file paths (in
  `registry.py`, `docs/gap-analyse-thesis.md`), an inaccurate wiring claim
  in `README.md`, the ASCII diagram in `docs/architektur.md` repaired to
  include three edges it was missing, a three-vocabulary "outcome"
  comparison table, `tests/test_process_separation.py` cited where it
  previously was not, and a documented -- not fixed -- coincidence in
  `ui/pages/audit.py` now pinned by `tests/test_process_registry.py`.

**Verification.** Full suite green after every step (184 tests at the
start of this rework, i.e. at the end of the process-separation rework
noted under §5; 195 once `contracts.py` landed; 201 at the end); `demo.py
--szenario 5` and `--liste` re-run after the producer-side change;
`draw_mermaid()` diffed byte-for-byte before/after the graph reordering; a
`git diff` review confirming no German string *value* changed anywhere
except the one `kostenstelle_verworfen` addition documented above.

**Not verified live in this environment:** a full browser walkthrough of a
cost-center-approval case (scenario 4) end-to-end, the one path that
exercises `ApprovalRequest`, `ApprovalResponse`, `InterruptKind`, and
`CaseOutcome` together. Blocked by two independent, pre-existing issues
unrelated to this rework, both surfaced while attempting it: the local
Ollama vision model failed to load (`unknown model architecture:
"mllama"`), and -- separately -- a live gap where a *total* classification
failure (nothing extracted at all), if its resulting exception case is
then approved, currently crashes the booking step (`KeyError:
'amount_eur'`) instead of ending the case gracefully. Neither is caused by
this rework; the second has been flagged separately as its own follow-up,
not fixed here, since it needs a product decision (what should happen
instead) rather than a code fix.

**Nothing in this section has been committed.** As with the rest of this
branch, that is left to the user's explicit instruction.

## 10. Bug fixes and a structural-clarity pass (2026-08-05)

**Date:** 2026-08-05 · **Branch:** `rafactoring`

Two follow-up requests: fix the issues surfaced at the end of §9, then
make the folder structure faster to grasp on first read.

**Bug fixes.**
- **Silent config drift.** The live `.env` file still used the pre-English-
  translation German variable names (`OLLAMA_MODELL_VISION`,
  `MODELL_MODUS`, ...), while `config.py`'s `Settings` fields had already
  been renamed to English during the translation pass (§ Phase 1) and
  `.env.example` updated to match. `pydantic-settings` matched neither, so
  every renamed setting silently fell back to its Python default --
  invisible everywhere the default happened to coincide with the intended
  value, and the exact cause of `ModelClass.VISION` quietly resolving to
  the broken `llama3.2-vision:11b` instead of the user's already-pulled,
  working `qwen2.5vl:7b`. Fixed by migrating `.env` to the current English
  names (values preserved); every other stale reference to the old names
  in user-facing messages (`llm/client.py`, `llm/preflight.py`, `demo.py`,
  `README.md`) corrected alongside it.
- **`node_exception_case` crash on an unbookable approval.** When
  classification fails totally, or succeeds but never resolves a number,
  and the resulting exception case is approved anyway, `node_booking`
  used to crash (`KeyError: 'amount_eur'` or an avoidable round trip to a
  target system that could only refuse). `node_exception_case`
  (`graph/nodes/payment_confirmation.py`) now recognizes "approved, but
  nothing bookable behind it" and ends the case the same way an outright
  rejection does, with an honest audit reason. Two regression tests in
  `tests/test_scenarios.py`, each verified to fail on the pre-fix code and
  pass on the fix.
- **Target-system audit gap, precisely scoped.** `booking.py`/`archiving.py`
  now audit a transport-level failure (Navision/ELO unreachable) from the
  caller's side -- previously invisible in the audit trail, since an
  unreachable target system's own handler never runs and so can never log
  itself. A first pass also added logging for the *reached* outcomes
  (accepted/explicitly refused), but `mocks/navision.py` and
  `mocks/elo.py` already log those themselves (same database access a
  real integration would not have) -- that duplicate logging was removed
  before landing. Two regression tests, same fail-before/pass-after
  verification.

**Structural-clarity pass** (folder/file renames, no behavior change):
- `registry.py` → `agent_registry.py`, so it reads as a matched pair with
  `process_registry.py` instead of a near-duplicate name.
- `agents/classification.py` and `agents/schemas.py` → `agents/shared/`,
  so the shared/A/B three-way split is visible in the directory tree
  itself, not only in prose.
- `ui/upload/` → `ui/intake/`, removing the path-level collision with
  `ui/pages/upload.py` (the split itself -- testable business logic vs.
  the Streamlit page -- was already correct and unchanged).
- `ui/cases/processes/` → `ui/cases/process_views/`, matching the
  `ProcessView` dataclass name the package already exports.
- All seven previously-empty top-level `__init__.py` files
  (`agents/`, `governance/`, `graph/`, `llm/`, `mocks/`, `tools/`, `data/`)
  got a short orientation docstring, extending a pattern that already
  existed in `graph/nodes/__init__.py` and `agents/payment_confirmation/
  __init__.py` but had not been applied uniformly.
- New `tests/test_structure.py` pins the key paths `README.md`'s
  project-structure section names against the filesystem, so a future
  rename that forgets the docs fails the suite instead of drifting --
  exactly what happened twice already in this report (§9's drift
  corrections, and the stale `MODELL_MODUS`/`registry.py` messages found
  while fixing the config bug above).

**Verification.** Full suite green after every step (206 at the end, up
from 201 at the end of §9); each of the four regression tests (crash
fixes + audit gap) individually verified to fail against the pre-fix code
and pass against the fix, not merely "green once written"; a live re-run
of the total-extraction-failure crash against a real (not mocked) model
timeout, confirming the fix holds outside the test suite too.

**Nothing in this section has been committed.** Same standing instruction
as throughout this branch.
