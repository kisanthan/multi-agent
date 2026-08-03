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
