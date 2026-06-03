# PLAN.md

The living implementation plan — **what** we're building and **when**, plus current status. This is the one place to update as work progresses. It is forward-looking; the *why* behind any change to the plan goes in `DECISIONS.md` (link it from the relevant phase). See the Document map in `CLAUDE.md` for how the docs divide responsibility.

**Workflow:** one branch per phase. Each phase's PR ticks that phase's boxes here and refines the *next* phase with whatever was learned. Keep upcoming phases editable — they are expected to change.

**Status legend:** `[ ]` todo · `[~]` in progress · `[x]` done · `[!]` blocked/needs decision

---

## Phase 0 — Project docs & design  `[x]`
**Goal:** Lock the design and the working agreement before writing code.
- [x] PROJECT_PROPOSAL.md (design rationale)
- [x] CLAUDE.md (working agreement, guardrails, non-negotiables)
- [x] DECISIONS.md (decision log) + this PLAN.md
- [x] Graph diagram reflects router-as-node + independent fan-out branches

## Phase 1 — Scaffold + LLM backend + Makefile  `[ ]`
**Goal:** Runnable skeleton with the dummy backend so everything downstream is testable offline.
- [ ] Repo scaffold per PROJECT_PROPOSAL §11 (src/, app/, eval/, data/)
- [ ] `config.yaml` + env loading (no hardcoded knobs)
- [ ] `src/llm.py` with `LLM_BACKEND=ollama|dummy` switch
- [ ] Makefile targets: install, ingest, run, eval, loadtest, test
**Done when:** `make install` works and the dummy backend returns canned responses.

## Phase 2 — Calculator + unit tests  `[ ]`
**Goal:** Deterministic, LLM-free compensation tool — the eval ground truth. Build first.
- [ ] `calculate_compensation` as an explicit `@tool` (haversine → band → amount → 3h threshold + 50% rule)
- [ ] Eligibility-agnostic: returns the **candidate** amount (gate lives in synthesize) — see DECISIONS
- [ ] Unit tests: distance bands, threshold, reduction, boundary routes (~1500 km)
**Done when:** `make test` passes with recomputed-from-real-coords expectations.

## Phase 3 — Ingestion → ChromaDB  `[ ]`
**Goal:** Structure-aware, **drop-in** corpus loader (scalable integration).
- [ ] Generic directory loader: detect type → dispatch to matching structure-aware chunker
- [ ] Per-chunk metadata (source, article, title, url, retrieved_at, chunk_id)
- [ ] Idempotent persist to `data/chroma/`; commit frozen corpus + `data/SOURCES.md`
- [ ] Sanity-check retrieval on 2–3 queries
**Done when:** dropping a new file into `data/corpus/` + `make ingest` indexes it with no code changes.

## Phase 4 — RAG subgraph (corrective RAG), standalone  `[ ]`
**Goal:** Modular, grounded, cited retrieval that self-corrects.
- [ ] Compiled `StateGraph`: retrieve → grade → (rewrite → retrieve, bounded) → generate
- [ ] `retrieve_passenger_rights` as an explicit `@tool`
- [ ] Citations from metadata; refuses when support is insufficient
**Done when:** subgraph answers grounded + cited in isolation.

## Phase 5 — Main graph + router + state  `[ ]`
**Goal:** Wire the full agent.
- [ ] Typed `AgentState`; nodes: intake, router (writes decision to state), planner, eligibility, calculator, synthesize, fallback
- [ ] RAG subgraph attached via `add_node`
- [ ] `mixed`/`compensation_calc` as fan-out → fan-in; gate applied at synthesize
**Done when:** all four routes produce correct end-to-end behavior.

## Phase 6 — Streamlit UI with trace panel  `[ ]`
**Goal:** Demonstrate agent operation.
- [ ] `graph.stream` → append each node's output to the trace panel
- [ ] Show query_type, decomposition, retrieved chunks, eligibility rationale, calc result, citations, disclaimer
**Done when:** a mixed query visibly walks through the nodes in the UI.

## Phase 7 — Functional eval (15 Qs)  `[ ]`
**Goal:** Measure correctness; iterate prompts.
- [ ] `eval/eval_set.yaml` (15 Qs + ground truth) — calculator outputs as ground truth
- [ ] `functional_eval.py` + methodology write-up
**Done when:** eval runs via `make eval` and results are recorded.

## Phase 8 — Load test (50–200 queries)  `[ ]`
**Goal:** Latency + bottleneck analysis.
- [ ] Load test supporting `LLM_BACKEND=dummy` to isolate LLM time
- [ ] Report latency metrics + bottleneck + 1–2 optimizations
**Done when:** `make loadtest` produces the numbers and the write-up.

## Phase 9 — Docker + compose  `[ ]`
- [ ] Dockerfile
- [ ] docker-compose.yml (app + ollama) — bonus
**Done when:** `docker compose up` runs end-to-end.

## Phase 10 — README  `[ ]`
**Goal:** Complete, reproducible entry point. Write last.
- [ ] Problem, architecture + design justification, eval/perf summary, install/run, reform caveat
**Done when:** a fresh clone can be set up and run from the README alone.

---

## Changes & findings log
Append plan-affecting changes here (with a link to the DECISIONS.md entry that explains *why*). Keeps the phase sections clean while preserving the trail.

- _none yet_
