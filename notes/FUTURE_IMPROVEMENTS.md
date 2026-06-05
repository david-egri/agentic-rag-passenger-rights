# Future improvements — ready-to-file GitHub issues

A forward-looking backlog for the prototype, distilled from the review pass and the evaluation
baseline (see `notes/EVAL_RESULTS.md` for the numbers these items target) and cross-checked
against the current code — so this lists only **genuinely-open** work and **documented,
by-design limitations**, not anything already shipped.

**How to use this file.** Each `##` section below is one issue: the heading text is the issue
title, the **Labels** line lists the labels to apply in the GitHub UI, and everything else is
the issue body. Copy a block into *New issue* and post.

### Label legend (create these once under *Issues → Labels*)
- **Type:** `enhancement`, `bug`, `refactor`, `performance`, `discussion`
- **Area:** `area:intake`, `area:agent-graph`, `area:rag`, `area:corpus`, `area:calculator`, `area:eval`
- **Priority:** `priority:high`, `priority:medium`, `priority:low`
- **Status:** `needs-investigation`, `by-design`

---

## Move structured extraction to `with_structured_output` + Pydantic schemas

**Labels:** `enhancement`, `area:intake`, `priority:high` · **Effort:** Medium

### Context
`intake`, `planner`, and `eligibility` hand-parse the model's JSON via a manual fence-stripping
helper (`_parse_json` in `src/graph.py`); `src/llm.py` exposes only a bare `get_llm()`.

### Problem
The evaluation's weakest dimension is **routing (~71%)**: the intake model pulls a query toward
"compensation" whenever it mentions a disruption *and* a money/refund word (`"refund"`,
`"how much"`). Free-form JSON also risks parse failures.

### Proposed change
Move structured extraction onto the `langchain-ollama` `with_structured_output` formalism,
backed by predefined Pydantic schemas, centralized in `src/llm.py` with a clear per-node naming
convention. Schema-constrained output replaces hand-parsed JSON.

### Why it matters
Forcing the model to fill fixed slots rather than reply free-form is the most reliable accuracy
fix — models are far better at "ticking boxes" than writing freely. This is the highest-value
lever and a prerequisite that makes the two-blind-spots and delay-robustness work land more
cleanly.

### Acceptance criteria
- [ ] `intake`, `planner`, `eligibility` use `with_structured_output` + Pydantic schemas via `src/llm.py`
- [ ] `_parse_json` removed from `src/graph.py` (or reduced to a fallback only)
- [ ] Functional eval re-run; routing score recorded vs. the ~71% baseline (target: improvement, no regressions)

### References
- `src/graph.py` (`_parse_json`, `intake`, `planner`, `eligibility`)
- `src/llm.py` (`get_llm`)
- `notes/EVAL_RESULTS.md` §1 (F-ROUTING)

---

## Fix two known classification blind spots (ATC delays, EU route-scope asymmetry)

**Labels:** `bug`, `area:intake`, `priority:high` · **Effort:** Small–Medium

### Context
Two failures are documented and already pinned by the eval set, so progress is measurable.

### Problem
- **ATC delays wrongly treated as compensable.** Air-traffic-control disruptions are outside the
  airline's control (extraordinary → no compensation), but the model sometimes awards it.
- **EU route-scope asymmetry.** A non-EU → EU flight on a **non-EU** carrier is *not* covered;
  the model fumbles "am I even covered?" phrasings (it currently misroutes these to `mixed`).

### Proposed change
Add both as explicit worked examples in the intake/eligibility prompts — the same way
weather = no compensation but an airline's **own-staff strike** = compensation is already
taught. (Related: structured-output intake plausibly helps the extraction half.)

### Why it matters
These are real correctness gaps in the core domain logic, not edge cases, and the eval already
catches them — so a fix is directly verifiable.

### Acceptance criteria
- [ ] ATC case: routes/grades to *not compensable* with the correct rationale
- [ ] Scope-asymmetry case: routes to `rights_info` (not `mixed`/`fallback`) and answers coverage correctly
- [ ] Both move from the eval's "known-fails" bucket to passing

### References
- `notes/EVAL_RESULTS.md` §1 (F-ROUTING, F-SCOPE-FAILMODE)
- `src/graph.py` (`intake`, `eligibility` prompts)
- _Related:_ "Move structured extraction to `with_structured_output`"

---

## Harden delay / cancellation disruption-type extraction

**Labels:** `bug`, `needs-investigation`, `area:intake`, `priority:medium` · **Effort:** Medium

### Context
The calculator's delay table is correct in isolation (`src/calculator.py`: delay →
`threshold_met = delay_hours >= 3`; cancellation / denied boarding → `True`). The suspected
risk is **upstream** in extraction.

### Problem
How intake extracts `disruption_type` + `delay_hours` may not be robust for **delay-only**
cases, and **cancellation carve-outs** (Art. 5(1)(c): no compensation if notified > 14 days, or
with timely re-routing) may get conflated.

### Proposed change
Audit delay-only cases (at / under / over 3 h) and cancellation-with-notice cases; turn whatever
surfaces into new eval cases, then fix the extraction. (Structured-output intake likely helps
the extraction half.)

### Why it matters
Misclassifying the disruption type or missing a carve-out produces a wrong amount — the one
output users care about most.

### Acceptance criteria
- [ ] New eval cases: delay-only at/under/over 3 h, cancellation with > 14 days notice, cancellation with timely re-routing
- [ ] Each yields the correct gated amount (incl. €0 where carve-outs apply)

### References
- `src/calculator.py` (delay/threshold logic)
- `src/graph.py` (`intake` extraction)

---

## Skip the RAG subgraph for pure `compensation_calc` queries

**Labels:** `performance`, `area:agent-graph`, `priority:high` · **Effort:** Medium

### Context
`src/graph.py` routes `compensation_calc` to a `["rag", "calculator"]` fan-out, so the RAG
subgraph runs even when the answer is purely an amount. The load test shows `rag` is **~70% of
per-query latency**.

### Problem
For a *pure* `compensation_calc` query the amount is deterministic (calculator), eligibility is
usually the no-cause deterministic path, and citations are optional — so the RAG call is mostly
wasted time.

### Proposed change
Make the RAG branch **conditional**: skip it for pure `compensation_calc`, keep it for
`rights_info` and `mixed`. Touches the router branch logic (`_route_from_router`), the
eligibility branch's doc dependency, and calc-only citation expectations.

### Why it matters
Projected impact: calc queries drop from **~18 s to ~4–5 s** — a large share of realistic
traffic — with no correctness cost.

### Acceptance criteria
- [ ] Pure `compensation_calc` queries no longer invoke the RAG subgraph
- [ ] `rights_info` / `mixed` behaviour unchanged
- [ ] Load test re-run; calc-query latency recorded vs. the ~18 s baseline

### References
- `src/graph.py` (`_route_from_router`, the `compensation_calc` fan-out at the `["rag", "calculator"]` return)
- `notes/EVAL_RESULTS.md` §2 (lever B)

---

## Add Reg. (EC) 889/2002 (baggage) and broaden passenger-rights coverage

**Labels:** `enhancement`, `area:corpus`, `priority:medium` · **Effort:** Large

### Context
The corpus is scoped to Reg. 261/2004. Baggage claims derive from Reg. (EC) 889/2002 and are
out of scope today. This is also why the kept Your Europe summary
(`data/corpus/plain_language_summary.md`) can surface the occasional out-of-scope (e.g. baggage)
passage instead of routing to fallback — an accepted trade-off **until this lands**.

### Problem
Baggage and other passenger-rights questions either fall back or risk a partially-grounded
answer from the broad summary doc.

### Proposed change
Add Reg. (EC) 889/2002 to the corpus and extend eligibility/routing to cover baggage and other
cases — turning some of today's out-of-scope fallbacks into grounded answers. Re-pin
citation-level eval ground truth afterward (see `notes/EVAL_CITATION_SCORING.md`).

### Why it matters
Removes the largest scope gap and resolves the documented summary-doc scope-creep trade-off.

### Acceptance criteria
- [ ] 889/2002 ingested with structure-aware chunking + metadata
- [ ] Baggage questions answer with correct citations instead of falling back
- [ ] Citation-correctness eval cases re-pinned against the expanded corpus

### References
- `data/corpus/`, `src/ingest.py`
- `notes/EVAL_CITATION_SCORING.md`

---

## Add multi-hop reference-following to the RAG subgraph

**Labels:** `enhancement`, `area:rag`, `priority:low` · **Effort:** Large

### Context
Retrieved passages sometimes reference other relevant articles or a fuller explanation
elsewhere in the corpus.

### Problem
The corrective-RAG loop grades and rewrites but does not *follow references* — so an answer can
miss a directly-cited neighbouring article.

### Proposed change
Detect explicit cross-references in retrieved chunks and refine the subgraph to follow them and
retrieve again (iterative / multi-hop retrieval), within the existing bounded-loop discipline.

### Why it matters
A genuine quality enhancement — but high effort with diminishing returns on a 3B model + small
corpus, and it moves eval *scores*, not ground truth. Low priority by design.

### Acceptance criteria
- [ ] Subgraph follows at least one referenced article when present, still bounded
- [ ] No latency regression beyond an agreed cap on the load test

### References
- `src/rag.py` (corrective-RAG loop)

---

## Consolidate domain types into `src/domain.py`

**Labels:** `refactor`, `area:agent-graph`, `priority:low` · **Effort:** Small

### Context
Domain-tied types are defined ad hoc and scattered — `DISRUPTION_TYPES` in `src/calculator.py`,
`QueryType` in `src/state.py`.

### Problem
There are now two domain-type families (the "second real case" the convention waits for), but
they live in unrelated modules, so the structurally-significant types aren't in one visible
place.

### Proposed change
Collect the domain enums/literals into a small `src/domain.py`. Keep it minimal — de-duplication,
not a type framework.

### Why it matters
Improves readability and gives the domain vocabulary a single home, without violating the
"least ceremony" convention (the second real case justifies it).

### Acceptance criteria
- [ ] `DISRUPTION_TYPES` and `QueryType` (and any siblings) live in `src/domain.py`
- [ ] Call sites import from there; behaviour identical (eval unchanged)

### References
- `src/calculator.py` (`DISRUPTION_TYPES`), `src/state.py` (`QueryType`)

---

## Encode the long-haul >3500 km 50% reduction nuance in the calculator

**Labels:** `enhancement`, `area:calculator`, `priority:low` · **Effort:** Small

### Context
For >3500 km flights delayed 3–4 h, Reg. 261/2004 allows a 50% reduction of the €600 band. The
calculator currently notes but does not encode this nuance — a deliberate prototype
simplification.

### Problem
The €600-band amount for that specific delay window can be overstated by 50%.

### Proposed change
Encode the >3500 km, 3–4 h auto-50% reduction in `calculate_compensation`, keeping the function
deterministic and LLM-free. Add eval cases on the boundary.

### Why it matters
Closes a known precision gap in the one output users rely on, with low effort.

### Acceptance criteria
- [ ] >3500 km + 3–4 h delay yields €300 (50% of €600); other windows unchanged
- [ ] Calculator unit tests + an eval case cover the boundary

### References
- `src/calculator.py`
- `tests/test_calculator.py`

---

## By-design: Agent trace is coupled to `AgentState`

**Labels:** `discussion`, `by-design`, `area:agent-graph`, `priority:low` · **Effort:** N/A (decision)

### Context
The Agent-tab "agent steps" read a custom `trace` field on `AgentState`, coupling the UI to the
state shape.

### Decision (why it's by-design)
The custom trace was chosen deliberately because it **survives `.invoke()`** — which the eval
runner depends on — whereas `stream_mode="custom"` is stream-only. A pure-streaming rewrite
would break the non-streamed eval path.

### Bar to revisit
Only worth reopening if nodes are being restructured anyway (touch them once) — not as a
standalone rewrite. Filed for visibility, not as pending work.

### References
- `src/state.py` (`trace`), `src/graph.py`, `streamlit_app.py` / `ui_components.py`
- `notes/EVAL_RESULTS.md` §2 (per-node timing layered alongside the trace)
