# Phase 5 — Review findings & cross-phase coupling

Working notes from the human-driven Phase 5 review pass. These are **findings the user
surfaced while spot-checking the assembled solution** (Phases 1–4), polished into a
revisitable list, each annotated with *impact*, *difficulty*, *what later phase it couples
to*, and *recommended timing*. This file is the backlog we iterate over; settled decisions
get promoted to `DECISIONS.md`, plan/status changes to `PLAN.md`.

See also: `notes/EVAL_CITATION_SCORING.md` (the citation-scoring design these findings
reference), and the two already-logged spot-check findings in `DECISIONS.md`
(`spot-check-misroutes`: `ATC-NOT-EXTRAORDINARY`, `SCOPE-ASYMMETRY-MISROUTE`).

---

## Agreed sequencing (the frame these findings sit in)

The key realization: **Phase 6 splits into two separable pieces** —

- the **evaluation machinery** (eval set + runner/scoring + load-test driver): build-once,
  design-independent, reusable — stand it up *early* as the instrument that measures whether
  these findings are real and protects the changes we make;
- the **evaluation results** (recorded scores, latency/bottleneck numbers, the 1–2
  optimizations write-up): *outputs* of running the machinery against a specific design —
  only worth locking in *after* the corpus/code changes, because every change moves them.

Resulting order:

1. **Eval harness + baseline** (start of Phase 6, not its completion).
2. **Corpus pass** — findings #1 + #2; *then* pin the citation-level eval ground truth.
3. **Code/structure pass** — findings #3 + #4 + investigate #6; re-run the eval after each.
4. **Finalize Phase 6** — eval report + load test + bottleneck/optimizations on the settled
   design (natural home for finding #5's trace/timing work).
5. **Docker** — the genuinely independent addition.
6. **README** — written once, last.

Coupling cheat-sheet: **Docker** is independent (wraps the app; cares about deps/entrypoint,
not graph shape). **README** + **corpus-provenance** are coupled to the *final* design → last.
The **eval set's** routing/eligibility/amount ground truth is design-independent **if anchored
to Reg. 261/2004 correctness, not to current graph output**; only its **citation-level**
ground truth couples to the corpus.

---

## Group A — Corpus (ripples into eval citation ground-truth → settle before pinning that)

These two are linked (both = "what's in the corpus + how it's made"), both resolve the
deferred `gitignore-data-for-now` Phase 7 decision, and both must precede the
**citation-correctness** slice of the eval set. Do them as one **corpus pass**.

### #1 — Remove `plain_language_summary.md` (scope creep)
*Impact: high (guardrail alignment) · Difficulty: low*

**Finding.** The Your Europe plain-language summary (`data/corpus/plain_language_summary.md`,
source label *"EU Air Passenger Rights Summary"*) covers **more legislation than Reg.
261/2004** — e.g. baggage claims, which derive from **Reg. (EC) 889/2002**. A baggage
question can therefore retrieve a grounded-looking passage from this doc instead of routing
to fallback.

**Why it matters.** This actively undermines two non-negotiables: **#4** (out-of-scope →
fallback — the fallback can't fire if RAG finds a baggage passage) and **#3** (ground only in
261/2004). It's a *correctness* fix, not tidiness.

**Trade-off to go in with eyes open.** `DECISIONS.md` (`corpus-2024-guidelines`) kept this doc
specifically for **colloquial→formal recall** and its compensation tables. Removing it may
cost some plain-language recall — measurable via the eval baseline. The narrower
`legissum_261_2004.html` (scoped to 261/2004) stays and retains some of that colloquial value.

**Coupling.** Corpus change → invalidates any eval ground truth whose expected citation points
at *"EU Air Passenger Rights Summary."* Settle before pinning citation-correctness.

**Recommendation.** Remove it; log **"add Reg. 889/2002 + extend to baggage/other cases"** as
future work (README "future improvements").

### #2 — Corpus acquisition: human-download + one-time paid LLM extraction → committed clean corpus
*Impact: high (graded "how is data processed" story) · Difficulty: medium · ⚠️ touches a non-negotiable*

**Finding.** Acquiring/parsing the corpus was painful: EUR-Lex bot detection (AWS WAF) blocks
automated download, and structure-aware parsing of these documents is non-trivial. Since
**human** download *is* possible, the proposed workflow is: a human downloads the raw HTML/PDF
originals → a **one-time** call to a high-capacity model (e.g. Opus) extracts each into a
clean, easily-parsable `.md` → the **processed corpus is committed to git**. Trade: a one-time
paid processing step, in exchange for greatly simplified corpus handling. Possible exception:
the Your Europe summary (finding #1) — itself already a summary of a webpage, and uncertain
whether we keep it.

**⚠️ Non-negotiable tension.** Non-neg **#1** ("No paid APIs… never add an OpenAI/Anthropic
client") governs the **running solution** (the chatbot must use local Ollama). A **one-time,
offline, build-time** extraction that yields a committed artifact the app never calls at
runtime is arguably outside that rule's spirit — but it's load-bearing enough to **decide
deliberately and log in DECISIONS**, not slip in. Reproducibility is preserved *because the
processed `.md` is committed* (a fresh clone never re-runs the extraction or needs a key).

**Structure-preservation caveat.** Non-neg #2 / the guardrail wants **structure-aware chunking
(Article/Recital/Section)** as a scoring point. The LLM extraction must **preserve** that
structure as markdown headings (`## Article 7`) so citations still key off Article/Section —
not flatten it away.

**Three viable shapes (user's call):**
- **(a) Free fetch-script** — commit the current frozen corpus + `scripts/fetch_corpus.py`
  (Cellar API + `requests` export, the routes already cracked). Zero paid, fully reproducible,
  but the **complex per-doc chunkers stay**.
- **(b) User's proposal** — raw download → one-time Opus extraction → clean uniform `.md`
  committed. **Simplifies the chunkers dramatically** (likely collapse to one markdown-heading
  chunker), clean processing story, paid once. Tension with #1 as above.
- **(c) Commit-as-is** — commit raw + already-parsed corpus, document acquisition in prose, no
  script. Lowest effort, weakest "processing" narrative.

**Coupling.** Re-chunking changes `chunk_id`s and can shift section/article *labels* (cf. the
parked OJ-notice em-dash leak) → invalidates `chunk_id`- or label-keyed citation ground truth.
Resolves the Phase 7 corpus-provenance / `gitignore-data-for-now` decision. **Do before
pinning citation-correctness.**

---

## Group B — Code structure / robustness (refactors; cheapest now, low phase-coupling; eval harness protects them)

### #3 — Domain types are scattered & hidden
*Impact: medium · Difficulty: low–medium*

**Finding.** Domain-tied types with global effect are defined ad hoc and buried:
`DISRUPTION_TYPES` in `src/calculator.py:42`, `QueryType` in `src/state.py`. Types tied to the
domain should be handled **consistently and in a structurally visible place**.

**Why it matters / convention check.** CLAUDE.md says "abstraction when a *second* real case
appears, not in anticipation" — we now have **two** domain-type families, which is exactly that
second case, so a small `src/domain.py` (the domain enums/literals) is de-duplication, not
gold-plating. Keep it minimal; do **not** build a type framework.

**Coupling.** Pure refactor; LOW coupling to later phases. Behavior must stay identical — the
regression check / eval harness covers it. **Cheapest while design is fluid (now).**

### #4 — Consolidate structured-output LLM usage into `llm.py`
*Impact: medium–high (also a correctness lever) · Difficulty: medium*

**Finding.** Structured-output LLM usage exists but is ad hoc. It should live in `src/llm.py`,
use the **Ollama / `langchain-ollama` structured-output formalism** (`with_structured_output`
+ predefined Pydantic schemas), with a clear naming convention so it's obvious how to use each
schema within the graph.

**Why it matters.** Not just cleanliness — moving from hand-parsed JSON to schema-constrained
output reduces parse failures, which plausibly touches the misclassification findings
(`ATC-NOT-EXTRAORDINARY`, `SCOPE-ASYMMETRY-MISROUTE`, `DECISIONS.md` `spot-check-misroutes`)
and finding #6. Pairs naturally with #3 (both are "domain + LLM contract" cleanups).

**Coupling.** Touches `llm.py` + the structured-output call sites (intake / router / grader /
eligibility). Because it **can change classification outputs**, do it **with the eval baseline
in place** to confirm no regression (and hopefully an improvement).

### #6 — Delay disruption-type robustness
*Impact: high if real · Difficulty: investigate-first*

**Finding.** Spot-checking suggests the **delay** disruption type may not be handled robustly —
particularly **delay-only** cases (no cancellation). Worth a deeper look.

**Where the risk is *not*.** The calculator's delay table is correct in isolation
(`src/calculator.py:155–158`: delay → `threshold_met = delay_hours >= 3`; cancellation /
denied boarding → `threshold_met = True`). So the risk is **upstream**: how **intake extracts
`disruption_type` + `delay_hours`**, and whether **cancellation carve-outs** (Art. 5(1)(c): no
compensation if notified >14 days, or with timely re-routing) are conflated. (#4's structured
output likely helps the extraction half.)

**Coupling.** Whatever we find becomes **eval cases** (delay-only at/under/over 3 h; cancellation
with/without notice). Cheap to investigate; good Phase-5 spot-check item.

---

## Group C — Already-litigated / bigger breadth (reopen only with clear payoff, or defer)

### #5 — Trace-in-state → LangGraph custom streaming
*Impact: architectural · Difficulty: medium · already a logged decision*

**Finding.** The Agent-tab "agent steps" use a **custom `trace` field on `AgentState`**. This
couples the UI to the state shape — changing the graph can break the trace visualization.
Worth examining **`stream_mode="custom"` + `get_stream_writer()`** for per-node streaming
behaviour and a more modular UI/backend boundary.

**Already decided (bar to reopen).** `DECISIONS.md` `trace-in-state` chose the custom field
*deliberately*; the reasons are still live — chiefly that the custom trace **survives
`.invoke()`**, which the **eval runner depends on**, whereas `stream_mode="custom"` is
**stream-only**. A pure-streaming rewrite must not break the non-streamed path.

**Recommendation.** Don't rewrite the trace mechanism standalone. Revisit **only if** we're
restructuring nodes anyway (touch them once), or **fold it into the Phase 6 timing work** —
the `TRACE-VS-TIMING` flag already plans to layer `stream_mode="debug"` in for per-node
latency. Medium effort, unclear prototype payoff on its own.

### #7 — RAG multi-hop reference-following
*Impact: quality · Difficulty: high*

**Finding.** Retrieved passages sometimes contain **explicit references to other relevant
parts** or to a fuller explanation of the topic. The RAG subgraph could detect these and
**refine itself to follow the reference and retrieve again** (iterative/multi-hop retrieval).

**Assessment.** Genuine enhancement, but high effort with diminishing returns on a 3B model +
4-doc corpus, and it only moves eval *scores*, not ground truth. **Defer to README "future
improvements."**

---

## Future-work parking lot (carry into README "potential improvements")
- Add **Reg. (EC) 889/2002** (baggage) + extend the solution to other passenger-rights cases (#1).
- **RAG multi-hop** reference-following (#7).
- Long-haul (>3500 km) 3–4 h **auto-50%** nuance, noted-not-encoded (`DECISIONS.md`
  `calculator-rules-constants`).
- `RULES-LOCATION-REVISIT`, `GRAPH-DIAGRAM-OFFLINE` (existing DECISIONS flags).
