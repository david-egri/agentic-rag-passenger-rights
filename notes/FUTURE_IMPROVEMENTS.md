# Future improvements & known limitations

Forward-looking backlog for the prototype, distilled from the review pass and the evaluation
baseline (see `notes/EVAL_RESULTS.md` for the numbers these items target). Each entry was
cross-checked against the current code, so this lists only **genuinely-open** work and
**accepted limitations** — not anything already shipped.

Grouped by the lever each item pulls: **accuracy**, **speed**, **scope/data**, **code
quality**, and **known limitations** (deliberately not fixed).

---

## Accuracy

### Structured-output intake (highest-value accuracy lever)
**State:** open. `intake`, `planner`, and `eligibility` hand-parse the model's JSON via a
manual fence-stripping helper (`_parse_json` in `src/graph.py`); `src/llm.py` exposes only a
bare `get_llm()`.

**Improvement.** Move structured extraction onto the `langchain-ollama`
`with_structured_output` formalism backed by predefined Pydantic schemas, centralized in
`src/llm.py` with a clear per-node naming convention. Schema-constrained output replaces
hand-parsed JSON, reducing parse failures.

**Why it matters.** The evaluation's weak dimension is **routing** (~71%): the intake model
pulls a query toward "compensation" whenever it mentions a disruption *and* a money/refund
word (`"refund"`, `"how much"`). Forcing the model to fill fixed slots rather than reply
free-form is the most reliable fix — models are far better at "ticking boxes" than writing
freely. Pairs naturally with the two blind spots below.

### Teach the two known blind spots
**State:** open; both are documented known-fails the eval set already pins, so progress is
measurable.

- **ATC delays wrongly treated as compensable.** Air-traffic-control disruptions are outside
  the airline's control (extraordinary → no compensation), but the model sometimes awards it.
- **EU route-scope asymmetry.** A non-EU → EU flight on a **non-EU** carrier is *not* covered;
  the model fumbles "am I even covered?" phrasings.

**Improvement.** Add these as explicit worked examples in the intake/eligibility prompts — the
same way weather = no compensation but an airline's **own-staff strike** = compensation is
already taught. (Structured output above plausibly helps the extraction half of these.)

### Delay disruption-type robustness
**State:** investigate-first. The calculator's delay table is correct in isolation
(`src/calculator.py`: delay → `threshold_met = delay_hours >= 3`; cancellation / denied
boarding → `True`). The risk is **upstream**: how intake extracts `disruption_type` +
`delay_hours`, and whether **cancellation carve-outs** (Art. 5(1)(c): no compensation if
notified > 14 days, or with timely re-routing) get conflated.

**Improvement.** Audit delay-only cases (at / under / over 3 h) and cancellation-with-notice
cases; whatever surfaces becomes new eval cases. Structured-output intake likely helps the
extraction half.

---

## Speed

### Conditional RAG — skip retrieval for pure `compensation_calc`
**State:** open. `src/graph.py` routes `compensation_calc` to a `["rag", "calculator"]`
fan-out, so the RAG subgraph (~70% of per-query latency) runs even when the answer is purely
an amount.

**Improvement.** Make the RAG branch **conditional**: skip it for pure `compensation_calc`
(the amount is deterministic from the calculator and eligibility is usually the no-cause
deterministic path; citations are optional for calc-only answers), keep it for `rights_info`
and `mixed`. Touches the router's branch logic + the eligibility branch's doc dependency +
calc-only citation expectations.

**Projected impact.** Calc queries drop from ~18 s to ~4–5 s (intake + calculator +
deterministic eligibility/synthesize) — a large share of realistic traffic. Re-measure with
the load test after the change.

---

## Scope & data

### Add Reg. (EC) 889/2002 (baggage) and broaden coverage
**State:** open / accepted limitation today. The corpus is scoped to Reg. 261/2004; baggage
claims derive from Reg. (EC) 889/2002 and are out of scope.

**Improvement.** Add 889/2002 to the corpus and extend the eligibility/routing logic to cover
baggage and other passenger-rights cases — turning some of today's out-of-scope fallbacks into
grounded answers.

### RAG multi-hop reference-following
**State:** open; high effort, diminishing returns on a 3B model + small corpus.

**Improvement.** Retrieved passages sometimes reference other relevant articles or a fuller
explanation. The RAG subgraph could detect these and refine itself to follow the reference and
retrieve again (iterative / multi-hop retrieval). Moves eval *scores*, not ground truth.

---

## Code quality

### Consolidate domain types into `src/domain.py`
**State:** open. Domain-tied types are defined ad hoc and scattered — `DISRUPTION_TYPES` in
`src/calculator.py`, `QueryType` in `src/state.py`.

**Improvement.** Collect the domain enums/literals into a small `src/domain.py` so the
structurally-significant types live in one visible place. There are now two domain-type
families (the "second real case" the convention waits for), so this is de-duplication, not
gold-plating — keep it minimal, no type framework.

---

## Known limitations (deliberately not fixed)

- **Long-haul > 3500 km, 3–4 h delay → 50% reduction nuance** is noted but not encoded in the
  calculator. A deliberate simplification for the prototype.
- **Plain-language summary covers more than Reg. 261/2004.** `plain_language_summary.md`
  (Your Europe) was kept for its colloquial → formal recall and compensation tables, at the
  cost of the occasional out-of-scope passage retrieving instead of routing to fallback — an
  accepted trade-off until 889/2002 (above) lands.
- **Trace coupled to state.** The Agent-tab "agent steps" read a custom `trace` field on
  `AgentState`, coupling the UI to the state shape. This was chosen deliberately because the
  custom trace survives `.invoke()` (which the eval runner depends on), whereas
  `stream_mode="custom"` is stream-only. Revisit a pure-streaming approach only if nodes are
  being restructured anyway — not as a standalone rewrite.
