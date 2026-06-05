# CLAUDE.md

Working context for anyone — human or AI agent — developing in this repository. It covers what
the project is, how to run it, the constraints that must hold, and the conventions to follow.
For the full design rationale, architecture walkthrough, and install guide, see `README.md`;
this file is the concise operational companion to it.

---

## Project overview

An **agentic RAG chatbot** (Python + **LangGraph**) for **EU air passenger rights**
(Regulation (EC) No 261/2004). It does two things:

- **Answers passenger-rights questions** via grounded retrieval — every answer is built from
  retrieved legal text and carries citations.
- **Computes flight-disruption compensation** with a deterministic, non-LLM calculator tool.

Everything runs locally (LLM via **Ollama**), with a **Streamlit** UI and Docker packaging. The
codebase favours a small, readable, reproducible footprint over breadth.

---

## Commands

```bash
python3.14 -m venv .venv && . .venv/bin/activate   # one-time: create + activate the env
pip install -r requirements.txt          # install pinned deps
python -m src.ingest                      # parse + chunk + embed corpus -> ChromaDB (idempotent)
streamlit run streamlit_app.py            # launch the Streamlit UI
python -m eval.functional_eval            # functional eval over eval/eval_set.yaml
python -m eval.loadtest                   # load test (50–200 queries) with per-node timing
pytest tests/test_calculator.py           # unit tests for the deterministic calculator
docker compose up                         # app + ollama end-to-end
```

All tunables (model names, Ollama URL, top-k, retry caps) live in `config.py` as constants with
env-var overrides. Read them through `config.py` — don't hardcode knobs at call sites.

---

## Tech stack

- **Orchestration:** LangGraph — a main graph plus a separate compiled RAG subgraph
- **Vector store:** ChromaDB (persisted at `data/chroma/`, rebuilt from the corpus)
- **Embeddings:** `nomic-embed-text` via Ollama — reuses the local Ollama server, so no
  `torch`/`sentence-transformers` dependency. Needs task prefixes (`search_document:` /
  `search_query:`, applied in `src/store.py`); the model is set by `EMBEDDING_MODEL` in `config.py`.
- **LLM:** `qwen2.5:3b-instruct` via Ollama (pinned for constrained hardware; good at structured
  output). `llama3.2:3b` is a noted alternative. Accessed through a pluggable `LLM_BACKEND` seam.
- **UI:** Streamlit
- **Runtime:** Python 3.14 (pinned via `.python-version`), stdlib `venv`, deps pinned in
  `requirements.txt` (no Poetry/conda/uv)
- **Container:** Docker base `python:3.14-slim` (+ docker-compose for app + Ollama)

---

## Architecture

**State** (`src/state.py`): a typed `AgentState` carrying `user_query`, `query_type`,
`flight_details`, `subtasks`, `retrieved_docs`, `rag_answer`, `rag_citations`, `eligibility`,
`calc_result`, `final_answer`, and `trace` (a per-node log surfaced in the UI).

**Main graph** (`src/graph.py`) — the control flow, as explicit nodes:

1. `intake` — extract flight entities + classify intent (structured output)
2. `router` — branch on `query_type`: `rights_info` / `compensation_calc` / `mixed` / `out_of_scope`
3. `planner` — decompose `mixed` queries into subtasks
4. `eligibility` — decide whether the disruption is compensable (extraordinary-circumstances logic)
5. `calculator` — invoke the deterministic compensation tool
6. `synthesize` — merge rights answer + amount + citations + disclaimer
7. `fallback` — out-of-scope handling (the hallucination firewall)

**RAG subgraph** (`src/rag.py`): a modular, separately compiled `StateGraph` added to the main
graph as a node. Corrective RAG —
`retrieve → grade_documents → (relevant? generate : rewrite_query → retrieve)` — with a
**bounded** rewrite loop. The grade→rewrite loop is the most genuinely agentic part of the system.

**Tools** (`src/tools.py`), both explicit LangChain `@tool`s:

- `retrieve_passenger_rights(query)` — retrieval (used inside the RAG subgraph)
- `calculate_compensation(origin_iata, dest_iata, delay_hours, disruption_type, rerouting_offered=False)`
  — non-retrieval: haversine distance from OpenFlights coords → distance band → amount, then the
  3-hour threshold and 50% reduction rules

**Mixed queries** run as a real fan-out → fan-in: a RAG/eligibility branch and a calculator
branch execute as independent parallel branches and converge at `synthesize`.

This is a **directed/structured agent** — the graph governs control flow rather than letting the
model freely choose tools. That's a deliberate trade-off: predictability and testability over
open-ended autonomy.

---

## Core constraints (keep these true)

Load-bearing invariants. Don't break one unless the change is *explicitly* meant to revise it —
and update this file if so.

1. **Local-only LLM.** The running app uses a local model via Ollama; never wire in a paid
   API client. Keep model access behind the `LLM_BACKEND` seam in `src/llm.py` (nodes call a
   single `get_llm()` abstraction).
2. **Anchor to the in-force law.** Use current Reg. 261/2004 figures (3-hour threshold;
   €250 / €400 / €600 distance bands). Don't encode the not-yet-enacted 2025 reform; mention it
   only as a README caveat.
3. **Ground and cite.** Rights answers come only from retrieved chunks and must carry citations
   (source + article). If retrieval doesn't support an answer, say so — never fabricate.
4. **Out-of-scope routes to fallback.** Questions beyond Reg. 261/2004 (baggage, pets, visas,
   pricing) go to the fallback node, not a made-up answer.
5. **Disclaimer.** Every answer that interprets the rules carries a "not legal advice" note.
6. **The calculator is deterministic and LLM-free.** No model calls inside
   `calculate_compensation`; its output doubles as eval ground truth, so keep it pure.
7. **Reproducibility.** Pin versions, set `temperature=0` and fixed seeds where supported, keep
   ingestion idempotent, and commit the frozen corpus snapshot.

---

## Conventions

- **Least ceremony that meets the need.** Prefer the simplest construct: module-level constants
  and plain functions over config frameworks or factory indirection; **flat modules**
  (`src/tools.py`, `src/rag.py`, `src/ingest.py`) over nested packages until a module earns
  splitting. Add abstraction when a second real case appears, not in anticipation. (The core
  agent architecture — the multi-node graph, typed `AgentState`, compiled RAG subgraph, and
  explicit `@tool`s — is intentional structure; don't collapse it in the name of simplicity.)
- **Generic, drop-in ingestion.** Dropping a file into `data/corpus/` and re-running ingestion
  should index it — detect type → apply the right chunker → embed — with no code changes.
- **Chunk by legal structure** (Article / Recital), not fixed token windows; sub-split only
  oversized articles by paragraph with small overlap. Attach metadata (`source`, `article`,
  `title`, `url`, `retrieved_at`, `chunk_id`) to every chunk.
- **Citations reference metadata**, never raw chunk-text dumps.
- **Config over hardcoding** — every knob in `config.py`, env-overridable.
- **Bounded loops** — cap the corrective-RAG rewrite retries to keep latency predictable.
- **Stream the graph** in Streamlit (`graph.stream`) and append each node's output to the
  `trace` panel, so the agent's steps are visible.
- **Repo hygiene.** Commit the frozen corpus (`data/corpus/`); gitignore `data/chroma/` (a
  derived artifact, rebuilt by ingestion), `.venv/`, `__pycache__/`, `*.pyc`. The corpus is the
  source of truth; the vector store is regenerated from it.

---

## Making changes safely

- **The functional eval is the regression harness.** Run `python -m eval.functional_eval` after
  any behavioural change. Its ground truth is anchored to Reg. 261/2004 correctness (not to
  current output), so it stays valid across refactors.
- **The calculator has unit tests** (`pytest tests/test_calculator.py`). Keep it deterministic
  and LLM-free; when you change rules or bands, recompute expected amounts from real coordinates
  before updating ground truth.
- **Re-ingest after corpus changes** (`python -m src.ingest`) — it's idempotent. Don't commit
  `data/chroma/`; it's rebuilt.
- **Keep this file current.** When a convention or constraint changes, update CLAUDE.md in the
  same change.

---

## Domain gotchas (verify before trusting)

- **Recompute example distances** from real OpenFlights coordinates before pinning eval ground
  truth — routes near a band boundary (~1500 km) can flip the expected amount. A wrong "expected"
  value is worse than none.
- **EU261 route scope is asymmetric**: EU-departing flights are covered on any carrier; non-EU →
  EU is covered only on EU carriers. `eligibility`/RAG must reflect this.
- **Own-airline staff strike is *not* extraordinary** (compensation due); weather / ATC /
  security generally *are* extraordinary (no compensation, though care/rerouting may still apply).
- **The latency bottleneck is local-LLM generation** (plus the rewrite loop) — vector search and
  the calculator are negligible. Confirmed by per-node timing in `notes/EVAL_RESULTS.md`.
- **Licensing:** OpenFlights data is ODbL (attribute it in `data/SOURCES.md`); EUR-Lex content is
  reusable with source acknowledgment.

---

## Reference docs

- `README.md` — full design rationale, architecture, and run/install guide.
- `notes/EVAL_RESULTS.md` — functional-eval + load-test methodology and baseline numbers.
- `notes/EVAL_CITATION_SCORING.md` — how the eval set asserts on citations.
- `data/SOURCES.md` — corpus + airport-data provenance and licensing.
- **GitHub Issues** — open backlog and known limitations, filed as labelled issues.
