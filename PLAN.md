# PLAN.md

The living implementation plan — **what** we're building and **when**, plus current status. This is the one place to update as work progresses. It is forward-looking; the *why* behind any change to the plan goes in `DECISIONS.md` (link it from the relevant phase). See the Document map in `CLAUDE.md` for how the docs divide responsibility.

**Workflow:** one branch per phase. Each phase's PR ticks that phase's boxes here and refines the *next* phase with whatever was learned. Keep upcoming phases editable — they are expected to change.

**Build philosophy (see DECISIONS):**
- **Streamlit is the spine — a tab per layer.** The UI exists from Phase 1 and gains a **new tab** each phase (Chat → Corpus → RAG → Calculator → Agent), so every layer stays independently runnable and demonstrable. The first four are **inspector tabs** (dev/demo surfaces); the **Agent** tab is the product that satisfies the task's UI requirement. Build display pieces once (chunk card, citation list, trace-step renderer) and reuse across tabs. The UI doubles as the functional-test harness.
- **Functional over unit tests.** Verify real functionality by exercising it (through the UI and the 15-Q eval) rather than classical unit tests. **One exception:** the deterministic calculator keeps a small direct test set.
- **No Make.** Run things with plain, documented commands (kept in this file + README). Reproducibility still holds: pinned versions, `temperature=0`, idempotent ingest, frozen corpus.

**Status legend:** `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked/needs decision

---

## Phase 0 — Project docs & design  `[x]`
**Goal:** Lock the design and the working agreement before writing code.
- [x] PROJECT_PROPOSAL.md (design rationale)
- [x] CLAUDE.md (working agreement, guardrails, non-negotiables, document map)
- [x] DECISIONS.md (decision log) + this PLAN.md
- [x] Graph diagram reflects router-as-node + independent fan-out branches

## Phase 1 — LLM backend + minimal chat UI  `[ ]`
**Goal:** A runnable spine on day one — talk to the model directly.
- [ ] Python env: `.python-version` pinned to **3.12**, stdlib `venv`, pinned `requirements.txt` (no Poetry/conda/uv)
- [ ] `src/llm.py` with `LLM_BACKEND=ollama|dummy` switch; `temperature=0`
- [ ] `config.yaml` + env loading (model names, Ollama URL, top-k — no hardcoding)
- [ ] Streamlit app shell (`app/streamlit_app.py`) with a tab layout + a **Chat (LLM)** tab wired to the LLM
- [ ] Sidebar showing active backend / model / top-k (persistent across tabs)
- [ ] Pinned `requirements.txt`; run command documented (`streamlit run app/streamlit_app.py`)
**Done when:** you can chat with both backends from the Chat tab; dummy works fully offline.

## Phase 2 — Corpus + RAG subgraph  `[ ]`
**Goal:** Grounded, cited retrieval that self-corrects — visible in the UI.
- [ ] Ingestion: generic **drop-in directory loader** → structure-aware chunkers → metadata → ChromaDB (idempotent)
- [ ] Commit frozen corpus + `data/SOURCES.md`
- [ ] `retrieve_passenger_rights` as an explicit `@tool` (the retrieval tool lives here, with RAG)
- [ ] Corrective-RAG subgraph (compiled `StateGraph`): retrieve → grade → (rewrite → retrieve, bounded) → generate
- [ ] **UI gains — Corpus tab:** browse chunks per document, structure boundaries (Article/Recital), per-chunk metadata, counts (makes "quality processing" visible)
- [ ] **UI gains — RAG tab:** query → retrieved chunks (scores + metadata) → grade decision → rewritten query (if any) → generated answer + citations (surfaces the corrective loop)
**Done when:** dropping a file into `data/corpus/` + re-running ingestion indexes it with no code changes; Corpus + RAG tabs render and answers are grounded + cited.

## Phase 3 — Calculator (the non-retrieval tool)  `[ ]`
**Goal:** Deterministic compensation tool — the factual backbone and eval ground truth.
- [ ] `calculate_compensation` as an explicit `@tool` (haversine → band → amount → 3h threshold + 50% rule)
- [ ] **Eligibility-agnostic:** returns the candidate amount; gate lives in synthesize (see DECISIONS)
- [ ] Small direct test set (the one classic-test exception): band boundaries (~1500 km), threshold, reduction
- [ ] **UI gains — Calculator tab:** flight inputs → distance / band / amount, for functional verification
**Done when:** the test set passes with recomputed-from-real-coords expectations; Calculator tab works.

## Phase 4 — Agentic assembly (end goal)  `[ ]`
**Goal:** Put it together into the agentic-RAG graph.
- [ ] Typed `AgentState`; nodes: intake, router (writes decision to state), planner, eligibility, calculator, synthesize, fallback
- [ ] RAG subgraph attached via `add_node`
- [ ] `mixed`/`compensation_calc` as fan-out → fan-in; gate applied at synthesize
- [ ] **UI gains — Agent tab (the product):** full node-by-node trace (`graph.stream`) + final grounded answer + citations + "not legal advice" disclaimer — satisfies the task's UI requirement (agent steps + RAG result). Reuses the chunk/citation/trace components from earlier tabs.
**Done when:** all four routes work end-to-end and the Agent tab visibly walks the nodes.

## Phase 5 — Functional eval + load test  `[ ]`
**Goal:** Measure correctness and latency (both are graded deliverables; the eval is itself a functional test).
- [ ] `eval/eval_set.yaml` (15 Qs + ground truth) + an eval runner; methodology write-up
- [ ] Load test (50–200 queries) supporting `LLM_BACKEND=dummy` to isolate LLM time
- [ ] Latency metrics + bottleneck + 1–2 optimizations
**Done when:** eval and load test run via documented commands and results are recorded.

## Phase 6 — Docker + README  `[ ]`
**Goal:** Reproducible entry point.
- [ ] Dockerfile + docker-compose.yml (app + ollama)
- [ ] README: problem, architecture + design justification, eval/perf summary, install/run, reform caveat
**Done when:** `docker compose up` runs end-to-end and a fresh clone can be set up from the README alone.

---

## Changes & findings log
Append plan-affecting changes here (with a link to the DECISIONS.md entry that explains *why*). Keeps the phase sections clean while preserving the trail.

- 2026-06-03 — Reordered build: UI-as-spine, LLM-first, corpus/RAG → calculator → agentic assembly; dropped Make; functional-testing with a calculator exception. See DECISIONS `build-approach-ui-spine`.
