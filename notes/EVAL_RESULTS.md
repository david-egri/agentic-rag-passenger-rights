# Functional evaluation & load test results

Methodology and recorded results for the functional evaluation and load test. The eval set +
runner are the **measurement instrument** (build-once, design-independent); the numbers below
are the **baseline on the current design** — the corpus/code improvements they point to are
tracked as GitHub issues, and this baseline should be **re-run** after they land.

Commands:
```bash
python -m eval.functional_eval        # 15-Q functional eval → table + eval/last_run.json
python -m eval.loadtest               # load test (50–200 queries) → timing/bottleneck
```

---

## 1. Functional eval

### Methodology
- **Set:** `eval/eval_set.yaml` — 15 questions covering all four routes, the three distance
  bands, sub-threshold €0, cancellation + denied-boarding disruption types, both eligibility
  verdicts (own-staff strike vs. weather/ATC), and the documented 3B known-fail (a residual
  citation-correctness gap).
- **Driver:** `eval/functional_eval.py` runs the **real compiled graph** via `run_agent()`
  (the same `.invoke()` path the UI uses), so a pass means the assembled agent behaves end to
  end.
- **Ground truth** is anchored to **Reg. (EC) 261/2004 correctness**, not current graph
  output, so routing/eligibility/amount survive the future corpus/code changes. Every route
  distance was recomputed from real OpenFlights coords before pinning amounts (CLAUDE.md
  gotcha). Citation `any_of` correctness is pinned against the **current 4-doc corpus** and
  will be re-pinned after the corpus pass (`notes/EVAL_CITATION_SCORING.md`).
- **Scored dimensions** (only those a case pins): routing, eligibility, amount (the *gated*
  final figure), citation presence (guardrail), citation correctness (`any_of`,
  source + article, set-membership / recall).
- **Known-fails** (the spot-check finding) are scored like any case but reported
  separately, so the baseline distinguishes a *documented gap* from a *new regression*.

### Baseline (2026-06-15, `qwen2.5:3b-instruct`, temperature 0)

Measured on the **v2 capability-routed graph**: `classify` routes directly on its three intent
signals (`in_scope` / `asks_rights` / `asks_amount`) to `{rights | extract → calculator ‖
eligibility} → synthesize`. `extract` runs **only on the amount path**; the corrective-RAG
`rights` node runs **only when `asks_rights`**; `eligibility` grounds its own cause-specific
retrieval (retrieve-only — no `generate`). Supersedes the 2026-06-14 classify/extract baseline
(same correctness, wall ≈ 324 s); the topology changes here are a **latency** win (see §2), not a
correctness one.

| Dimension | Score | Notes |
|---|---|---|
| Routing | **15/15 (100%)** | signal-based routing; `query_type` is now a report-only label |
| Eligibility | **9/9 (100%)** | own-staff strike → eligible; weather/ATC → not |
| Amount (gated) | **9/9 (100%)** | all bands + sub-threshold + gating correct |
| Citation presence | **7/7 (100%)** | every rights/mixed answer carries ≥1 citation |
| Citation correctness | **6/6 (100%)** | excludes the one known scope-asymmetry miss |

- **Overall (excl. known-fails): 14/14 cases fully pass.**
- **Known-fails: 1/1 dimension failed exactly as documented** (scope-asymmetry citation
  correctness) — the eval set still pins it, distinguishing the documented gap from a regression.
- Wall time ≈ 197 s for 15 cases (avg ≈ 13 s/case), **down from ≈ 324 s** on the previous
  topology. Per-route timing now reflects the conditional pipelines:
  `out_of_scope` ≈ **3 s** (just `classify` → `fallback` — `extract` no longer runs before the
  route is known), pure `compensation_calc` ≈ **8–9 s** (no `rights`/RAG call), `rights_info`
  ≈ 14–18 s, `mixed` ≈ 26–27 s (both pipelines run). See §2 for the per-node breakdown.

### Findings

**F-ROUTING — RESOLVED (held since 2026-06-14).** Routing is **15/15**. The 2026-06-14 refactor
fixed the original `intake` misrouting by emitting three independent boolean signals via
`with_structured_output` and deriving the lane in code. The v2 change keeps that classifier
untouched and simply **routes on the booleans directly** rather than on the derived `query_type`
label (now report-only) — so routing accuracy is unchanged while the four-way label no longer
steers control flow.

**F-CAUSE-SPECIFICITY — eligibility correctness depends on `extract` keeping the cause specific.**
The eligibility verdict turns on the own-staff-vs-third-party distinction, which lives entirely in
the extracted `reason`. A run where `extract` flattened "a strike by the airline's **own cabin
crew**" to a bare "airline staff strike" mis-judged `mixed-own-strike` as extraordinary (→ €0). The
fix was in `extract`, not the eligibility grounding: the prompt now captures any stated cause *as
stated and specific* (preserving who is striking). With the specific cause, the verdict is correct
in every grounding configuration — even with no retrieved context — and is stable across re-runs.
The eligibility judgment is the most variance-prone dimension on a 3B model; this is the lever to
watch on re-runs.

**F-SCOPE-CITATION — the residual scope-asymmetry gap is citation correctness, not routing.**
The coverage question ("New York → Paris on a US carrier") classifies as `rights_info` correctly,
but retrieval still doesn't surface Art. 3 / the EUR-Lex summary for it, so `cite_correct` misses.
This is the one remaining documented known-fail — tracked against the corpus/retrieval, not the
graph.

---

## 2. Load test

### Methodology
- **Driver:** `eval/loadtest.py` runs N queries (default 50; brief: 50–200) through the real
  graph, **sequential and single-threaded**. A single local Ollama serializes generation on
  the model, so concurrency would only queue requests and muddy per-node attribution — the
  question this test answers is *where the time goes per run*, not max throughput under
  contention.
- **Query pool** = the 15-case eval set, cycled round-robin to N (balanced route mix,
  reproducible — no randomness).
- **Per-node timing** via LangGraph `stream_mode="debug"` (paired `task`/`task_result`
  timestamps), layered *alongside* the semantic `trace` (which lives on `AgentState`), not
  stuffed into it. The `rights` node's time bundles the whole corrective-RAG subgraph (its
  internal retrieve/grade/generate aren't split out at the main-graph level); `eligibility` is a
  cause-specific vector retrieval plus one LLM judgment.

### Results (N=50, 2026-06-15, `qwen2.5:3b-instruct`, temperature 0)

v2 capability-routed topology (conditional `rights` and `extract`; retrieve-only eligibility).
Supersedes the 2026-06-14 classify/extract run (wall 1204.9 s, mean latency 24.1 s).

- **Wall time 788.2 s**, throughput **0.063 q/s** (~3.8 queries/min) — **−35 %** wall vs the
  previous topology.
- **End-to-end latency (s):** mean **15.76**, p50 **14.76**, p90 **27.0**, p95 **32.4**, max
  **36.3**, min **3.08** (the `out_of_scope` path — now a single `classify` call before `fallback`).
  Mean latency fell **24.1 → 15.76 s (−35 %)**.

| node | kind | calls | total s | mean s | share |
|---|---|---:|---:|---:|---:|
| `rights` | LLM | 22 | 377.9 | 17.18 | **45.7%** |
| `classify` | LLM | 50 | 193.6 | 3.87 | **23.4%** |
| `extract` | LLM | 28 | 177.9 | 6.35 | **21.5%** |
| `eligibility` | LLM* | 28 | 76.9 | 2.75 | 9.3% |
| `calculator` | — | 28 | 0.12 | 0.004 | 0.0% |
| `synthesize` | — | 44 | 0.02 | 0.000 | 0.0% |
| `fallback` | — | 6 | 0.00 | 0.000 | 0.0% |

\* `eligibility` is LLM **only when a cause is stated**; the no-cause path is deterministic (no
retrieval, no LLM). Call counts follow directly from the routing: `rights` fires on the 22
`asks_rights` runs, `extract`/`calculator`/`eligibility` on the 28 `asks_amount` runs, `classify`
on all 50, `fallback` on the 6 `out_of_scope` runs, and `synthesize` on the 44 non-fallback runs.

### Bottleneck

**Still local-LLM generation, full stop — LLM nodes are 100.0% of node time; everything non-LLM is
0.14 s total (0.0%).** This confirms the CLAUDE.md prediction (calculator + vector search +
assembly negligible). What changed is the **call mix**, because the pipelines are now conditional:
- **`rights` (45.7%)** is again the single dominant cost (~17 s/call: grade + generate, plus a
  grade+generate per corrective rewrite), but it now fires on only **22 of 50** runs — the
  `asks_rights` ones — instead of 44. Pure-amount queries skip it entirely.
- **`classify` (23.4%)** is the new universal floor: one ~3.9 s call on **every** query, the only
  node that always runs. It is now the largest *unavoidable* per-query cost.
- **`extract` (21.5%)** runs on only the **28** amount-path runs (was all 50), so rights-only and
  out-of-scope queries no longer pay its ~6.3 s.
- **`eligibility` (9.3%)** is unchanged in call count (28) and per-call cost (~2.7 s); the
  retrieve-only grounding keeps the vector search negligible and avoids a second generation.
- **Non-LLM nodes are free**: `calculator` 0.12 s over 28 calls, `synthesize`/`fallback` rounding
  error. The only lever remains the **number and cost of LLM calls**.

### Optimizations

**A — built into the design; the load test quantifies the payoff.**
1. **Deterministic no-cause eligibility**: the no-cause path skips the LLM (and retrieval)
   entirely; only the stated-cause subset hits the LLM, averaging ~2.7 s.
2. **LLM-free `synthesize`**: assembling the final answer adds **0.02 s** over 44 calls — a second
   generative pass here would have been ~17 s × 44 ≈ ~750 s and a fresh hallucination surface.
3. **`out_of_scope` short-circuit to `fallback`** (no LLM): those runs complete in ~3.1 s vs the
   ~15.8 s mean — and the win is **bigger again** now that `extract` no longer runs before the
   route is known (it was ~8 s on the previous topology).

**B — conditional RAG for pure `compensation_calc` — DONE this round.** The v2 routing sends a
pure-amount query straight to `extract → calculator ‖ eligibility`, skipping the `rights`/RAG node;
its citations (eval pins `required: false` for calc-only cases) come from eligibility's own
cause-specific retrieval when a cause is stated. Payoff: `rights` calls fell **44 → 22**, removing
one ~17 s subgraph call from every pure-amount query.

**C — conditional `extract` — DONE this round.** `extract` now runs only on the amount path, not on
every query. Payoff: `extract` calls fell **50 → 28**, and `out_of_scope` dropped back to ~3 s
(`classify` → `fallback`, no extraction). Together B and C cut wall time **1205 → 788 s** and mean
latency **24.1 → 15.8 s**.

**D — remaining levers (open).** With B and C shipped, the dominant costs are the two nodes that
are hard to avoid: the `rights` corrective-RAG subgraph (~17 s when it runs) and the universal
`classify` floor (~3.9 s on every query). Further wins would have to target the **RAG loop itself**
(e.g. cheaper grading, or capping rewrites harder) or fold the work of `classify` — neither is a
routing change. Tracked as GitHub issues, to be re-measured here.

---

## 3. Plain-language summary

A non-technical distillation of the two sections above — the same facts, no jargon.

### What we learned

**Is it correct? (functional eval)**
- **The money is always right.** Every compensation amount and every eligibility decision was
  correct — 100%. €250 / €400 / €600 / €0, and whether weather or strikes count, is rock-solid.
- **The grounding is always right.** Every rights answer came with a real citation to the law —
  no made-up answers.
- **Sorting questions into the right lane stays at 15 of 15.** The system has the model tick three
  yes/no boxes about a question, and now steers entirely off those boxes (the old four-way label is
  kept only for display).
- **One blind spot to watch.** Whether a strike counts hinges on *who* is striking — the airline's
  own crew (you're owed money) vs. a third party (you're not). The system now makes sure it captures
  that "who" precisely when reading the question; if it ever loses that detail, the strike answer
  can flip. The remaining known gap is the "am I even covered?" coverage question: it's sorted into
  the right lane, but the system still doesn't pull up the exact article that backs the answer.

**Is it fast enough? (load test)**
- **One query now takes ~16 seconds** on this hardware — **down from ~24 s** last round.
- **All of that time is the AI model thinking.** The math, the database, and the answer-assembly
  are basically instant (a fraction of a second combined). The system is slow *only* because of the
  local AI model — not because of any inefficiency in our code.
- **The most expensive single step is reading the law and writing the grounded answer** (~46%) —
  but it now only runs when a question actually asks about rights.
- **We made it faster by doing less work per question.** Money-only questions skip the law-reading
  step; rights-only and off-topic questions skip the flight-detail-extraction step; off-topic
  questions bail out after a single step (~3 s). Those three "only do what this question needs"
  changes are what cut a typical query from ~24 s to ~16 s.

**Bottom line:** accurate where it counts (amounts, eligibility, citations), faster than last round,
and slow only because of the local AI model.

### What to improve next

**Done this round — only do the expensive steps when the question needs them (speed).** Money-only
questions no longer read the law; rights-only and off-topic questions no longer extract flight
details. This is the speed work the previous baseline flagged as "still to do" — now shipped, for a
~35% drop in both wall time and per-query latency.

**Done this round — keep the cause specific (accuracy).** The strike answer depends on *who* is
striking; the question-reading step now preserves that detail so own-crew strikes are correctly
treated as compensable.

**Still to do — the coverage-citation blind spot (accuracy).** For "am I even covered?" questions
about flights into the EU on a non-EU airline, the system picks the right lane but doesn't surface
the exact article that backs the answer. The fix lives in the corpus/retrieval, not the graph.

**Still to do — the remaining speed levers are harder.** The two unavoidable costs left are reading
the law (when rights are actually asked) and the always-on question-sorting step. Shaving those
would mean a cheaper retrieval loop, not another routing change.

> **One line:** correctness holds at 14/14 (+1 documented known-fail), and this round's win is
> **speed** — making the law-reading and detail-extraction steps conditional cut a typical query
> from ~24 s to ~16 s. The open items are the corpus-side citation gap and harder retrieval-loop
> speedups, tracked as GitHub issues.
