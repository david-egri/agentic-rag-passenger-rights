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

## 2026-06-03 — Calculator is eligibility-agnostic; gating happens at fan-in
**[decision]** In the `mixed` path, the eligibility branch and the calculator branch are siblings that run independently and converge at `synthesize`; the calculator does **not** depend on eligibility.
**Why:** This resolves the apparent contradiction "why compute an amount before eligibility is fixed?" The two branches consume *different* inputs — eligibility needs the disruption *reason* + rules (RAG); the calculator needs only route + delay. Neither consumes the other's output. The dependency is a **combination dependency at fan-in** (`final = eligible ? candidate_amount : 0`), not an input dependency between branches — which is exactly what fan-out → fan-in expresses. The calculator therefore computes the **statutory candidate amount** (what Art. 7 awards for that distance band + delay), and the gate is applied at merge. Computing an amount that may be zeroed is free (deterministic, no LLM) and useful: it lets synthesize give a counterfactual ("you'd ordinarily be owed €400, but the cause was weather → no compensation, though care/rerouting still apply").
**Revisit if:** the calculator's contract ever changes to return the *final* amount owed (consuming eligibility) — then the branches are no longer independent, the fan-out collapses to a sequential gate, and the "independent execution" demonstration is lost. Keep the calculator eligibility-agnostic.
**Note:** The §4.3 ASCII diagram still shows `calculator → eligibility`, which wrongly implies a dependency. To be redrawn as two sibling branches gated at synthesize.

## 2026-06-03 — "Agentic" = directed/structured agent, not open-ended planner
**[decision]** The agent's control flow is governed by the LangGraph structure (router dispatches, edges decide branches), rather than an open-ended planner that freely selects tools at runtime.
**Why:** Predictability and testability matter more than open-ended autonomy for an evaluable interview prototype. The task explicitly equates "agentic" with conditional routing + decomposition + state, all of which this satisfies. The corrective-RAG grade→rewrite loop is the most defensibly "agentic" element. Be ready to articulate this as a deliberate trade-off if probed.
**Revisit if:** the goal shifts toward demonstrating open-ended/model-driven tool selection — then add an LLM tool-calling step (e.g. intake autonomously invoking the calculator) to strengthen the claim.

## 2026-06-03 — Router is an explicit node, not a bare conditional edge
**[decision]** Implement the router as a genuine state-updating node that writes its routing decision into `state`, with the conditional branch as the edge *after* it.
**Why:** Costs nothing, removes the node-vs-edge inconsistency in the original proposal, and makes the routing choice visible in the Streamlit trace/"agent steps" panel — which directly scores the "demonstrate agent operation" requirement.
