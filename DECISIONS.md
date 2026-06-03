# DECISIONS.md

Running log of implementation decisions and insights — trade-offs made, arbitrary choices that need revisiting, and anything non-obvious worth remembering. Append new entries at the top. Keep each entry short and dated.

Tag entries so they're easy to scan:
- **[trade-off]** — a deliberate compromise (what we gave up and why)
- **[revisit]** — an arbitrary/placeholder choice that must be revised later
- **[gotcha]** — surprising behavior or a non-obvious constraint
- **[decision]** — a settled choice worth recording so it isn't re-litigated

Format:

```
## YYYY-MM-DD — short title
**[tag]** What was decided/observed.
**Why:** the reasoning or constraint that forced it.
**Revisit if:** (for [revisit]) the condition that should trigger a second look.
```

---

<!-- Add entries below, newest first. -->

## 2026-06-03 — Streamlit UI evolves as one-tab-per-layer  (`ui-tabs-per-layer`)
**[decision]** The UI is a tabbed app that gains a tab each phase: **Chat (LLM)** → **Corpus** → **RAG** → **Calculator** → **Agent**. The first four are inspector/dev-demo tabs; the **Agent** tab is the product and is the one that satisfies the task's UI requirement (agent steps + RAG result).
**Why:** Keeps every layer independently runnable and demonstrable (great for a live walkthrough and as the functional-test harness), and makes otherwise-invisible scoring criteria visible — the Corpus tab shows "quality processing"/structure-aware chunking; the RAG tab surfaces the corrective grade→rewrite loop (the most "agentic" behaviour). Over-delivers on the deliberately-minimal brief without much cost.
**How to apply:**
- Build display components **once** (chunk card, citation list, trace-step renderer) and reuse them in the RAG and Agent tabs so they can't drift.
- Persistent **sidebar** (not a tab) shows active backend / model / top-k.
- Inspector tabs handle the **not-built-yet/empty** state gracefully (corpus not ingested, no Chroma) so a fresh clone doesn't error.
**Revisit if:** tab count or per-tab complexity starts to sprawl — then group inspectors behind a single "Pipeline inspector" tab and keep Agent as the top-level product.
Related: [[build-approach-ui-spine]].

## 2026-06-03 — Build approach: Streamlit-as-spine, reordered, no Make, functional-first  (`build-approach-ui-spine`)
**[decision]** Reworked the build order and process: (1) **Streamlit is the spine** — a minimal chat UI exists from Phase 1 and gains a visualization each phase; (2) **reordered** to LLM backend + chat → corpus + RAG → calculator → agentic assembly → eval + load test → Docker + README; (3) **dropped Make** in favor of plain documented commands; (4) **functional testing** (through the UI + the 15-Q eval) over classical unit tests.
**Why:** The UI-as-spine keeps every stage runnable and demonstrable, and doubles as the functional-test harness — which is why functional testing through it is sufficient for most of the app. LLM-first de-risks the Ollama/dummy switch immediately and gives something runnable on day one. Make added ceremony without value for a prototype this size. Reordering breaks no acceptance criteria (those constrain the final artifact, not build order).
**Exceptions / guards:**
- The **calculator keeps a small direct test set** — it's deterministic, trivially testable, and produces the compensation amounts (and eval ground truth); a wrong euro figure is the worst failure mode, so verifying it only through a chat box is too weak.
- The retrieval tool (`retrieve_passenger_rights`) is born in the **corpus/RAG** phase (the subgraph uses it); the dedicated tools phase is the **calculator**.
- The required **functional eval (15 Qs), load test, Docker, and README** remain as explicit late phases — they're graded deliverables; the eval is itself a functional test.
- **Reproducibility** is independent of Make and still holds: pinned versions, `temperature=0`, idempotent ingest, frozen corpus.
**Revisit if:** the app grows enough that manual/functional verification stops catching regressions — then add targeted tests at the seams (RAG grading, router classification).

## 2026-06-03 — Calculator is eligibility-agnostic; gating happens at fan-in
**[decision]** In the `mixed` path, the eligibility branch and the calculator branch are siblings that run independently and converge at `synthesize`; the calculator does **not** depend on eligibility.
**Why:** This resolves the apparent contradiction "why compute an amount before eligibility is fixed?" The two branches consume *different* inputs — eligibility needs the disruption *reason* + rules (RAG); the calculator needs only route + delay. Neither consumes the other's output. The dependency is a **combination dependency at fan-in** (`final = eligible ? candidate_amount : 0`), not an input dependency between branches — which is exactly what fan-out → fan-in expresses. The calculator therefore computes the **statutory candidate amount** (what Art. 7 awards for that distance band + delay), and the gate is applied at merge. Computing an amount that may be zeroed is free (deterministic, no LLM) and useful: it lets synthesize give a counterfactual ("you'd ordinarily be owed €400, but the cause was weather → no compensation, though care/rerouting still apply").
**Revisit if:** the calculator's contract ever changes to return the *final* amount owed (consuming eligibility) — then the branches are no longer independent, the fan-out collapses to a sequential gate, and the "independent execution" demonstration is lost. Keep the calculator eligibility-agnostic.
**Note:** The §4.3 ASCII diagram has been redrawn (2026-06-03) to show two sibling branches (RAG→eligibility, calculator) fanning in at synthesize, with the gate applied there.

## 2026-06-03 — "Agentic" = directed/structured agent, not open-ended planner
**[decision]** The agent's control flow is governed by the LangGraph structure (router dispatches, edges decide branches), rather than an open-ended planner that freely selects tools at runtime.
**Why:** Predictability and testability matter more than open-ended autonomy for an evaluable interview prototype. The task explicitly equates "agentic" with conditional routing + decomposition + state, all of which this satisfies. The corrective-RAG grade→rewrite loop is the most defensibly "agentic" element. Be ready to articulate this as a deliberate trade-off if probed.
**Revisit if:** the goal shifts toward demonstrating open-ended/model-driven tool selection — then add an LLM tool-calling step (e.g. intake autonomously invoking the calculator) to strengthen the claim.

## 2026-06-03 — Router is an explicit node, not a bare conditional edge
**[decision]** Implement the router as a genuine state-updating node that writes its routing decision into `state`, with the conditional branch as the edge *after* it.
**Why:** Costs nothing, removes the node-vs-edge inconsistency in the original proposal, and makes the routing choice visible in the Streamlit trace/"agent steps" panel — which directly scores the "demonstrate agent operation" requirement.
