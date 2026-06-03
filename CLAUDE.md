# CLAUDE.md

Operational guide for working on this repo with Claude Code. Read `notes/PROJECT_PROPOSAL.md` for the full design rationale; this file is the short, high-signal working agreement — conventions, commands, and the non-negotiables.

---

## Document map (where things live — route updates here)

Each doc has one job. When something changes, update the **one** file that owns it:

| Need | Home | Notes |
|------|------|-------|
| *How to work* — conventions, guardrails, non-negotiables, commands | **CLAUDE.md** (this file) | Changes rarely — only when a rule/convention changes |
| *What & when* — phased plan + live status | **PLAN.md** | The living doc; update as phases progress |
| *Why it changed* — findings, trade-offs, simplifications | **DECISIONS.md** | Append-only; link entries from PLAN.md |
| *Why* (original design rationale) | **notes/PROJECT_PROPOSAL.md** | Near-frozen reference; don't rewrite — add a "superseded by [[decision]]" pointer instead |

**Routing rule:** scope/status/next-phase changed → `PLAN.md`. Why you changed it → `DECISIONS.md` (and link it from the PLAN entry). A convention/rule changed → here. Design rationale stays put in the proposal.

---

## What this project is

An **Agentic RAG chatbot** (Python + **LangGraph**) for **EU air passenger rights** (Regulation (EC) No 261/2004). It (a) answers questions about passenger rights using grounded retrieval and (b) computes flight-disruption compensation using a deterministic calculator tool. UI is **Streamlit**; everything runs locally and is containerized.

This is an **interview prototype**. Optimize for a small, clean, reproducible, well-documented build — not breadth. "Quality processing, not quantity" is a grading criterion.

---

## Non-negotiables (do not violate)

1. **No paid APIs.** LLM runs locally via **Ollama**, or use the **dummy LLM backend** (`LLM_BACKEND=dummy`). Never add an OpenAI/Anthropic/etc. paid client.
2. **Anchor to the in-force rules.** Use the **current** Reg. 261/2004 figures (3-hour threshold; €250 / €400 / €600 distance bands). The 2025 reform is **not enacted** — do not encode proposed thresholds. Note the pending reform only as a README caveat.
3. **Ground everything; cite always.** Rights answers come *only* from retrieved chunks and must carry citations (source + article). If retrieval doesn't support an answer, say so — never fabricate.
4. **Out-of-scope → fallback.** Questions outside Reg. 261/2004 (baggage fees, pets, visas, airline pricing) must route to the fallback node, not get a made-up answer.
5. **"Not legal advice" disclaimer** on every answer that interprets the rules.
6. **The calculator is deterministic and LLM-free.** No model calls inside `calculate_compensation`. Its output is also eval ground truth, so keep it pure.
7. **Reproducibility.** Pin versions, set `temperature=0` and fixed seeds where supported, keep ingestion idempotent, commit the frozen corpus snapshot.

---

## Tech stack

- **Orchestration:** LangGraph (main graph + a separate compiled RAG subgraph)
- **Vector store:** ChromaDB (persisted at `data/chroma/`)
- **Embeddings:** `sentence-transformers` — `BAAI/bge-small-en-v1.5` (fallback `all-MiniLM-L6-v2`)
- **LLM:** local instruct model via Ollama (7–8B default; 3B for routing/extraction on constrained hardware) — switchable to `dummy`
- **UI:** Streamlit
- **Container:** Docker (+ docker-compose for app + ollama)

---

## Commands

Use the Makefile targets (create them if missing):

```bash
make install      # install pinned deps
make ingest       # parse + chunk + embed corpus -> ChromaDB (idempotent)
make run          # launch the Streamlit UI
make eval         # run functional eval over eval/eval_set.yaml
make loadtest     # run the 50-200 query load test (supports LLM_BACKEND=dummy)
make test         # unit tests (calculator first)
docker compose up # app + ollama end-to-end
```

Backend switch: `LLM_BACKEND=ollama` (default) or `LLM_BACKEND=dummy`. Configure model names, Ollama URL, and top-k in `config.yaml` / env — never hardcode.

---

## Architecture quick reference

**State** (`src/state.py`): typed `AgentState` carrying `user_query`, `query_type`, `flight_details`, `subtasks`, `retrieved_docs`, `rag_answer`, `rag_citations`, `eligibility`, `calc_result`, `final_answer`, and `trace` (per-node log for the UI).

**Main graph** (`src/graph.py`) — 7 nodes (≥5 required):
1. `intake` — extract flight entities + classify intent (structured JSON out)
2. `router` — conditional routing on `query_type` (rights_info / compensation_calc / mixed / out_of_scope)
3. `planner` — decompose `mixed` queries into subtasks
4. `eligibility` — autonomous decision: is the disruption compensable? (extraordinary circumstances logic)
5. `calculator` — calls the non-retrieval compensation tool
6. `synthesize` — merge rights answer + amount + citations + disclaimer
7. `fallback` — out-of-scope handling (hallucination firewall)

**RAG subgraph** (`src/rag/graph.py`) — modular, **does NOT count toward the 5**; corrective RAG:
`retrieve → grade_documents → (relevant? generate : rewrite_query → retrieve)` with a **bounded** rewrite loop (max 1–2 retries).

**Tools** (`src/tools/`):
- `retrieve_passenger_rights(query)` — retrieval (used in the subgraph)
- `calculate_compensation(origin_iata, dest_iata, delay_hours, disruption_type, rerouting_offered=False)` — **non-retrieval**: haversine distance from OpenFlights coords → band → amount → apply 3h threshold + 50% reduction rule

---

## Implementation guardrails (from design review — lock these in)

These five make the difference between *claiming* a requirement and *demonstrably* satisfying it. Implement them this way unless there's a concrete reason not to (record any deviation in `DECISIONS.md`):

1. **Mixed-query path is a real fan-out → fan-in.** Decompose `mixed` into a RAG/eligibility branch and a calculator branch that run as **independent parallel branches** and converge at `synthesize`. This is the single highest-value refinement — it *demonstrates* "decomposition into subtasks AND independent execution" instead of asserting it. Don't collapse it into a sequential path.
2. **Both capabilities are explicit LangChain `@tool`s.** `retrieve_passenger_rights` and `calculate_compensation` are decorated tools, not plain functions buried in nodes — so there's no argument about whether they count. The calculator stays deterministic/LLM-free; wrapping it as a `@tool` does **not** introduce a model call.
3. **The RAG subsystem is a compiled `StateGraph` added via `add_node`.** It must be an actually-compiled subgraph invoked as a node — not a Python function the main graph calls. That wiring is what makes it "a subgraph that doesn't count toward the 5."
4. **Ingestion is a generic, drop-in directory loader.** Dropping a new file into `data/corpus/` → detect type → apply the right chunker → re-run `make ingest` → indexed, with **no code changes**. This is what satisfies "scalable data integration"; avoid per-document hand-tuned parsing paths.
5. **Router is an explicit node; the planner does real decomposition.** The router is a genuine node that writes its routing decision into state (cleaner trace panel), with the conditional branch as the edge *after* it — not a bare conditional edge. The planner emits subtasks via the LLM, not a hardcoded "mixed always splits into eligibility + calc."

Framing to be ready to defend: this is a **directed/structured agent** (the graph governs control flow) rather than an open-ended planner that freely chooses tools — a deliberate trade-off of predictability and testability over open-ended autonomy, appropriate for an evaluable prototype. The corrective-RAG grade→rewrite loop is the most defensibly "agentic" part. See `DECISIONS.md`.

---

## Conventions

- **Chunk by legal structure** (Article / Recital), not fixed token windows; sub-split only oversized articles by paragraph with small overlap. Attach metadata (`source`, `article`, `title`, `url`, `retrieved_at`, `chunk_id`) to every chunk.
- **Citations reference metadata**, never raw chunk text dumps.
- **Config over hardcoding** — all knobs in `config.yaml`/env.
- **Bounded loops** — cap the corrective-RAG rewrite retries to keep latency sane.
- **Stream the graph** in Streamlit (`graph.stream`) and append each node's output to the `trace` panel so the user watches the agent work (this scores the "demonstrate agent operation" requirement).
- **Run independent subtasks concurrently** for `mixed` queries where practical.
- **Log implementation decisions in `DECISIONS.md`** — whenever a trade-off is made, an arbitrary/placeholder choice is taken that must be revised later, or a non-obvious gotcha surfaces, append a dated entry (newest first) using the tags in that file.

---

## Build order

The phased build plan and its live status live in **`PLAN.md`** (see the Document map above). The short version: calculator + tests first (it's the eval ground truth), then ingestion, then the RAG subgraph, then the main graph, UI, eval, load test, Docker, README last. Update `PLAN.md` as phases complete; log the *why* behind any plan change in `DECISIONS.md`.

---

## Gotchas / verify before trusting

- **Recompute example distances** with real OpenFlights coords before fixing eval ground truth — routes near a band boundary (e.g. ~1500 km) can flip the expected amount. A wrong "expected" value is worse than none.
- **OpenFlights data is ODbL** — attribute it in `data/SOURCES.md`. EUR-Lex content is reusable with source acknowledgment.
- **EU261 route scope is asymmetric**: EU-departing flights (any carrier) are covered; non-EU → EU is covered only on EU carriers. Make sure `eligibility`/RAG reflects this.
- **Own-airline staff strike ≠ extraordinary** (compensation due); weather/ATC/security generally are extraordinary (no compensation, but care/rerouting may apply).
- **Expected load-test bottleneck** is local LLM generation latency (plus the rewrite loop) — the calculator and vector search are negligible. Use dummy mode to confirm by isolating LLM time.

---

## Definition of done

See the acceptance checklist at the end of `notes/PROJECT_PROPOSAL.md` (§13). In short: ≥5 nodes with conditional routing, decomposition, typed state, ≥2 tools (≥1 non-retrieval), modular RAG subgraph not counted in the 5, structure-aware corpus processing with citations, local/dummy LLM, Streamlit UI showing agent steps, Dockerfile (+ compose bonus), functional eval (15 Qs) + load test (50–200 queries) with bottleneck analysis, and a complete reproducible README.
