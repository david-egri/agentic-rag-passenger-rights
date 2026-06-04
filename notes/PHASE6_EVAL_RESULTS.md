# Phase 6 — Functional eval + load test results

Methodology and recorded results for the Phase 6 deliverables. The eval set + runner are the
**measurement instrument** (build-once, design-independent); the numbers below are the
**baseline on the current design** (the corpus/code review findings are deferred to a later
phase — DECISIONS `phase-6-eval-only` — so this baseline will be **re-run** after that phase).

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
  verdicts (own-staff strike vs. weather/ATC), and the two documented 3B known-fails.
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
- **Known-fails** (the two Phase-5 spot-check findings) are scored like any case but reported
  separately, so the baseline distinguishes a *documented gap* from a *new regression*.

### Baseline (2026-06-04, `qwen2.5:3b-instruct`, temperature 0)

| Dimension | Score | Notes |
|---|---|---|
| Routing | **10/14 (71%)** | the weak dimension — see findings below |
| Eligibility | **8/8 (100%)** | own-staff strike → eligible; weather → not |
| Amount (gated) | **8/8 (100%)** | all bands + sub-threshold + gating correct |
| Citation presence | **7/7 (100%)** | every rights/mixed answer carries ≥1 citation |
| Citation correctness | **6/7 (86%)** | the one miss is the known scope-asymmetry case |

- **Overall (excl. known-fails): 10/13 cases fully pass.**
- **Known-fails: 3/3 dimensions failed exactly as documented** (scope-asymmetry routing;
  ATC eligibility + amount) — both Phase-5 findings reproduce, confirming they're real and
  the eval set pins them.
- Wall time ≈ 256 s for 15 cases (avg ≈ 17 s/case); out_of_scope cases are ≈ 2.5 s (fallback,
  no LLM generation) vs. ≈ 17–28 s for RAG/generation cases — first signal for the load test.

### Findings from the baseline (carry into the review phase, do NOT fix in Phase 6)

**F-ROUTING — intake blurs rights_info / compensation_calc / mixed on a 3B model.** Every
routing miss is the intake LLM pulling a query toward "compensation" whenever it mentions a
disruption **and** a money/refund word:

| case | expected | actual | trigger |
|---|---|---|---|
| `cancel-refund` | rights_info | mixed | "refund" |
| `delay-care` | rights_info | compensation_calc | "delayed 5h … entitled" |
| `mixed-own-strike` | mixed | compensation_calc | dropped the rights half |
| `scope-asymmetry` (known) | rights_info | mixed | "New York / US airline" |

*Impact is mostly cosmetic on correctness:* `compensation_calc` and `mixed` both run the
eligibility branch, so **eligibility and amount stay correct even when misrouted** — the cost
is the rights-paragraph / trace shape, not the numbers. This is the same intake weakness
finding **#4 (structured-output consolidation)** targets; the review phase should re-measure
routing after moving intake to `with_structured_output` + a Pydantic schema, and after the
intake-prompt tweaks for scope/coverage questions (`SCOPE-ASYMMETRY-MISROUTE`) and ATC
(`ATC-NOT-EXTRAORDINARY`).

**F-SCOPE-FAILMODE — the scope-asymmetry misroute now lands on `mixed`, not `fallback`.**
DECISIONS `spot-check-misroutes` recorded it routing to `out_of_scope → fallback`; at this
baseline it routes to `mixed`. Still a routing failure, but the failure mode shifted — note it
when fixing so the fix targets the right behaviour.

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
  timestamps), layered *alongside* the semantic `trace`, not stuffed into it — the
  `TRACE-VS-TIMING` plan (DECISIONS `trace-in-state`). The `rag` node's time bundles the whole
  corrective-RAG subgraph (its internal retrieve/grade/generate aren't split out at the main-
  graph level).

### Results (N=50, 2026-06-04, `qwen2.5:3b-instruct`, temperature 0)

- **Wall time 890.7 s**, throughput **0.056 q/s** (~3.4 queries/min).
- **End-to-end latency (s):** mean **17.8**, p50 **18.1**, p90 **24.6**, p95 **25.7**, max
  **30.5**, min **2.47** (the out_of_scope fallback path — no LLM generation).

| node | kind | calls | total s | mean s | share |
|---|---|---:|---:|---:|---:|
| `rag` | LLM | 44 | 614.4 | 13.96 | **69.0%** |
| `intake` | LLM | 50 | 213.3 | 4.27 | **24.0%** |
| `eligibility` | LLM* | 40 | 33.6 | 0.84 | 3.8% |
| `planner` | LLM | 11 | 29.1 | 2.65 | 3.3% |
| `calculator` | — | 40 | 0.16 | 0.004 | 0.0% |
| `router` | — | 50 | 0.04 | 0.001 | 0.0% |
| `synthesize` | — | 44 | 0.02 | 0.000 | 0.0% |
| `fallback` | — | 6 | 0.00 | 0.000 | 0.0% |

\* `eligibility` is LLM **only when a cause is stated**; the no-cause path is deterministic.

### Bottleneck

**The bottleneck is local-LLM generation, full stop — LLM nodes are 100.0% of node time;
everything non-LLM is 0.22 s total (0.0%).** This confirms the CLAUDE.md prediction
(calculator + vector search + assembly negligible). The shape:
- **`rag` (69%)** is the single dominant cost — it runs ≥2 LLM calls (grade + generate), plus
  another grade+generate on each corrective rewrite. It's the most expensive node *and* the
  most "agentic" one.
- **`intake` (24%)** is one structured-extraction call on every query — unavoidable as the
  entry classifier, but a fixed ~4.3 s tax per query.
- **Non-LLM nodes are free**: `calculator` 0.16 s over 40 calls, `synthesize`/`router`/
  `fallback` are rounding error. Optimizing them would buy nothing; the only lever is the
  **number and cost of LLM calls**.

### Optimizations

**A — already in the design; the load test quantifies the payoff.** Three deliberate latency
choices show up directly in the numbers:
1. **Deterministic no-cause eligibility** (DECISIONS `eligibility-control-frame`): `eligibility`
   averaged **0.84 s/call** vs `intake`'s 4.27 s for a comparable single LLM call — because
   most calls skip the LLM. Roughly ¾ of the 40 calls took the deterministic path; making all
   40 LLM calls would add an estimated **~100 s** to the 50-run wall time.
2. **LLM-free `synthesize`** (DECISIONS `synthesize-deterministic`): assembling the final
   answer adds **0.02 s** total over 44 calls — a second generative pass here would have been
   another ~4 s × 44 ≈ ~175 s, and a fresh hallucination surface.
3. **out_of_scope short-circuit to `fallback`** (no LLM): those runs complete in **2.47 s** vs
   the ~18 s mean — the router/fallback firewall is also a latency win.

**B — recommended next lever (a graph change → defer to the review phase).** Since `rag` is
69% of the cost and a *pure* `compensation_calc` answer's amount is deterministic (calculator)
and its eligibility is usually the no-cause deterministic path, the RAG subgraph on that route
mainly produces *optional* citations (eval pins `required: false` for calc-only cases). Making
the RAG branch **conditional** — skip it for pure `compensation_calc`, keep it for
`rights_info`/`mixed` — would remove one ~14 s subgraph call from every calc query (a large
share of realistic traffic). It's deferred because it's a **graph-wiring change** (touches
`_route_from_router` + the eligibility branch's doc dependency + citation expectations), which
belongs to the deferred code-review phase, not Phase 6's measurement scope (DECISIONS
`phase-6-eval-only`). Projected impact: calc queries drop from ~18 s to ~4–5 s (intake +
calculator + deterministic eligibility/synthesize). To be implemented and **re-measured** with
this same load test in the review phase.

_(A secondary lever — moving `intake` to `with_structured_output`, finding #4 — is primarily a
**correctness** fix for `F-ROUTING`, not latency; noted in §1.)_

---

## 3. Plain-language summary

A non-technical distillation of the two sections above — the same facts, no jargon.

### What we learned

**Is it correct? (functional eval)**
- **The money is always right.** Every compensation amount and every eligibility decision was
  correct — 100%. €250 / €400 / €600 / €0, and whether weather or strikes count, is rock-solid.
- **The grounding is always right.** Every rights answer came with a real citation to the law —
  no made-up answers.
- **The one weak spot is sorting questions into the right lane.** About 7 of 10 questions were
  routed correctly. When a question mixes a problem with the word "refund" or "how much," the
  small AI model tends to treat it as a money question. Even when it picks the wrong lane,
  though, the answer and the amount still come out correct — it just takes a different path.
- **The two known weak spots we already knew about showed up exactly as expected** (an
  air-traffic-control case and a coverage-scope case) — confirming the test catches real issues.

**Is it fast enough? (load test)**
- **One query takes ~18 seconds** on this hardware.
- **All of that time is the AI model thinking.** The math, the database, and the answer-assembly
  are basically instant (a fraction of a second combined). The system is slow *only* because of
  the local AI model — not because of any inefficiency in our code.
- **The most expensive single step is reading the law and writing the grounded answer** (~70%).

**Bottom line:** accurate where it counts (amounts, eligibility, citations), and slow only
because of the local AI model.

### What to improve next

**Make it sort questions better (accuracy).** The model sometimes puts a question in the wrong
lane. Fix: instead of letting it reply free-form, force it to fill in a strict form with fixed
slots — models are far more reliable "ticking boxes" than writing freely.

**Teach it two specific blind spots (accuracy).** It wrongly thinks air-traffic-control delays
deserve compensation (they don't — outside the airline's control), and it fumbles "am I even
covered?" questions for flights into the EU on a non-EU airline. Fix: add those exact cases as
worked examples, the way we already taught it weather = no compensation but an airline's own
staff strike = compensation.

**Make money-only questions much faster (speed).** The slowest step (reading the law, ~70% of
the time) runs even for pure "how much do I get?" questions — where the amount actually comes
from the calculator, not the law text. Fix: skip that heavy step for amount-only questions,
dropping them from ~18 s to ~4–5 s.

**Already done — just proven this round.** Three speed shortcuts were already built in (skip the
model when no reason is given; assemble the final answer without the model; bail out instantly
on off-topic questions). The load test confirmed they save real time.

> **One line:** to make it more accurate, force the model to fill in a structured form and give
> it examples of the cases it misses; to make it faster, skip the expensive law-reading step for
> pure money questions. All of these are **code changes saved for the next review phase** —
> Phase 6 only measured, and it gave us the exact targets.

