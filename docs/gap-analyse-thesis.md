# Gap analysis: prototype ↔ thesis section 6.4

Comparison of the practical implementation against the prose in
`Masterarbeit.docx`, section **6.4 "Application and analysis of the process
domains"** and the evaluation table (7.2, table 10). As of: 2026-07-21.

Legend: ✅ congruent · ⚠️ divergence/needs clarification · ➕ additional in
the prototype (not in the thesis).

---

## Congruent (no action needed)

| Thesis 6.4 | Prototype | |
|---|---|---|
| Two processes A (payment receipt) / B (incoming invoice), shared intake stretch | one shared graph, shared reader/orchestrator/data layer | ✅ |
| Business processing only by **Shared Domain Agents** | registry: all business agents are Shared Domain | ✅ |
| Classification/extraction agent determines type + reads fields | `agents/classification.py` (type + fields in one pass) | ✅ |
| Orchestrator "without its own full business rights", routing only | routing function, no write access | ✅ |
| Reader tool **not an AI agent**, PDF→Markdown deterministic | `tools/reader.py`, no LLM | ✅ |
| **Process B: unique → straight to ELO; otherwise exception case (four-eyes, HITL)** | `route_cost_center` + `node_cost_center_approval` | ✅ |
| **Process B ends at ELO** (tamper-evident archiving) | `elo → END`, no Navision booking in B | ✅ |
| Process A: reconciliation → booking sets open→paid in Navision | `agents/booking.py` → Navision mock `/booking` | ✅ |
| AD security group at the process entry point (Least Privilege) | AD check *inside* `read_document()` | ✅ |
| Policy checks "deterministically outside the language model" | `governance/policy.py`, enforced via AST test | ✅ |
| Audit "tamper-evident" | hash-chained trail, append-only | ✅ |
| Provider-independent abstraction layer (5.1.5), agent/model swappable | `llm/client.py::choose_model` | ✅ |
| Personal Agents do not occur | none in the system | ✅ |

This session's process-B rework brought the prototype **exactly in line
with the thesis text**: a unique assignment → straight to ELO, otherwise an
exception case; ELO as the end of the process.

---

## Divergences / needs clarification

### G1 -- RAG: my earlier advice was wrong ⚠️ *(fixed in the docs)*

The thesis (6.4) **already and unambiguously** decides the RAG question:
the shared data layer is "deliberately not implemented as a semantic
retrieval system" (translated from the German); **both** lookups
(reconciliation A *and* cost-center assignment B) count as "exact,
referential lookups against structured master data." RAG is only intended
complementarily -- for the extraction agent on difficult layouts and to
enrich the exception-case review.

→ That answers the question "build in RAG?" from the thesis's point of
view: **not into the data layer.** My earlier assessment (RAG would suit
the cost-center assignment) contradicted the thesis; `docs/mapping.md` I7
is corrected. If RAG is built at all, then where the thesis places it
(extraction support / exception-case enrichment), not at the master-data
reconciliation.

### G2 -- Cost-center agent: thesis "exact lookup" vs. prototype "semantic" ⚠️

The thesis describes the cost-center assignment as an **exact referential
lookup** (deterministic). The prototype (at the time of this analysis)
implemented it as **LLM-/keyword-based, semantic**
(`agents/kostenstelle.py`, docstring: "a semantic task that cannot be
formulated as an exact query", translated from the German).

That is a real contradiction. Two paths:

- **(a) Align the prototype with the thesis:** implement the cost center as
  a deterministic lookup via an explicit **cost-center reference** on the
  document (the extraction agent reads the reference, the cost-center
  agent looks it up exactly). That would make the agent -- like the
  reconciliation agent (I1) -- work without its own language model;
  "ambiguity" = reference missing/not unique.
- **(b) Refine the thesis text:** the process's own step "assignment
  unique?" with an exception-case path shows that the assignment has a
  **classification character** -- an exact lookup is never "ambiguous."
  The phrase "exact referential lookup" therefore carries less far for the
  cost center than for the invoice number. One or two sentences in 6.4
  would resolve this (e.g.: cost-center assignment = reference-based, but
  with a classification component when the reference is missing or not
  unique).

**Recommendation:** (b) -- the prototype cleanly reflects reality (the
assignment is a judgment/classification step), and the existence of the
exception-case path gives you the argument. If the supervision requires
strict determinism coherence, (a) is the way; say so and it will be
reworked.

*(Resolution note: option (a) was ultimately implemented -- see D2 in
[abschlussbericht-thesis-angleichung.md](abschlussbericht-thesis-angleichung.md)
and I1/I7 in [mapping.md](mapping.md). The cost-center agent is now a
deterministic reference lookup, consistent with the reconciliation agent.)*

### G3 -- Booking agent: oversight mode contradictory ⚠️

Here the **thesis itself is inconsistent**:

- **Thesis text** (characterization paragraph + table 10, row
  "controllability A"): booking agent "under **human-in-the-loop**"
  (financially effective write access).
- **Thesis figure 5** (`teil3_multiagentensystem.png`): the booking-agent
  tile is labeled **human-on-the-loop**; the HITL point is the "exception-
  case review" (only on a missing number).
- **Prototype:** `HUMAN_ON_THE_LOOP` as the default plus an **amount
  threshold** (`BUCHUNG_SCHWELLE_EUR`: below it automatic, above it HITL) --
  a construct that **does not appear in the thesis at all** (➕).

→ **Two things to decide:**
1. Align text vs. figure in the thesis (booking agent: in-the-loop *or*
   on-the-loop -- consistently).
2. Align the prototype accordingly. If the thesis chooses
   **human-in-the-loop** (as the text suggests, financially effective), the
   booking agent should **always** require an approval; the amount
   threshold would go away or be declared a deliberate prototype extension.
   If **human-on-the-loop** (as the figure), the prototype already fits,
   but the threshold remains a prototype addition.

**Recommendation:** choose **human-in-the-loop** in the thesis for the
financially effective booking step (consistent with "rising autonomy →
tighter oversight"), adjust figure 5 accordingly, and in the prototype
either keep the threshold as an optional, documented extension or switch
to pure HITL.

*(Resolution note: pure HITL was ultimately implemented, with the
threshold removed -- see D1 in
[abschlussbericht-thesis-angleichung.md](abschlussbericht-thesis-angleichung.md).)*

### G4 -- Dynamic cloud escalation of extraction is missing ⚠️ *(small)*

Thesis: extraction "primarily on-premise ... only escalate to the cloud on
**difficult layouts**" (translated from the German) -- i.e. a *dynamic*
escalation. Prototype: **static** model assignment (classification agent =
vision class → always cloud in hybrid mode). The described "on-prem first,
escalate on difficulty" mechanism is not implemented.

→ Optionally retrofittable: local VLM first, escalate to the cloud on a
low confidence/validation signal (the R1 retry already exists!). The
escalation path docks well onto the existing validation layer
(`llm/extraction.py`). Not necessary for the core demo, but it would make
sub-question 2 more demonstrable.

### G5 -- Audit fields not named 1:1 as in the text ⚠️ *(small)*

The thesis explicitly names the fields to be logged: **requester, agent,
source, tool call, policy decision, outcome** (translated from the
German). Prototype audit columns (at the time of this analysis): `akteur`
(=requester ✅), `agent` ✅, `aktion` (~tool call), `entscheidung` (=policy
decision ✅), `begruendung`, `payload` (contains source/file + outcome).

→ "Source" and "outcome" were stuck in the `payload`, not as their own
columns. Functionally complete, but for a **1:1 proof against the thesis's
exact wording** (the "traceability" criterion, table 10), it would be
cleaner to carry them as explicit fields. A small change to
`governance/audit.py` + the schema.

*(Resolution note: implemented -- `case_id`, `source`, and `outcome` are
now dedicated, hashed columns in the `audit` table. See
[abschlussbericht-thesis-angleichung.md](abschlussbericht-thesis-angleichung.md)
O2 and [grenzen.md](grenzen.md) L9.)*

---

## Conclusion

The prototype covers thesis section 6.4 **completely in structure**; the
most recent process-B rework eliminated the last major divergence. Still
open:

- **G1/G2 (substantively important):** the RAG question is decided by the
  thesis (no RAG in the data layer) -- my earlier advice was wrong and has
  been corrected. The cost-center agent was more semantic in the prototype
  than the thesis describes; that is resolvable via a text refinement
  (recommended) or a prototype change (both meanwhile implemented in code,
  see the resolution notes above).
- **G3 (important, concerns the thesis itself):** booking agent -- text
  (HITL) and figure 5 (on-the-loop) contradict each other; this belongs
  unified in the thesis, with the prototype following.
- **G4/G5 (small, optional):** dynamic cloud escalation and explicit audit
  fields -- retrofittable, not required for the core claims.
