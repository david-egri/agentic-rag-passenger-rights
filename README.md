# Agentic RAG — EU Air Passenger Rights (Reg. 261/2004)

An **agentic RAG chatbot** that (a) answers questions about EU air passenger rights using
**grounded, cited retrieval** over the in-force legal corpus, and (b) computes flight-disruption
**compensation** with a deterministic, LLM-free calculator. Built with **LangGraph**, a local LLM
via **Ollama**, **ChromaDB**, and a **Streamlit** UI that shows the agent working node by node.

Everything runs **locally** — no paid APIs — and the whole stack is containerized
(`docker compose up`).

> ⚖️ **Not legal advice.** Answers interpret Regulation (EC) No 261/2004 for general
> information only. See [Caveats](#caveats).

---

## What it does

- **Rights questions** → grounded answer from the legal corpus, always with **citations**
  (source + article/section) and a disclaimer. If retrieval doesn't support an answer, it says so.
- **Compensation questions** → a deterministic calculator (great-circle distance → Art. 7 band →
  €250 / €400 / €600), with the **eligibility** gate (extraordinary circumstances) applied.
- **Mixed questions** → decomposed into parallel branches (rights retrieval ‖ calculation) that
  converge into one answer.
- **Out-of-scope questions** (baggage fees, visas, pricing…) → routed to a fallback node, never
  answered from thin air (hallucination firewall).

---

## Architecture

A **directed/structured agent**: the LangGraph graph governs control flow (predictable and
testable), rather than an open-ended planner that freely picks tools. The most "agentic" part is
the **corrective-RAG** loop, which grades its own retrieval and rewrites the query when it's weak.

### Main graph (`src/graph.py`) — 7 nodes

```
                       ┌─────────┐
  user query  ───────▶ │ intake  │  extract flight entities + classify intent (structured JSON)
                       └────┬────┘
                            ▼
                       ┌─────────┐
                       │ router  │  writes routing decision to state
                       └────┬────┘
          ┌─────────────────┼───────────────────────────┬──────────────────┐
   rights_info        compensation_calc / mixed                         out_of_scope
          │                 │  (planner decomposes mixed into subtasks)        │
          ▼                 ▼                                                  ▼
     ┌─────────┐     ┌──────────────── fan-out ───────────────┐          ┌──────────┐
     │   rag   │     │  rag → eligibility    ‖    calculator   │          │ fallback │
     │(subgraph)     │  (extraordinary-     │   (deterministic │          └────┬─────┘
     └────┬────┘     │   circumstances)     │    €250/400/600) │               │
          │          └──────────────── fan-in ────────────────┘               │
          │                          │                                         │
          └──────────────┬───────────┴─────────────────────────────────────────┘
                         ▼
                   ┌───────────┐
                   │ synthesize│  merge rights + amount + citations + disclaimer;
                   └─────┬─────┘  apply gate: final = eligible ? candidate : €0  (deterministic)
                         ▼
                   final answer
```

- **`intake`** — extracts flight details and classifies intent (structured output).
- **`router`** — an explicit node that writes its decision to state; the conditional branch is the
  edge *after* it (cleaner trace).
- **`planner`** — decomposes `mixed` queries into real subtasks.
- **`eligibility`** — autonomous decision: is the disruption compensable? (e.g. own-airline staff
  strike = compensable; weather/ATC = extraordinary → no compensation, but care/rerouting may apply).
- **`calculator`** — calls the non-retrieval compensation tool.
- **`synthesize`** — merges the parts and applies the eligibility gate. **Deterministic, no LLM**
  (assembles already-grounded pieces — groundedness + latency).
- **`fallback`** — out-of-scope handling.

`mixed` / `compensation_calc` run as a genuine **fan-out → fan-in**: the eligibility branch
(`rag → eligibility`) and the `calculator` branch execute as independent parallel branches and
converge once at `synthesize` (a *deferred* node, so the uneven-length branches join exactly once).

### RAG subgraph (`src/rag.py`) — modular, compiled, **not** one of the 7

A separately compiled `StateGraph`, attached to the main graph as a shared `rag` node (it maps
`RAGState ↔ AgentState` at the boundary) and reused by both the `rights_info` path and the
eligibility branch:

```
retrieve → grade_documents → (relevant? → generate : rewrite_query → retrieve)
                              └─ bounded rewrite loop (REWRITE_MAX_RETRIES) ─┘
```

The grader is an **LLM grader + cosine-distance safety floor** hybrid; `generate` is strictly
grounded (no outside knowledge, no invented figures).

### Two explicit tools (`src/tools.py`)

- `retrieve_passenger_rights(query)` — retrieval (used inside the subgraph).
- `calculate_compensation(...)` — **non-retrieval, deterministic, LLM-free**: haversine distance
  from OpenFlights coords → Art. 7 band → amount → 3 h threshold + 50 % reduction rule. Its output
  is also the eval ground truth, so it stays pure (`src/calculator.py`, statutory figures as module
  constants).

### Typed state (`src/state.py`)

A typed `AgentState` carries `user_query`, `query_type`, `flight_details`, `subtasks`,
`retrieved_docs`, `rag_answer`, `rag_citations`, `eligibility`, `calc_result`, `final_answer`, and
an append-only `trace` (per-node log the UI streams).

---

## Tech stack

| Layer | Choice |
|---|---|
| Orchestration | **LangGraph** (main graph + compiled RAG subgraph) |
| LLM | **`qwen2.5:3b-instruct`** via **Ollama** (local; `temperature=0`) |
| Embeddings | **`nomic-embed-text`** via Ollama (no torch/sentence-transformers) |
| Vector store | **ChromaDB** (persisted at `data/chroma/`, derived) |
| UI | **Streamlit** (a tab per layer: Chat · Corpus · RAG · Calculator · **Agent**) |
| Runtime | **Python 3.14**, stdlib `venv`, pinned `requirements.txt` |
| Container | `python:3.14-slim` + `docker-compose` (app + ollama) |

The LLM sits behind a pluggable `LLM_BACKEND` seam (`src/llm.py`); all knobs live in `config.py`
with env override (`OLLAMA_URL`, `MODEL`, `TOP_K`, `REWRITE_MAX_RETRIES`, …).

---

## Quick start

### Option A — Docker, all-in-one (portable; works on any OS) ✅ recommended for a clean run

```bash
docker compose up --build         # first run: builds app, pulls ~2.2 GB models, ingests corpus
# then open http://localhost:8501
```

First boot takes a few minutes (model pull + one-time ingest, both persisted in named volumes);
later boots are fast. The app waits for the Ollama service's healthcheck before starting.

> 🍎 **macOS note:** a Linux container can't use the Apple GPU, so the in-container Ollama is
> **CPU-only — measured ~5.5× slower** end-to-end (see [Performance](#evaluation--performance)).
> On a Mac, prefer **Option B**.

### Option B — Docker app + host Ollama (the macOS fast path)

Run Ollama natively on the host (GPU), and point the containerized app at it — one env override,
no code change:

```bash
# 1) host: run Ollama with both models
ollama serve            # (if not already running)
ollama pull qwen2.5:3b-instruct
ollama pull nomic-embed-text

# 2) app container → host Ollama (skips the in-container ollama service)
OLLAMA_URL=http://host.docker.internal:11434 docker compose up -d --build --no-deps app
# then open http://localhost:8501
```

This is also the **lightest** path on disk — it reuses the host's models, so it skips the
~1.5 GB Ollama image and the ~2.2 GB model download. *(`host.docker.internal` is auto-provided by
Docker Desktop; for native Linux the compose file already maps it via
`extra_hosts: ["host.docker.internal:host-gateway"]`, so this path works cross-platform out of the
box.)*

### Option C — Local, no Docker (dev)

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# requires a local Ollama with qwen2.5:3b-instruct + nomic-embed-text pulled
python -m src.ingest                 # parse → chunk → embed corpus → ChromaDB (idempotent)
streamlit run streamlit_app.py       # http://localhost:8501
```

### Eval & tests

```bash
python -m eval.functional_eval       # 15-question functional eval (routing/eligibility/amount/citations)
python -m eval.loadtest              # load test (N=50) with per-node timing + bottleneck
pytest tests/test_calculator.py      # the one classic-unit-test exception (deterministic calculator)
```

### Managing the Docker stack

```bash
docker compose stop / start          # pause / resume (no disk churn)
docker compose down                  # remove containers, KEEP volumes (fast next start)
docker compose down -v               # also drop volumes (frees ~2.2 GB models; re-pull next time)
```

---

## Usage

The Streamlit UI has a tab per layer; the **Agent** tab is the product:

- **Chat** — talk to the raw LLM (the Phase-1 spine).
- **Corpus** — browse the indexed chunks with their Article/Recital/Section labels + metadata.
- **RAG** — run a query through the corrective-RAG subgraph and watch retrieve → grade → (rewrite) →
  generate, with citations and retrieved-passage distances.
- **Calculator** — flight inputs → distance / band / threshold / reduction / final amount.
- **Agent** — the full graph: a live node-by-node trace (`graph.stream`), the final grounded answer,
  citations, and the disclaimer. Includes a live graph diagram and graph-verified example queries.

---

## Evaluation & performance

Full methodology + numbers: [`notes/PHASE6_EVAL_RESULTS.md`](notes/PHASE6_EVAL_RESULTS.md).
Ground truth is anchored to **Reg. 261/2004 correctness** (route distances recomputed from real
OpenFlights coords before pinning amounts), not to current model output.

### Functional eval (`qwen2.5:3b-instruct`, temperature 0)

| Dimension | Score |
|---|---|
| Routing | 10/14 (71%) — the weak dimension (3B intake blurs rights/calc/mixed; see `F-ROUTING`) |
| Eligibility | **8/8 (100%)** |
| Amount (gated) | **8/8 (100%)** |
| Citation presence | **7/7 (100%)** |
| Citation correctness | 6/7 (86%) |

**Correctness where it counts is solid** — amounts, eligibility, and citations are reliable; even
when the intake misroutes, the eligibility branch still runs, so the *numbers* stay correct (the
cost is trace shape, not the answer). The routing weakness is documented and queued for a later
review phase (move intake to structured output + targeted few-shots).

### Load test (N=50, sequential)

- **Latency:** mean **17.8 s**, p95 **25.7 s**, min **2.47 s** (the LLM-free out_of_scope path).
- **Bottleneck:** local-LLM generation is **100 % of node time**; everything non-LLM (calculator,
  vector search, synthesize, routing) is **0.0 %**. Split: `rag` **69 %** (grade + generate, ×2 on a
  rewrite), `intake` **24 %**. The only lever is the number/cost of LLM calls.
- **Design wins quantified:** deterministic no-cause eligibility, LLM-free synthesize, and the
  out_of_scope short-circuit each measurably cut latency. Next lever (deferred): make the RAG branch
  conditional on `compensation_calc`.

### CPU vs GPU (Docker substrate)

Identical queries, `temperature 0`, **host Metal GPU vs the CPU-only container**: the in-container
Ollama is **~5.5× slower end-to-end** (mean 25.3 s → 139.8 s over LLM-heavy routes). A bare
single-prompt decode benchmark is only ~2.2× (≈21 vs ≈9.5 tok/s); the end-to-end gap is wider
because the agent fires several LLM calls per query and the `rag` step does large-context prefill,
where CPU lags most. → the macOS fast path (Option B) exists for exactly this reason.

---

## Project structure

```
config.py              # all knobs (env-overridable): MODEL, OLLAMA_URL, TOP_K, paths, …
streamlit_app.py       # UI spine (one tab per layer); ui_components.py = shared renderers
src/
  llm.py               # get_llm() behind the LLM_BACKEND seam
  state.py             # typed AgentState (+ append-only trace reducer)
  graph.py             # main 7-node graph + run_agent()
  rag.py               # compiled corrective-RAG subgraph
  tools.py             # @tool retrieve_passenger_rights + @tool calculate_compensation
  calculator.py        # pure, deterministic Art. 7 logic (haversine + band table)
  ingest.py            # generic drop-in corpus loader → structure-aware chunkers → Chroma
  store.py             # Chroma client + Ollama embeddings
eval/                  # eval_set.yaml + functional_eval.py + loadtest.py
tests/test_calculator.py
docker/                # entrypoint.sh + prepare.py (wait-for-ollama → pull models → ingest)
Dockerfile  docker-compose.yml  .dockerignore
data/corpus/           # frozen legal corpus (committed); data/chroma/ is derived (gitignored)
notes/                 # design proposal, decisions, eval results, review findings
```

---

## Corpus & sources

The RAG corpus is a **frozen, dated snapshot** committed under `data/corpus/` (the source of
truth); the ChromaDB store is derived and rebuilt by `python -m src.ingest`. Four documents:
the full **Regulation (EC) No 261/2004**, the **2024 Commission interpretative guidelines**, the
EUR-Lex **legislative summary**, and a **Your Europe** plain-language summary.

Licensing & provenance: [`data/SOURCES.md`](data/SOURCES.md). EUR-Lex / Publications Office content
is © European Union (reuse with acknowledgement); OpenFlights `airports.dat` (used by the
calculator, not the RAG corpus) is **ODbL** — attributed accordingly.

---

## Reproducibility

Pinned versions (`requirements.txt`, `python:3.14-slim`), `temperature=0` and fixed seeds where
supported, idempotent ingestion, and the **frozen corpus committed** so a fresh clone reproduces the
index offline. The vector store is the one derived artifact (gitignored, rebuilt deterministically).

---

## Caveats

- **The 2025 reform is *not* encoded.** Reg. 261/2004 is under reform (Council position June 2025;
  Parliament TRAN committee October 2025) but **not yet enacted**. This system targets the
  **current in-force rules**: 3-hour delay threshold; €250 / €400 / €600 distance bands. Proposed
  thresholds are deliberately not used.
- **EU261 route scope is asymmetric:** EU-departing flights (any carrier) are covered; non-EU → EU
  is covered only on EU carriers.
- **Not legal advice.** General information only; consult the official texts or a qualified adviser
  for any real claim.
```
