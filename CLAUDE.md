# CLAUDE.md

Operational guide for working on this repo with Claude Code — conventions, commands, and the
non-negotiables. See `README.md` for the full design rationale, architecture walkthrough, and
the justification behind each decision.

---

## What this project is

An **Agentic RAG chatbot** (Python + **LangGraph**) for **EU air passenger rights**
(Regulation (EC) No 261/2004). It (a) answers questions about passenger rights using grounded
retrieval and (b) computes flight-disruption compensation using a deterministic calculator
tool. UI is **Streamlit**; everything runs locally and is containerized.

This is a small, clean, reproducible, well-documented prototype — optimize for that, not
breadth. "Quality processing, not quantity."

---

## Non-negotiables (do not violate)

1. **No paid APIs at runtime.** The LLM runs locally via **Ollama**. Never add an
   OpenAI/Anthropic/etc. paid client to the running app. Keep the backend behind the pluggable
   `LLM_BACKEND` seam in `src/llm.py` — nodes call a single `get_llm()` abstraction.
2. **Anchor to the in-force rules.** Use the **current** Reg. 261/2004 figures (3-hour
   threshold; €250 / €400 / €600 distance bands). The 2025 reform is **not enacted** — do not
   encode proposed thresholds. Note the pending reform only as a README caveat.
3. **Ground everything; cite always.** Rights answers come *only* from retrieved chunks and
   must carry citations (source + article). If retrieval doesn't support an answer, say so —
   never fabricate.
4. **Out-of-scope → fallback.** Questions outside Reg. 261/2004 (baggage fees, pets, visas,
   airline pricing) must route to the fallback node, not get a made-up answer.
5. **"Not legal advice" disclaimer** on every answer that interprets the rules.
6. **The calculator is deterministic and LLM-free.** No model calls inside
   `calculate_compensation`. Its output is also eval ground truth, so keep it pure.
7. **Reproducibility.** Pin versions, set `temperature=0` and fixed seeds where supported, keep
   ingestion idempotent, commit the frozen corpus snapshot.

---

## Tech stack

- **Orchestration:** LangGraph (main graph + a separate compiled RAG subgraph)
- **Vector store:** ChromaDB (persisted at `data/chroma/`)
- **Embeddings:** `sentence-transformers` — `BAAI/bge-small-en-v1.5` (fallback `all-MiniLM-L6-v2`)
- **LLM:** **`qwen2.5:3b-instruct`** via Ollama — pinned default for constrained hardware, good
  at structured/JSON output; `llama3.2:3b` is the noted alternative. Behind a pluggable
  `LLM_BACKEND` seam.
- **UI:** Streamlit
- **Runtime/env:** Python **3.14** (pinned via `.python-version`), isolated with stdlib
  **`venv`**, deps pinned in `requirements.txt` (no Poetry/conda/uv)
- **Container:** Docker base `python:3.14-slim` (+ docker-compose for app + ollama)

---

## Commands

No Make — run plain, documented commands (keep them in sync with the README):

```bash
python3.14 -m venv .venv && . .venv/bin/activate   # one-time: create + activate the env
pip install -r requirements.txt          # install pinned deps
python -m src.ingest                      # parse + chunk + embed corpus -> ChromaDB (idempotent)
streamlit run streamlit_app.py            # launch the Streamlit UI
python -m eval.functional_eval            # run functional eval over eval/eval_set.yaml
python -m eval.loadtest                   # run the 50-200 query load test
pytest tests/test_calculator.py           # the one classic-test exception (deterministic calculator)
docker compose up                         # app + ollama end-to-end
```

Backend: `LLM_BACKEND=ollama` (the only one wired; the seam allows adding others). Configure
model names, Ollama URL, and top-k in `config.py` / env — never hardcode.

---

## Architecture quick reference

**State** (`src/state.py`): typed `AgentState` carrying `user_query`, `query_type`,
`flight_details`, `subtasks`, `retrieved_docs`, `rag_answer`, `rag_citations`, `eligibility`,
`calc_result`, `final_answer`, and `trace` (per-node log for the UI).

**Main graph** (`src/graph.py`) — 7 nodes:
1. `intake` — extract flight entities + classify intent (structured JSON out)
2. `router` — conditional routing on `query_type` (rights_info / compensation_calc / mixed / out_of_scope)
3. `planner` — decompose `mixed` queries into subtasks
4. `eligibility` — autonomous decision: is the disruption compensable? (extraordinary-circumstances logic)
5. `calculator` — calls the non-retrieval compensation tool
6. `synthesize` — merge rights answer + amount + citations + disclaimer
7. `fallback` — out-of-scope handling (hallucination firewall)

**RAG subgraph** (`src/rag.py`) — modular, compiled `StateGraph` added via `add_node` (does
**not** count toward the 5); corrective RAG:
`retrieve → grade_documents → (relevant? generate : rewrite_query → retrieve)` with a
**bounded** rewrite loop (max 1–2 retries).

**Tools** (`src/tools.py`) — both are explicit LangChain `@tool`s:
- `retrieve_passenger_rights(query)` — retrieval (used in the subgraph)
- `calculate_compensation(origin_iata, dest_iata, delay_hours, disruption_type, rerouting_offered=False)`
  — **non-retrieval**: haversine distance from OpenFlights coords → band → amount → apply 3h
  threshold + 50% reduction rule

**Mixed-query path** is a real fan-out → fan-in: `mixed` decomposes into a RAG/eligibility
branch and a calculator branch that run as independent parallel branches and converge at
`synthesize`.

This is a **directed/structured agent** (the graph governs control flow) rather than an
open-ended planner — a deliberate trade-off of predictability and testability over open-ended
autonomy. The corrective-RAG grade→rewrite loop is the most defensibly "agentic" part.

---

## Conventions

- **Least ceremony that meets the requirement.** Prefer the simplest construct that does the
  job: module-level constants and plain functions over config frameworks or factory
  indirection; **flat modules** (`src/tools.py`, `src/rag.py`, `src/ingest.py`) over nested
  packages until a module genuinely earns splitting. Introduce abstraction when a second real
  case appears, not in anticipation. **This never applies to the required agent
  architecture:** the ≥5-node graph, the typed `AgentState`, the compiled RAG subgraph, and
  the explicit `@tool`s are *requirements*, not ceremony — keep them.
- **Ingestion is a generic, drop-in directory loader.** Drop a file into `data/corpus/` →
  detect type → apply the right chunker → re-run ingestion → indexed, with no code changes.
- **Chunk by legal structure** (Article / Recital), not fixed token windows; sub-split only
  oversized articles by paragraph with small overlap. Attach metadata (`source`, `article`,
  `title`, `url`, `retrieved_at`, `chunk_id`) to every chunk.
- **Citations reference metadata**, never raw chunk text dumps.
- **Config over hardcoding** — all knobs in `config.py` (constants + env override).
- **Bounded loops** — cap the corrective-RAG rewrite retries to keep latency sane.
- **Stream the graph** in Streamlit (`graph.stream`) and append each node's output to the
  `trace` panel so the user watches the agent work.
- **Run independent subtasks concurrently** for `mixed` queries where practical.
- **Repo hygiene.** Commit the frozen corpus snapshot (`data/corpus/`); **gitignore**
  `data/chroma/` (rebuilt from the corpus via idempotent ingest), `.venv/`, `__pycache__/`,
  `*.pyc`. Only the corpus is the source of truth — the vector store is a derived artifact.

---

## Gotchas / verify before trusting

- **Recompute example distances** with real OpenFlights coords before fixing eval ground truth
  — routes near a band boundary (e.g. ~1500 km) can flip the expected amount. A wrong
  "expected" value is worse than none.
- **OpenFlights data is ODbL** — attribute it in `data/SOURCES.md`. EUR-Lex content is
  reusable with source acknowledgment.
- **EU261 route scope is asymmetric**: EU-departing flights (any carrier) are covered; non-EU →
  EU is covered only on EU carriers. Make sure `eligibility`/RAG reflects this.
- **Own-airline staff strike ≠ extraordinary** (compensation due); weather/ATC/security
  generally are extraordinary (no compensation, but care/rerouting may apply).
- **Load-test bottleneck is local LLM generation** (plus the rewrite loop) — the calculator and
  vector search are negligible. Confirmed via per-node timing in `notes/EVAL_RESULTS.md`.

---

## Reference docs

- `README.md` — the full design rationale, architecture, and run/install guide.
- `notes/EVAL_RESULTS.md` — functional-eval + load-test methodology and baseline numbers.
- `notes/EVAL_CITATION_SCORING.md` — how the eval set asserts on citations.
- `notes/FUTURE_IMPROVEMENTS.md` — open backlog and known limitations.
- `data/SOURCES.md` — corpus + airport-data provenance and licensing.

---

## Definition of done

≥5 nodes with conditional routing, decomposition, typed state, ≥2 tools (≥1 non-retrieval),
modular RAG subgraph not counted in the 5, structure-aware corpus processing with citations,
local LLM (Ollama), Streamlit UI showing agent steps, Dockerfile (+ compose), functional eval
+ load test with bottleneck analysis, and a complete reproducible README.
