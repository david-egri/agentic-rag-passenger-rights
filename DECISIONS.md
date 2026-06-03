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

## 2026-06-03 — Python pin moved 3.12 → 3.14  (`python-314`)
**[revisit]** The local machine only had Python **3.14.5** installed (no 3.12). Rather than `brew install python@3.12`, we moved the pin to **3.14**: `.python-version` = `3.14`, and the Docker base becomes `python:3.14-slim` (Phase 6). Supersedes the 3.12 decision in [[python-env]].
**Why:** Lowest-friction path on the available machine; 3.14 had native cp314 wheels for the entire Phase 1 stack (streamlit 1.58, langchain-ollama 1.1, pydantic, numpy, pyarrow) — `pip install` resolved cleanly with no source builds.
**Revisit if:** Phase 2 ML deps (chromadb, sentence-transformers, torch) lack cp314 wheels → fall back to 3.13 or 3.12 (would then require installing that interpreter). This is the main open risk of the 3.14 choice.
Related: [[python-env]], [[build-approach-ui-spine]].

## 2026-06-03 — Local model tag is `qwen2.5:3b-instruct`  (`model-tag`)
**[decision]** `config.yaml` `model` defaults to **`qwen2.5:3b-instruct`** — the tag already pulled locally — rather than the canonical `qwen2.5:3b` written in the docs. Same underlying Qwen2.5 3B Instruct model; avoids a redundant ~1.9 GB pull. Refines [[llm-model]].
**Why:** The instruct tag was already present in Ollama; `qwen2.5:3b` resolves to the same instruct weights anyway. The `model` knob keeps it swappable, so the literal string is not load-bearing.
Related: [[llm-model]].

## 2026-06-03 — Working agreement: plan-first, user drives commits/merges  (`working-agreement`)
**[decision]** Per-phase loop: orient (read PLAN next phase + skim DECISIONS) → **post a short plan and wait for approval before coding** → branch+push → build (ticking PLAN, logging to DECISIONS) → **the user explicitly triggers every commit, merge, and tag** (never autonomous, even mid-phase) → on approval, update PLAN status and do the merge/tag/push. Documented in CLAUDE.md (Working agreement).
**Why:** Keeps the user in control of integration and history, and makes the collaboration loop survive fresh contexts (a cold agent otherwise wouldn't know to plan-first or that the user drives commits). Matches the rhythm used while planning.
**Revisit if:** the user later wants faster cycles (e.g. autonomous checkpoint commits on the branch, or just-build for small phases).
Related: [[git-workflow]].

## 2026-06-03 — Pinned LLM: qwen2.5:3b (constrained hardware)  (`llm-model`)
**[revisit]** Default Ollama model pinned to **`qwen2.5:3b`** (Qwen2.5 3B Instruct); `llama3.2:3b` is the alternative. `config.yaml` `model` knob makes it swappable.
**Why:** User confirmed constrained hardware, so 3B is the tier. Qwen2.5 3B has good structured/JSON-output adherence, which matters for intake (JSON), router, and the RAG grader. Reproducibility non-negotiable wants a concrete pin, not a candidate list.
**Revisit if:** routing/extraction reliability or generation quality proves weak at 3B → bump to a 7–8B instruct model (Llama 3.1 8B / Qwen2.5 7B), or split models (small for routing/extraction, larger for final generation). Also revisit if a different model handles structured output more reliably.
Related: [[drop-dummy-llm]].

## 2026-06-03 — Git workflow: phase branches, merge commits, phase tags  (`git-workflow`)
**[decision]** One branch per phase named `phase/N-slug`; integrate into `main` via `--no-ff` merge commits; annotate each phase's merge commit with a `phase-N-slug` tag; keep phase branches (don't delete) and push `main` + branches + tags. Non-phase branches use `type/slug` (`fix/`, `docs/`, `chore/`, `refactor/`, `spike/`), chosen per case. Full convention in CLAUDE.md (Git workflow).
**Why:** Merge commits keep a visible per-phase boundary in history; tags make each completed phase a referenceable checkpoint (easy to diff/checkout a phase); kept+pushed branches preserve the per-phase record on the remote. Matches the branch-per-phase plan and the documentation-routing setup.
**How to apply:** branch from up-to-date `main`; publish the branch early; `git merge --no-ff` then `git tag -a phase-N-slug`; push `main`, the branch, and the tag.
Related: [[build-approach-ui-spine]].

## 2026-06-03 — Drop the dummy LLM backend for now (keep the seam)  (`drop-dummy-llm`)
**[revisit]** No dummy/stub LLM backend is built. Only `ollama` is wired — but behind a pluggable `LLM_BACKEND` seam (`get_llm()`), so one can be added later as a single backend branch.
**Why:** The brief only offers the dummy as a *hardware fallback* ("if [a real local LLM] is not possible"), which isn't our situation. Its one genuine engineering benefit — isolating LLM latency in the load test — is a late-phase concern, so carrying a stub (and its per-call-site structured stubs) through P1–P4 is cost without payoff. The bottleneck analysis will instead lean on per-node timing from the trace.
**How to apply:** Nodes must call the `get_llm()` abstraction, never Ollama directly, so the seam stays cheap to extend. Don't scatter Ollama client calls across nodes.
**Revisit if:** the load test's per-node timing isn't conclusive enough to pin the bottleneck → add a stub backend for a clean real-vs-stub A/B. (Also the original fallback reason returns if the target hardware can't run the chosen model.)
Related: [[build-approach-ui-spine]], [[python-env]].

## 2026-06-03 — Python env: venv + pinned requirements + Python 3.12  (`python-env`)
**[decision]** Local env is stdlib **`venv`** with deps pinned in **`requirements.txt`**; Python pinned to **3.12** via `.python-version`; the Dockerfile uses `python:3.12-slim` so local and container match. No Poetry/conda/uv. Resolves the old `requirements.txt / pyproject.toml` ambiguity in the proposal repo tree → `requirements.txt`.
**Why:** Lowest-ceremony option consistent with the "no Make / plain commands" stance, no extra tooling for a reviewer to install, and it closes the reproducibility gaps the docs had left open (no isolation strategy, no Python version pin). 3.12 has solid wheel support across LangGraph/Chroma/sentence-transformers.
**How to apply:** `python3.12 -m venv .venv && . .venv/bin/activate` then `pip install -r requirements.txt`. Keep `.python-version` and the Dockerfile base in sync at 3.12.
**Revisit if:** a dependency lacks a 3.12 wheel (fall back to 3.11) or native/ML deps turn painful via pip (consider conda).
Related: [[build-approach-ui-spine]].

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
**Why:** The UI-as-spine keeps every stage runnable and demonstrable, and doubles as the functional-test harness — which is why functional testing through it is sufficient for most of the app. LLM-first de-risks the Ollama backend immediately and gives something runnable on day one. Make added ceremony without value for a prototype this size. Reordering breaks no acceptance criteria (those constrain the final artifact, not build order).
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
