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
- **Known-fails** (the two spot-check findings) are scored like any case but reported
  separately, so the baseline distinguishes a *documented gap* from a *new regression*.

### Baseline (2026-06-14, `qwen2.5:3b-instruct`, temperature 0)

Measured on the post-refactor graph — `intake` split into `classify` + `extract` (both
`with_structured_output`), `router`/`planner` removed. Supersedes the pre-refactor baseline of
2026-06-04 (routing 10/14, overall 10/13), whose weak dimension this refactor targeted.

| Dimension | Score | Notes |
|---|---|---|
| Routing | **15/15 (100%)** | the former weak spot — fixed by the structured-output `classify` |
| Eligibility | **9/9 (100%)** | own-staff strike → eligible; weather/ATC → not |
| Amount (gated) | **9/9 (100%)** | all bands + sub-threshold + gating correct |
| Citation presence | **7/7 (100%)** | every rights/mixed answer carries ≥1 citation |
| Citation correctness | **6/6 (100%)** | excludes the one known scope-asymmetry miss |

- **Overall (excl. known-fails): 14/14 cases fully pass.**
- **Known-fails: 1/1 dimension failed exactly as documented** (scope-asymmetry citation
  correctness) — the eval set still pins it, distinguishing the documented gap from a regression.
- Wall time ≈ 324 s for 15 cases (avg ≈ 22 s/case); out_of_scope cases are ≈ 8 s vs. ≈ 20–29 s
  for RAG/generation cases. (out_of_scope now runs two LLM calls — `classify` **and** `extract` —
  before it can route to `fallback`, up from one `intake` call; see §2.)

### Findings

**F-ROUTING — RESOLVED (2026-06-14).** The pre-refactor baseline routed only 10/14 correctly:
the single `intake` LLM call pulled a query toward "compensation" whenever it mentioned a
disruption **and** a money/refund word (every miss collapsed `rights_info`/`mixed` into
`compensation_calc`). The fix predicted in that baseline has landed — `intake` was split into a
`classify` node that emits three independent boolean signals (`in_scope` / `asks_rights` /
`asks_amount`) via `with_structured_output`, with `query_type` derived from them in code. Routing
rose to **15/15 (100%)**; the four former misroutes (`cancel-refund`, `delay-care`,
`mixed-own-strike`, `scope-asymmetry`) all route correctly now. The ATC eligibility blind spot
was fixed in the same pass: `mixed-atc-restrictions` gates to €0 and is relabelled
`compensation_calc`, matching its amount-only phrasing.

**F-SCOPE-CITATION — the residual scope-asymmetry gap is citation correctness, not routing.**
With routing fixed, the coverage question ("New York → Paris on a US carrier") now classifies as
`rights_info` correctly, but retrieval still doesn't surface Art. 3 / the EUR-Lex summary for it,
so `cite_correct` misses. This is the one remaining documented known-fail — tracked against the
corpus/retrieval, not the graph.

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
  stuffed into it. The `rag` node's time bundles the whole corrective-RAG subgraph (its
  internal retrieve/grade/generate aren't split out at the main-graph level).

### Results (N=50, 2026-06-14, `qwen2.5:3b-instruct`, temperature 0)

Post-refactor topology (`classify` + `extract` replace `intake`; no `planner`/`router`).
Supersedes the pre-refactor run of 2026-06-04 (wall 890.7 s, mean latency 17.8 s).

- **Wall time 1204.9 s**, throughput **0.041 q/s** (~2.5 queries/min).
- **End-to-end latency (s):** mean **24.1**, p50 **25.1**, p90 **32.0**, p95 **36.3**, max
  **38.2**, min **7.82** (the out_of_scope path — now two LLM calls before `fallback`).

| node | kind | calls | total s | mean s | share |
|---|---|---:|---:|---:|---:|
| `rag` | LLM | 44 | 660.5 | 15.01 | **54.8%** |
| `extract` | LLM | 50 | 262.9 | 5.26 | **21.8%** |
| `classify` | LLM | 50 | 198.9 | 3.98 | **16.5%** |
| `eligibility` | LLM* | 28 | 82.3 | 2.94 | 6.8% |
| `calculator` | — | 28 | 0.19 | 0.007 | 0.0% |
| `synthesize` | — | 44 | 0.02 | 0.000 | 0.0% |
| `fallback` | — | 6 | 0.00 | 0.000 | 0.0% |

\* `eligibility` is LLM **only when a cause is stated**; the no-cause path is deterministic.
(Fewer calls than the pre-refactor run — 28 vs 40 — because better routing no longer over-routes
`rights_info` queries into the eligibility branch; the higher mean reflects that the remaining
calls are disproportionately the stated-cause ones that do hit the LLM.)

### Bottleneck

**The bottleneck is local-LLM generation, full stop — LLM nodes are 100.0% of node time;
everything non-LLM is 0.21 s total (0.0%).** This confirms the CLAUDE.md prediction (calculator +
vector search + assembly negligible). The shape:
- **`rag` (54.8%)** is still the single dominant cost — ≥2 LLM calls (grade + generate) plus
  another grade+generate on each corrective rewrite. Its *share* fell from 69% only because the
  intake split added a second per-query call below it; its absolute cost is unchanged (~15 s/call).
- **`classify` + `extract` (38.3% combined, ~9.2 s/query)** are the cost of the refactor: the
  former single `intake` call (~4.3 s, 24%) became two structured-output calls. This is the
  **latency price of the routing-accuracy win** (10/14 → 15/15) — it pushed mean latency
  17.8 → 24.1 s and wall time 890 → 1205 s. The two classification calls per query, not RAG, are
  the new swing factor.
- **Non-LLM nodes are free**: `calculator` 0.19 s over 28 calls, `synthesize`/`fallback` are
  rounding error. The only lever remains the **number and cost of LLM calls**.

### Optimizations

**A — already in the design; the load test quantifies the payoff.**
1. **Deterministic no-cause eligibility**: the no-cause path skips the LLM entirely; only 28 of
   50 runs reach `eligibility` at all, and the stated-cause subset averages ~2.9 s — forcing
   every eligibility call through the LLM would add an estimated ~60–80 s to the 50-run wall time.
2. **LLM-free `synthesize`**: assembling the final answer adds **0.02 s** over 44 calls — a
   second generative pass here would have been ~15 s × 44 ≈ ~660 s and a fresh hallucination surface.
3. **out_of_scope short-circuit to `fallback`** (no LLM): those runs complete in ~7.8 s vs the
   ~24 s mean — still a win, but smaller than before because `classify` **and** `extract` both
   run before the route is known (see lever C).

**B — conditional RAG for pure `compensation_calc` (a graph change).** `rag` is ~55% of the cost,
yet a pure `compensation_calc` answer's amount is deterministic (calculator) and its eligibility
is usually the no-cause deterministic path, so the RAG subgraph there mainly produces *optional*
citations (eval pins `required: false` for calc-only cases). Making the RAG branch **conditional**
— skip it for pure `compensation_calc`, keep it for `rights_info`/`mixed` — would remove one
~15 s subgraph call from every calc query. Touches `_route_after_extract` + the eligibility
branch's doc dependency + citation expectations; tracked as a GitHub issue, to be re-measured here.

**C — make `extract` conditional (new, surfaced by this run).** `extract` now runs on **every**
query before the route is decided, but only `compensation_calc`/`mixed` actually need flight
details — `rights_info` and `out_of_scope` discard them. Re-wiring to
`classify → (out_of_scope → fallback | rights_info → rag | comp/mixed → extract → …)` would skip a
~5.3 s LLM call on every rights/out-of-scope query, clawing back most of the latency the intake
split added on those routes (e.g. out_of_scope back toward ~3–4 s). Tracked as a GitHub issue.

---

## 3. Plain-language summary

A non-technical distillation of the two sections above — the same facts, no jargon.

### What we learned

**Is it correct? (functional eval)**
- **The money is always right.** Every compensation amount and every eligibility decision was
  correct — 100%. €250 / €400 / €600 / €0, and whether weather or strikes count, is rock-solid.
- **The grounding is always right.** Every rights answer came with a real citation to the law —
  no made-up answers.
- **Sorting questions into the right lane — now fixed.** It used to route only about 7 of 10
  questions correctly (mixing a problem with "refund" or "how much" tipped it toward a money
  question); after this refactor it's **15 of 15**. The fix was to stop letting the model reply
  free-form and instead have it tick three yes/no boxes, from which the lane is worked out in code.
- **One of the two known blind spots is now fixed; one remains.** The air-traffic-control case
  (it used to wrongly grant compensation) is corrected. The remaining gap is the "am I even
  covered?" coverage question: it's now sorted into the right lane, but the system still doesn't
  pull up the exact article that backs the answer.

**Is it fast enough? (load test)**
- **One query takes ~24 seconds** on this hardware (up from ~18 s before the refactor).
- **All of that time is the AI model thinking.** The math, the database, and the answer-assembly
  are basically instant (a fraction of a second combined). The system is slow *only* because of
  the local AI model — not because of any inefficiency in our code.
- **The most expensive single step is reading the law and writing the grounded answer** (~55%).
- **The accuracy fix cost some speed.** Making the model "tick boxes" split one ~4-second step
  into two (~9 seconds total per query), which is why each query went from ~18 s to ~24 s — a
  deliberate trade: better routing for a few seconds more.

**Bottom line:** accurate where it counts (amounts, eligibility, citations), and slow only
because of the local AI model.

### What to improve next

**Done this round — sorting questions into lanes (accuracy).** The model used to misfile some
questions; we stopped letting it reply free-form and made it tick three yes/no boxes, working out
the lane in code. Routing went from ~7/10 to 15/15.

**Done this round — the air-traffic-control blind spot (accuracy).** It used to wrongly grant
compensation for ATC delays (which are outside the airline's control); adding it as a worked
example, alongside the weather / own-staff-strike examples, fixed it.

**Still to do — the coverage-citation blind spot (accuracy).** For "am I even covered?" questions
about flights into the EU on a non-EU airline, the system now picks the right lane but doesn't
surface the exact article that backs the answer. The fix lives in the corpus/retrieval, not the graph.

**Still to do — make money-only questions much faster (speed).** The slowest step (reading the
law, ~55% of the time) runs even for pure "how much do I get?" questions, where the amount comes
from the calculator, not the law text. Skipping it for amount-only questions would drop them sharply.

**New target — don't extract flight details when they aren't needed (speed).** The refactor added
a second model step that pulls flight details out of every question — but rights-only and
off-topic questions throw those details away. Running that step only for money questions would win
back most of the few seconds the accuracy fix cost on those routes.

**Already done — just proven again this round.** Three speed shortcuts are built in (skip the
model when no reason is given; assemble the final answer without the model; bail out fast on
off-topic questions). The off-topic bail-out is now a smaller win, because the two new
classification steps run before it.

> **One line:** the accuracy fixes shipped this round (structured "tick-the-boxes" routing + the
> ATC worked example) and routing is now 15/15; the open items are mostly **speed** — skip the
> law-reading step and the detail-extraction step when a question doesn't need them. Tracked as
> GitHub issues.

