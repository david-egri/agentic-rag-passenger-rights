# PLAN.md

The living implementation plan — **what** we're building and **when**, plus current status. This is the one place to update as work progresses. It is forward-looking; the *why* behind any change to the plan goes in `DECISIONS.md` (link it from the relevant phase). See the Document map in `CLAUDE.md` for how the docs divide responsibility.

**Workflow:** one branch per phase (`phase/N-slug`), merged into `main` with a `--no-ff` merge commit that gets an annotated `phase-N-slug` tag; phase branches are kept and pushed. See the Git workflow section in `CLAUDE.md` for the full convention. Each phase merge ticks that phase's boxes here and refines the *next* phase with whatever was learned. Keep upcoming phases editable — they are expected to change.

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

## Phase 1 — LLM backend + minimal chat UI  `[x]`
**Goal:** A runnable spine on day one — talk to the model directly.
- [x] Python env: `.python-version` pinned to **3.14** (3.12 unavailable locally — see DECISIONS `python-314`), stdlib `venv`, pinned `requirements.txt` (no Poetry/conda/uv)
- [x] `.gitignore`: `.venv/`, `__pycache__/`, `*.pyc`, `data/chroma/` (chroma is derived, rebuilt from corpus)
- [x] Model present: `qwen2.5:3b-instruct` already pulled in Ollama (tag note — see DECISIONS `model-tag`)
- [x] `src/llm.py` exposing a single `get_llm()` behind an `LLM_BACKEND` seam (only `ollama` wired now; keep it pluggable so a stub can be added later); `temperature=0`
- [x] `config.py` — constants + env override for knobs: `LLM_BACKEND`, `MODEL` (`qwen2.5:3b-instruct`), `OLLAMA_URL`, `TEMPERATURE`, `TOP_K`, `REWRITE_MAX_RETRIES`, `EMBEDDING_MODEL` (no hardcoding; env wins) — simplified from a config.yaml+Config class, see DECISIONS `simplify-p1`
- [x] Streamlit app shell (`streamlit_app.py`, repo root) with a tab layout (Chat active; Corpus/RAG/Calculator/Agent graceful placeholders) + a **Chat (LLM)** tab wired to the LLM (streamed)
- [x] Sidebar showing active backend / model / top-k (persistent across tabs)
- [x] Pinned `requirements.txt`; run command documented (`streamlit run streamlit_app.py`)
**Done when:** you can chat with the `qwen2.5:3b-instruct` model from the Chat tab. ✅ verified — round-trip + streaming through `get_llm()` and headless Streamlit boot (HTTP 200).

## Phase 2 — Corpus + RAG subgraph  `[x]`
**Goal:** Grounded, cited retrieval that self-corrects — visible in the UI.
- [x] Ingestion (`src/ingest.py`): generic **drop-in directory loader** → content-detected type → structure-aware chunkers (regulation Article/Recital · Commission-notice numbered sections · semantic HTML `<h1>`–`<h4>` headings · Markdown headings) + paragraph-overlap size guard → citation metadata → ChromaDB (idempotent rebuild). Embeddings reuse local Ollama (`src/store.py`).
- [x] Freeze corpus — 4 docs: reg 261/2004 + **2024** interpretative guidelines + EUR-Lex legislative summary (`LEGISSUM:l24173`) + Your Europe plain-language summary — + `data/SOURCES.md` + `data/corpus/sources.json`. **Note:** `/data/` is gitignored for now (user decision) — corpus stays local, **not committed**; commit-vs-fetch decision deferred to Phase 7. See DECISIONS `gitignore-data-for-now`.
- [x] `retrieve_passenger_rights` as an explicit `@tool` (`src/tools.py`)
- [x] Corrective-RAG subgraph (`src/rag.py`, compiled `StateGraph`): retrieve → grade → (rewrite → retrieve, bounded by `REWRITE_MAX_RETRIES`) → generate; LLM grader + cosine-distance safety floor; generate is grounded (no outside knowledge / invented figures)
- [x] **UI — Corpus tab:** counts, per-document chunk browse with Article/Recital/Section labels, per-chunk metadata, filter; graceful "not ingested" state
- [x] **UI — RAG tab:** query → corrective-RAG trace (retrieve hits → grade verdict → rewrite → generate) → grounded answer + citations + disclaimer; retrieved passages with distances. Reusable components in `ui_components.py`.
**Done when:** dropping a file into `data/corpus/` + re-running ingestion indexes it with no code changes; Corpus + RAG tabs render and answers are grounded + cited. ✅ verified — drop-in test (new `.md` → indexed → retrievable, no code change), grader/grounding behaviour exercised, headless Streamlit boot HTTP 200.
**Note:** 3B generation quality is the limiting factor on answer polish (architecture is sound); calibrate the grader floor + consider a larger model in Phase 6 eval. See DECISIONS `rag-grader`, `embeddings-ollama`, `corpus-2024-guidelines`, `python-314-resolved`.
**Parked polish:** OJ-notice citation labels for unnumbered dash sub-headings render as `Section · — Strikes by airline staff` (em-dash leaks in; no section number). Tidy later — ideally have dash sub-headings inherit their parent numbered section (`Section 4.3.3 · Strikes by airline staff`); affects `chunk_notice` + a re-ingest (local `data/chroma/` only).

## Phase 3 — Calculator (the non-retrieval tool)  `[x]`
**Goal:** Deterministic compensation tool — the factual backbone and eval ground truth.
- [x] `calculate_compensation` as an explicit `@tool` (`src/tools.py`, thin wrapper over pure `src/calculator.py`: haversine → band → amount → 3h threshold + 50% rule); LLM-free
- [x] **Eligibility-agnostic:** returns the candidate amount; gate lives in synthesize (see DECISIONS). `threshold_met`/`reduction_applied` are mechanical (distance/delay/rerouting), never the extraordinary-circumstances gate
- [x] Small direct test set (`tests/test_calculator.py`, the one classic-test exception): band boundaries (BUD→LHR **1489.5 km** just under, LHR→LIS **1563.9 km** just over), 3h threshold, 50%-reduction rule, eval routes, haversine sanity, error handling — **17 passed**
- [x] **UI gains — Calculator tab:** flight inputs (IATA/delay/type/rerouting) → distance / band / base / threshold / reduction / final amount + readable breakdown + disclaimer
- [x] Band amounts/thresholds are statutory **module constants** in `src/calculator.py` (not env knobs / not a rules YAML — see DECISIONS); OpenFlights `airports.dat` (ODbL) fetched to `data/`, attributed in `data/SOURCES.md`
**Done when:** the test set passes with recomputed-from-real-coords expectations; Calculator tab works. ✅ verified — `pytest` 17/17, headless Streamlit boot HTTP 200, `@tool` invoke round-trip.

## Phase 4 — Agentic assembly (end goal)  `[x]`
**Goal:** Put it together into the agentic-RAG graph.
- [x] Typed `AgentState` (`src/state.py`, `trace` is an append-only reducer); nodes (`src/graph.py`): intake, router (writes decision to state), planner, eligibility, calculator, synthesize, fallback
- [x] RAG subgraph attached as a shared `rag` node that **invokes the compiled `rag_graph`** and maps `RAGState ↔ AgentState` at the boundary (different-schema subgraph pattern); reused by both the `rights_info` path and the eligibility branch — does not count toward the 7
- [x] `mixed`/`compensation_calc` as fan-out → fan-in (eligibility branch `rag → eligibility` ‖ calculator); `synthesize` is a **deferred** node so the uneven-length branches converge once; gate `final = eligible ? candidate : 0` applied at synthesize
- [x] **UI gains — Agent tab (the product):** full node-by-node trace (`graph.stream`) + final grounded answer + citations + "not legal advice" disclaimer. Reuses chunk/citation/trace components (`render_agent_trace` added to `ui_components.py`, drills into the RAG subgraph trace).
**Done when:** all four routes work end-to-end and the Agent tab visibly walks the nodes. ✅ verified — four routes classify/route correctly (out_of_scope→fallback; rights_info→rag; comp/mixed→fan-out), eligibility verdicts correct (own-staff strike = compensable, weather = extraordinary→€0), amounts correct (BUD→LHR 4h €250, PAR→ROM strike €250, MAD→JFK snowstorm €0, FRA→CAI 1h €0 sub-threshold), calc tests 17/17, headless Streamlit boot HTTP 200.
**Note:** 3B answer-prose quality remains the limiting factor (the RAG `generate` text is sometimes garbled) — architecture/decisions are correct; calibrate in Phase 6 eval (revisit candidate for the Phase 5 review). See DECISIONS `agent-assembly`, `synthesize-deterministic`, `eligibility-control-frame`, `metro-aliases`.

## Phase 5 — Review, spot-check & improve  `[x]`
**Goal:** Step back from "it runs" to "it's right and clean," **before** heavy eval and dockerization lock the design in. This phase is **human-driven**: the user reviews the assembled solution (Phases 1–4), spot-checks it, and **initiates** the improvements and changes they want — Claude's role is to assist and execute, not to autonomously drive a feature list. Open-ended and exploratory by design; the items below are *available activities*, not a fixed scope.
- [x] **Review & spot-check** (user-led) — exercised the four routes + the corrective-RAG subgraph (band boundaries, EU-route asymmetry, own-staff-strike vs. weather, sub-threshold delays) against the non-negotiables and the five guardrails; surfaced two 3B misclassifications (DECISIONS `spot-check-misroutes`: `ATC-NOT-EXTRAORDINARY`, `SCOPE-ASYMMETRY-MISROUTE`).
- [x] **UI improvements implemented** (user-initiated) — live graph diagram (LR layout), live agent-run streaming, 12 graph-verified Agent-tab examples, live raw `AgentState` panel.
- [x] **Deeper findings documented & carried forward** — the seven substantive findings (corpus scope creep, corpus acquisition workflow, scattered domain types, structured-output consolidation, trace-vs-streaming, delay robustness, RAG multi-hop) are polished with cross-phase coupling in `notes/PHASE5_REVIEW_FINDINGS.md`; citation-scoring design in `notes/EVAL_CITATION_SCORING.md`. **Intentionally deferred to interleave with Phase 6** (eval machinery first as the measurement instrument, then corpus pass + code pass) — see DECISIONS `phase-5-close`. Parked items (3B prose, OJ-notice em-dash leak, `RULES-LOCATION-REVISIT`) folded into that doc's future-work list.
- [x] **Regression check** — Phase 4 behaviours re-confirmed clean: route classification (4 routes), eligibility verdicts (own-staff strike → eligible, snowstorm → €0), amounts (BUD→LHR 4h €250, FRA→CAI 1h sub-threshold €0, MAD→JFK snowstorm candidate €600 → gated €0, CDG→FCO cancellation €250), calc tests 17/17, headless boot HTTP 200. No regression from the UI commits; the lone anomaly (bare city-name intake → null IATA) is the known 3B extraction fragility, queued as findings #4/#6.
**Done when:** the user is satisfied with the review pass, the changes they initiated are implemented and re-spot-checked with no Phase 4 regression, and the deferred items are explicitly listed for the later phases. ✅ closed — review + UI changes done and regression-clean; the deeper findings are documented and explicitly carried into Phase 6 per the agreed sequencing (DECISIONS `phase-5-close`).

## Phase 6 — Functional eval + load test  `[ ]`
**Goal:** Measure correctness and latency (both are graded deliverables; the eval is itself a functional test).
**Note (from Phase 5):** Phase 6 absorbs the Phase 5 substantive findings, interleaved. **Build the eval machinery first** (set + runner + load driver — build-once, design-independent), capture a **baseline**, then do the **corpus pass** (findings #1/#2 — *then* pin citation-level ground truth per `notes/EVAL_CITATION_SCORING.md`) and the **code pass** (#3/#4, investigate #6), re-running the eval each time; **finalize the recorded results + load-test numbers on the settled design** (also the home for finding #5's trace/timing work, `TRACE-VS-TIMING`). Anchor routing/eligibility/amount ground truth to Reg. 261/2004 correctness (not current graph output) so it survives the changes; only citation-level ground truth couples to the corpus. See `notes/PHASE5_REVIEW_FINDINGS.md`.
- [ ] `eval/eval_set.yaml` (15 Qs + ground truth, incl. citation presence/correctness per `notes/EVAL_CITATION_SCORING.md`) + an eval runner; methodology write-up
- [ ] Load test (50–200 queries); attribute the bottleneck via **per-node timing** in the trace (LLM nodes vs. the rest). If that's not conclusive, consider adding a stub backend for a clean LLM-isolated A/B (deferred — see DECISIONS)
- [ ] Latency metrics + bottleneck + 1–2 optimizations
**Done when:** eval and load test run via documented commands and results are recorded.

## Phase 7 — Docker + README  `[ ]`
**Goal:** Reproducible entry point.
- [ ] Dockerfile + docker-compose.yml (app + ollama)
- [ ] README: problem, architecture + design justification, eval/perf summary, install/run, reform caveat
- [ ] **Corpus provenance & refresh** — resolve the deferred `/data/` gitignore (DECISIONS `gitignore-data-for-now`): either commit the frozen snapshot or add a documented/runnable `scripts/fetch_corpus.py` (Cellar API for reg + 2024 guidelines; `requests` + EUR-Lex TXT/HTML export for the legissum) so a fresh clone reproduces the corpus. Carry the licensing/attribution from `data/SOURCES.md` into a tracked location.
**Done when:** `docker compose up` runs end-to-end and a fresh clone can be set up from the README alone (corpus reproducible — committed or fetch-scripted).

---

## Changes & findings log
Append plan-affecting changes here (with a link to the DECISIONS.md entry that explains *why*). Keeps the phase sections clean while preserving the trail.

- 2026-06-04 — **Phase 5 closed.** Review + spot-check done (surfaced DECISIONS `spot-check-misroutes`); user-initiated UI improvements shipped (live graph diagram, live run streaming, 12 graph-verified examples, raw `AgentState` panel); the seven deeper findings documented in `notes/PHASE5_REVIEW_FINDINGS.md` + citation-scoring design in `notes/EVAL_CITATION_SCORING.md`, **deferred to interleave with Phase 6** (eval machinery/baseline first → corpus pass → code pass → finalize results). Phase-4 regression re-confirmed clean (4 routes, eligibility verdicts, amounts, calc 17/17, headless HTTP 200). See DECISIONS `phase-5-close`.
- 2026-06-03 — Inserted **Phase 5 — Review, spot-check & harden** between agentic assembly and eval: review/spot-check the assembled solution, propose improvements, implement the selected ones before heavy eval + dockerization. Renumbered the two not-yet-started phases: eval **5 → 6**, Docker **6 → 7** (no branches/tags existed yet). Forward-references updated in PLAN + the canonical phase-branch list in CLAUDE.md. **Note:** "Phase 5 eval/load test" in DECISIONS entries dated 2026-06-03 *predate* this insert and now mean **Phase 6**. See DECISIONS `phase-5-review-insert`.
- 2026-06-03 — Reordered build: UI-as-spine, LLM-first, corpus/RAG → calculator → agentic assembly; dropped Make; functional-testing with a calculator exception. See DECISIONS `build-approach-ui-spine`.
- 2026-06-03 — Phase 1 built: Python pin 3.12 → **3.14** (only 3.14 available locally; Phase 1 stack has cp314 wheels — risk to re-check at Phase 2 ML deps), model default `qwen2.5:3b-instruct`. See DECISIONS `python-314`, `model-tag`.
- 2026-06-03 — Phase 3 built. Deterministic calculator: pure logic in **`src/calculator.py`** (haversine + OpenFlights lookup + Art. 7 band table as module constants), thin `@tool` wrapper in `src/tools.py`; **`tests/test_calculator.py`** is the one classic-test exception (17 pass). Band figures kept as statutory constants (not YAML/env — see DECISIONS `calculator-rules-constants`); 50% reduction is flag-driven, long-haul 3–4h auto-50% nuance noted not encoded (DECISIONS `calculator-rules-constants`). OpenFlights `airports.dat` (ODbL) added to gitignored `data/`. Only new dep: `pytest==9.0.3`.
- 2026-06-03 — Phase 4 built. Main graph assembled (`src/graph.py`) over a typed `AgentState` (`src/state.py`): 7 nodes + the corrective-RAG subgraph reused as a shared `rag` node. `mixed`/`compensation_calc` are a real fan-out → fan-in; `synthesize` is **deferred** (`add_node(..., defer=True)`) so the uneven-length branches (calculator = 1 hop, rag→eligibility = 2) converge exactly once instead of firing synthesize twice (DECISIONS `agent-assembly`). **synthesize is deterministic** (no LLM) — assembles from already-grounded parts and applies the gate, reversing the plan's LLM-merge for groundedness/latency (DECISIONS `synthesize-deterministic`). **Eligibility** reframed around "within the carrier's control" + no-cause→deterministic-eligible, to stop the 3B treating every strike as extraordinary (DECISIONS `eligibility-control-frame`). Added a **metro-code alias** fallback in `src/calculator.py` (LON→LHR, PAR→CDG, …) because the intake LLM emits IATA *city* codes (DECISIONS `metro-aliases`). Agent tab is the product; `render_agent_trace` added. No new deps.
- 2026-06-03 — Phase 2 built. **Python 3.14 risk retired** — `langgraph` + `chromadb` (and onnxruntime/tokenizers/grpcio) all resolve cp314 wheels, no source builds (DECISIONS `python-314-resolved`). **Embeddings reuse local Ollama `nomic-embed-text`** instead of sentence-transformers/torch — lighter, no new heavy deps (DECISIONS `embeddings-ollama`). **Corpus upgraded:** 2016 → **2024** interpretative guidelines (newer case law), fetched via the Publications Office Cellar API to bypass the EUR-Lex WAF (DECISIONS `corpus-2024-guidelines`). RAG grader is LLM + distance-floor hybrid; 3B answer quality is the open quality item for Phase 5 (DECISIONS `rag-grader`). Deps `langgraph==1.2.4`, `chromadb==1.5.9` added; `PyYAML` dropped.
