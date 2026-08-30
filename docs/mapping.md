# Mapping: functional concept → code

This document maps the thesis's concept artifacts onto the prototype code
and makes every interpretation decision explicit. It serves as the basis
for the case-study prose (chapter 6).

## Preliminary note: missing diagrams

The six concept diagrams (`uebersicht_gesamt.png`, `mindmap_prozessA/B.png`,
`teil1_agententypen.png`, `teil2_ki_modelle.png`,
`teil3_multiagentensystem.png`) were **not available** during
implementation. The prototype was therefore built from the **agent
configuration table in section 1 of the planning prompt**. Where that table
left room for interpretation, the decisions below are marked as an
*interpretation*. Before use in the thesis, these points should be checked
against the actual diagrams.

## Agents → code

| Component (concept) | Code | Type | Level | Oversight | Model class |
|---|---|---|---|---|---|
| Reader tool | [tools/reader.py](../tools/reader.py) | not an agent | – | deterministic | none |
| Orchestrator agent | `route_document_type` in [graph/nodes/shared.py](../graph/nodes/shared.py) | orchestrator | – | human-on-the-loop | local/small |
| Classification & extraction | [agents/shared/classification.py](../agents/shared/classification.py) | Shared Domain | 2 | human-on-the-loop | vision |
| Reconciliation agent | [agents/payment_confirmation/reconciliation.py](../agents/payment_confirmation/reconciliation.py) | Shared Domain | 1 | human-on-the-loop | none *(det., I1)* |
| Booking agent | [agents/payment_confirmation/booking.py](../agents/payment_confirmation/booking.py) | Shared Domain | 3 | **human-in-the-loop** | frontier |
| Cost-center agent | [agents/incoming_invoice/cost_center.py](../agents/incoming_invoice/cost_center.py) | Shared Domain | 2 | human-on-the-loop | none *(det., I1)* |
| ELO agent (end of process B) | [agents/incoming_invoice/archiving.py](../agents/incoming_invoice/archiving.py) | Shared Domain | 3 | human-on-the-loop | local/small |
| Policy/governance | [governance/policy.py](../governance/policy.py) | policy | – | deterministic | none |
| Audit/monitoring | [governance/audit.py](../governance/audit.py) | audit | – | read-only | none |

The table is stored in code as effective data
([agent_registry.py](../agent_registry.py)) -- the policy reads from it. Changing a
level changes runtime behavior; it is not merely documented.

Reconciliation and booking live under `agents/payment_confirmation/`;
cost-center assignment and archiving under `agents/incoming_invoice/` --
classification stays in `agents/shared/`, and the reader stays in `tools/`
entirely outside `agents/`, because all three are genuinely shared by both
processes. `graph/nodes/` mirrors the same split (see the new
"A/B separation" section in [architecture.md](architecture.md)); this table
lists each agent once, not each file location per layer.

## Diagrams → implementation

- **`uebersicht_gesamt.png` (flow A+B)** → one shared graph
  ([graph/workflow.py](../graph/workflow.py)) with a shared reader,
  orchestrator, classification, and data layer. Two separate graphs would
  have dissolved the claim of *shared* components.
- **`mindmap_prozessA.png`** → nodes `reader → klassifikation → abgleich →
  buchung → Navision`, HITL node `klaerfall` (only on an unknown number /
  amount mismatch). Navision sets the status from open to paid.
- **`mindmap_prozessB.png`** → nodes `reader → klassifikation → kostenstelle
  → (on ambiguity) freigabe_kostenstelle → elo`. **End of process at ELO**
  -- no Navision booking in process B (diagram part 3).
- **`teil1_agententypen.png` (taxonomy)** → [agent_registry.py](../agent_registry.py):
  `AgentType`, `AutonomyLevel`, `OversightMode` as enums.
- **`teil2_ki_modelle.png` (model assignment)** → `ModelClass` per agent
  plus [llm/client.py](../llm/client.py) `choose_profile`: router, payment
  and invoice profile → provider and model.
- **`teil3_multiagentensystem.png` (overall synthesis, AD + governance)** →
  AD check in [tools/reader.py](../tools/reader.py), governance layer in
  `governance/`, layer boundary enforced via test.

## Interpretation decisions

### I1 — Reconciliation and cost-center agent without a language model *(agreed with the user)*

Thesis §7.4: both the number reconciliation (process A) and the
cost-center assignment (process B) are "exact, referential lookups against
structured master data" (translated from the German: *„exakte,
referenzielle Nachschläge auf strukturierte Stammdaten"*). A language model
could contribute nothing there that a database lookup does not already do
exactly and reproducibly -- it could only hallucinate, and at a
financially/booking-relevant point. The prototype therefore implements
both agents **deterministically**
([agents/payment_confirmation/reconciliation.py](../agents/payment_confirmation/reconciliation.py),
[agents/incoming_invoice/cost_center.py](../agents/incoming_invoice/cost_center.py)); the autonomy level and
oversight mode remain valid, the model class is `NO_MODEL`. Extracting the
number or the cost-center reference from the document itself is done by
the respective process-specific extraction agent (which uses a model).

**Usable finding for the thesis:** an agent's role and autonomy level do
not automatically imply model inference. The typology states *which role*
and *which autonomy level* a component has -- whether a language model is
needed for that is a separate decision. Deterministic domain agents
(reconciliation, cost center) therefore stand alongside the already
deterministic cross-cutting components (reader, policy, audit).

**Known divergence from figure 5 (as of the thesis revision of 11.08.2026).**
Figure 5 assigns both agents a model after all -- DeepSeek-V4-Flash to the
reconciliation agent, Claude Sonnet 4.6 / MiniMax M3 to the cost-center
agent -- with the justification that the lookup itself is deterministic
while *the model drives the tool call, checks uniqueness, and escalates
exception cases*. The prototype does neither with a model: the tool call
is an ordinary function call in `graph/nodes/*`, the uniqueness check is
an `if`, and the escalation is a routing edge (`route_cost_center`), so
the model class is `NO_MODEL` and no request is ever sent.

This is a deliberate simplification, not an oversight, and it errs on the
conservative side: the prototype is *more* deterministic than the figure
requires, and every property the thesis claims for these two steps
(exactness, reproducibility, auditability, §7.4) holds a fortiori. What it
does not demonstrate is the model-driven tool-calling path the figure
describes. Anyone comparing the submitted figure 5 against the agent table
in `agent_registry.py` will see "kein Modell" where the figure names one --
which is why it is recorded here rather than left to be discovered. To
close it in the thesis instead, figure 5 would have to read "kein Modell"
for both rows; that was considered during the 11.08.2026 revision and
rejected, because it would have reduced process B to a single agent.

### I2 — Booking agent: always human-in-the-loop (aligned with Thesis §7.4)

Per Thesis §7.4 and table 11, the financially effective booking step is
**human-in-the-loop**: every booking requires a human approval, regardless
of amount. An earlier prototype version used an amount threshold (below it
automatic, above it approval); this was removed because it would have
weakened the continuous oversight the concept requires. Implemented via the
oversight-mode rule in [governance/policy.py](../governance/policy.py).

*(Resolved on the thesis side by the revision of 11.08.2026: figure 6
previously labelled the booking agent "human-on-the-loop" while the text
and table 11 said "human-in-the-loop". The figure was corrected to match
the text and gained an explicit "Buchungsfreigabe — Human-in-the-loop (vor
Ausführung)" node between the booking agent and Navision. That is exactly
the path this prototype takes: `node_booking` requests approval before the
ERP call and only books once a human has decided.)*

### I3 — Autonomy levels "1-2"

Where the table names a range, the policy checks against the **upper
bound** (classification → 2). Rationale: the policy must check against the
highest claimed level, otherwise the barrier would be ineffective.

### I4 — Orchestrator routes without another model call

The document type is already known after the shared router. The
orchestrator then *routes* on it (conditional edge) instead of asking a
second model -- a second call could contradict the first.

### I5 — Cost-center agent: human-on-the-loop, HITL only on a missing reference

Per diagram part 3, the cost-center agent is **human-on-the-loop**: if the
document reference resolves to a unique cost center, the case runs
automatically through to archiving; the four-eyes approval only kicks in
if the reference is missing or unknown (the "assignment unique?" decision
→ no/exception case). This exactly mirrors process A (number present?).
Implemented in [graph/nodes/incoming_invoice.py](../graph/nodes/incoming_invoice.py)
via `route_cost_center`.

*(An earlier prototype version always forced an approval at this point;
the diagram refined the oversight mode to on-the-loop.)*

### I6 — Process B ends at ELO (no Navision booking)

Per diagram part 3, tamper-evident archiving in ELO is the **end of
process B**. A balance-sheet-effective booking as a liability (the earlier
"Navision agent", level 4) no longer happens. Navision (NAV) is now only
addressed in process A (booking agent, status open → paid). The Navision
agent, the `/liability` endpoint, the state field `verbindlichkeit_id`, and
the table `verbindlichkeiten` were removed.

### I7 — Shared data layer: no RAG (aligned with Thesis 6.4)

**Correction:** the thesis (section 6.4, the paragraph on RAG) establishes
that the shared data layer is **deliberately not** implemented as a RAG
system -- for *both* lookups: "the reconciliation in the payment receipt
and the cost-center assignment in the incoming invoice are exact,
referential lookups against structured master data" (translated from the
German original). The thesis sees RAG only as a *complementary* addition,
and at a different point: to support the router and extraction agents
with unusual document layouts, and to enrich the human exception-case
review with contract/policy passages.

The prototype now follows this line for **both** lookups: both the
reconciliation agent and the cost-center agent are deterministic, exact
reference lookups without a language model (see I1). The earlier prototype
version implemented the cost-center assignment as LLM-/keyword-based and
semantic; that was switched to a reference lookup to stay consistent with
the thesis's claim: the invoice carries a cost-center reference (e.g.
`KTR-ITINFRA`), the extraction agent reads it, the cost-center agent looks
it up exactly in the catalog. "Not unique" now means: reference missing or
unknown → exception case.

**Remaining analytical tension (for the thesis):** the process step
"assignment unique?" with an exception-case path now fits cleanly with the
reference lookup (reference present → unique; missing → exception case).
The previously noted tension ("an exact lookup is never ambiguous") is
thereby resolved: the "non-uniqueness" does not lie in a semantic
similarity, but in the absence of the reference on the document.

## Governance enforcement

- **Least Privilege:** the AD check sits *inside* `read_document()`, before
  any file access -- not in the calling node. Evidence:
  `tests/test_reader.py::test_denied_access_never_reads_the_file`.
- **Deterministic governance:** `governance/` imports no LLM client;
  enforced via AST analysis (`tests/test_layer_boundaries.py`).
- **Audit trail:** hash-chained, append-only via DB trigger;
  `verify_chain()` detects change, deletion, and insertion.
