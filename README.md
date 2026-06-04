# Agentic RAG — EU Air Passenger Rights (Reg. 261/2004)

A chatbot that answers two kinds of question about EU air passenger rights: *"what am I entitled to?"*
(answered from the actual law, always with a citation) and *"how much money do I get?"* (worked out by
a calculator, not guessed by a model). It's built as a small LangGraph agent, runs entirely on your own
machine with a local LLM, and the Streamlit UI lets you watch it think one step at a time.

No paid APIs, no data leaving the box. The whole thing comes up with one command (`docker compose up`).

> ⚖️ **Not legal advice.** Answers interpret Regulation (EC) No 261/2004 for general information only.
> See [Caveats](#caveats).

---

## The problem, and why an agent

If your flight is cancelled or badly delayed inside the EU, the law (Regulation 261/2004) says you may
be owed up to €600. In practice almost nobody claims it. The rules are real but fiddly: the amount
depends on how far you were flying and how late you arrived, and whether you get *anything* depends on
whether the disruption was the airline's fault or an "extraordinary circumstance" like weather. Most
people don't know the thresholds, and the airlines aren't in a hurry to volunteer them. So there's a
genuine, everyday user need: *tell me, in plain terms, what I'm owed and why.*

That need is awkward for a plain RAG chatbot, and the reason is worth spelling out, because it's the
whole justification for the agentic design:

- **Half the question is law, half is arithmetic.** "My Budapest–London flight was cancelled, how much
  do I get?" needs a *grounded* legal answer (was this even compensable?) **and** an *exact* number
  (which band, what threshold). A language model is good at the first and unreliable at the second —
  ask a 3B model to multiply distances and apply a €400/€600 cutoff and it will occasionally make the
  number up. So the money has to come from real code, not the model.
- **The two halves need different machinery.** Looking up the law wants retrieval; computing the
  amount wants a deterministic function. One prompt can't cleanly be both.
- **Some questions are traps.** "Can I bring my dog?" or "why are fares so high?" aren't covered by
  this regulation at all. A naive chatbot answers anyway. We want it to *notice* it's out of scope and
  refuse, rather than invent a plausible-sounding rule.

An agent earns its keep here because the job is naturally a little workflow: figure out what's being
asked, send the legal part to retrieval and the money part to a calculator, run those independently,
then merge them into one grounded answer with the right caveats. That's what the graph below does.

---

## What it does

Four kinds of question, four paths:

- **"What are my rights?"** → looks up the answer in the legal corpus and quotes it back with a
  **citation** (which document, which article). If the corpus doesn't actually support an answer, it
  says so instead of bluffing.
- **"How much am I owed?"** → a calculator works out the distance, picks the right band
  (€250 / €400 / €600), applies the 3-hour threshold, and only *then* checks eligibility — weather
  gets you €0, the airline's own strike doesn't.
- **Both at once** → the question is split in two; the legal lookup and the calculation run side by
  side and are joined into a single answer.
- **Off-topic** (baggage fees, visas, pricing…) → caught and routed to a polite "that's outside what I
  cover" instead of a hallucinated rule.

---

## How it works

It's a **directed agent**: the graph fixes the control flow, so the path a question takes is
predictable and testable. That's a deliberate trade-off — I gave up the open-endedness of a
"model freely picks tools" agent in exchange for something I can actually evaluate and reason about.
The one genuinely self-correcting part is the RAG loop, which grades its own retrieval and retries if
it came back weak.

### The main graph (`src/graph.py`) — 7 nodes

```
                       ┌─────────┐
  user query  ───────▶ │ intake  │  pull out flight details + classify the question
                       └────┬────┘
                            ▼
                       ┌─────────┐
                       │ router  │  decide which path, write the decision into state
                       └────┬────┘
          ┌─────────────────┼───────────────────────────┬──────────────────┐
   rights_info        compensation_calc / mixed                         out_of_scope
          │                 │  (planner splits a mixed question in two)        │
          ▼                 ▼                                                  ▼
     ┌─────────┐     ┌──────────────── fan-out ───────────────┐          ┌──────────┐
     │   rag   │     │  rag → eligibility    ‖    calculator   │          │ fallback │
     │(subgraph)     │  (was it the airline's │  (the actual   │          └────┬─────┘
     └────┬────┘     │   fault?)             │   €250/400/600) │               │
          │          └──────────────── fan-in ────────────────┘               │
          │                          │                                         │
          └──────────────┬───────────┴─────────────────────────────────────────┘
                         ▼
                   ┌───────────┐
                   │ synthesize│  stitch the pieces together + apply the eligibility gate:
                   └─────┬─────┘  final = eligible ? amount : €0   (plain code, no model)
                         ▼
                   final answer
```

Reading it node by node:

- **`intake`** is the front door. It reads the question, pulls out any flight details (airports, how
  late, what went wrong), and decides what *kind* of question it is.
- **`router`** is a real node, not just a branching edge. It writes its decision into the shared state
  before the graph branches — which means the trace panel in the UI shows you *why* it went the way it
  did, not just where it ended up.
- **`planner`** only fires for the "both at once" case. It splits the question into the two real
  subtasks (look up the right, compute the amount) so they can run independently.
- **`eligibility`** is the one judgement call in the system: was this disruption the airline's
  responsibility? Its own staff striking — yes, that's on them, you get paid. Weather or air-traffic
  control — extraordinary, no compensation (though you may still be owed care or rerouting).
- **`calculator`** calls the money tool. No model involved (more on why below).
- **`synthesize`** merges everything and applies the gate: if it wasn't eligible, the amount becomes
  €0 no matter what the calculator said. This step is **plain code on purpose** — by the time we reach
  it, every piece is already grounded, so running another model pass here would only add latency and a
  fresh chance to hallucinate.
- **`fallback`** handles the off-topic questions — the hallucination firewall.

The interesting bit is the middle. For money and mixed questions, the two branches — `rag → eligibility`
and `calculator` — really do run **in parallel and then converge once**. That's not decoration: it's the
clearest way to *show* (not just claim) "decompose into subtasks and execute them independently." The
branches are different lengths, so `synthesize` is a *deferred* node, which makes LangGraph wait for both
sides and join them exactly once instead of firing twice.

### The RAG subgraph (`src/rag.py`)

The retrieval side is its own compiled graph, bolted onto the main graph as a single `rag` node. It's
shared — both the "what are my rights" path and the eligibility branch use it — and it's the most
self-correcting part of the system:

```
retrieve → grade the results → good enough?  ──yes──▶ generate the answer
                                    │
                                    └──no──▶ rewrite the query → retrieve again
                                            (bounded: at most REWRITE_MAX_RETRIES tries)
```

The idea: don't trust the first retrieval blindly. Grade it, and if it's weak, rephrase the query and
try once more before answering — but cap the retries so latency stays sane. The grader is a hybrid: the
model judges relevance, with a cosine-distance floor as a safety net so a confidently-wrong model can't
wave through junk. And `generate` is told, firmly, to answer *only* from what was retrieved — no outside
knowledge, no invented figures.

### Two tools (`src/tools.py`)

The task asks for at least two tools, at least one of which isn't retrieval. We have exactly that, and
both are real LangChain `@tool`s so there's no argument about whether they count:

- **`retrieve_passenger_rights(query)`** — the retrieval tool, used inside the RAG subgraph.
- **`calculate_compensation(...)`** — the non-retrieval one, and the reason the numbers are trustworthy.
  It takes airports and a delay, computes great-circle distance from real coordinates, picks the band,
  applies the threshold and the 50% reduction rule, and returns a number. **No model anywhere in it.**
  That matters twice over: it's why the amounts are exact, and it's why the calculator's output can
  double as the *ground truth* for the eval — a model-free function can't drift.

### State (`src/state.py`)

Everything the nodes produce flows through one typed `AgentState` — the question, its type, the flight
details, the retrieved docs, the rights answer, the eligibility verdict, the calculated amount, the final
answer, and a running `trace`. The `trace` is append-only (each node adds its bit), and it's what the UI
streams so you can watch the agent work.

---

## Tech stack

| Layer | Choice |
|---|---|
| Orchestration | **LangGraph** (main graph + a separate compiled RAG subgraph) |
| LLM | **`qwen2.5:3b-instruct`** via **Ollama** (local, `temperature=0`) |
| Embeddings | **`nomic-embed-text`** via Ollama (no torch / sentence-transformers) |
| Vector store | **ChromaDB** (persisted at `data/chroma/`, derived) |
| UI | **Streamlit** (one tab per layer: Chat · Corpus · RAG · Calculator · **Agent**) |
| Runtime | **Python 3.14**, stdlib `venv`, pinned `requirements.txt` |
| Container | `python:3.14-slim` + `docker-compose` (app + ollama) |

**Why a 3B model?** It has to run on a laptop with no paid API, so the choice is a trade-off, not a
free lunch. `qwen2.5:3b-instruct` is small enough to be fast locally and notably good at structured
output (which matters for the intake/routing step), at the cost of some prose polish. The eval section
below is honest about where that shows. The model sits behind a pluggable `LLM_BACKEND` seam
(`src/llm.py`), so swapping in a bigger model — or a stub for testing — is a config change, not surgery.
Every knob lives in `config.py` with env overrides (`OLLAMA_URL`, `MODEL`, `TOP_K`,
`REWRITE_MAX_RETRIES`, …).

---

## Quick start

### Option A — Docker, all-in-one (works on any OS) ✅ easiest clean run

```bash
docker compose up --build         # first run: builds app, pulls ~2.2 GB of models, ingests the corpus
# then open http://localhost:8501
```

First boot takes a few minutes (model pull + a one-time ingest, both cached in named volumes); after
that it's fast. The app waits for Ollama's healthcheck before it starts.

> 🍎 **On a Mac, use Option B instead.** A Linux container can't reach the Apple GPU, so the in-container
> model runs on CPU — measured **~5.5× slower** end to end (see [Performance](#evaluation--performance)).

### Option B — Docker app + Ollama on the host (the Mac fast path)

Run Ollama natively (so it uses the GPU) and point the containerized app at it. One env override, zero
code change:

```bash
# 1) on the host: run Ollama and pull both models
ollama serve            # if it isn't already running
ollama pull qwen2.5:3b-instruct
ollama pull nomic-embed-text

# 2) start just the app, aimed at the host's Ollama
OLLAMA_URL=http://host.docker.internal:11434 docker compose up -d --build --no-deps app
# then open http://localhost:8501
```

This is also the lightest option on disk — it reuses the host's models, skipping the ~1.5 GB Ollama
image and the ~2.2 GB download. (`host.docker.internal` comes free on Docker Desktop; on native Linux
the compose file already maps it via `extra_hosts`, so this works there too.)

### Option C — Local, no Docker (dev)

```bash
python3.14 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
# needs a local Ollama with qwen2.5:3b-instruct + nomic-embed-text pulled
python -m src.ingest                 # parse → chunk → embed the corpus → ChromaDB (idempotent)
streamlit run streamlit_app.py       # http://localhost:8501
```

### Eval & tests

```bash
python -m eval.functional_eval       # 15-question functional eval (routing / eligibility / amount / citations)
python -m eval.loadtest              # load test (N=50) with per-node timing + bottleneck
pytest tests/test_calculator.py      # the one classic unit test (the deterministic calculator)
```

### Managing the Docker stack

```bash
docker compose stop / start          # pause / resume (no disk churn)
docker compose down                  # remove containers, KEEP volumes (fast next start)
docker compose down -v               # also drop volumes (frees ~2.2 GB of models; re-pull next time)
```

---

## Using the UI

There's a tab per layer, building up to the **Agent** tab, which is the actual product:

- **Chat** — talk to the raw LLM, no agent (the starting point everything was built on).
- **Corpus** — browse the indexed chunks with their Article / Recital / Section labels and metadata.
- **RAG** — run a query through the corrective-RAG subgraph and watch retrieve → grade → (rewrite) →
  generate, with citations and the distances of what it retrieved.
- **Calculator** — flight inputs in, the full breakdown out (distance → band → threshold → reduction →
  amount).
- **Agent** — the whole graph: a live, node-by-node trace, the final grounded answer, citations, and the
  disclaimer. There's a live graph diagram and a set of example queries to try.

---

## Evaluation & performance

The short version is below; full methodology and numbers are in
[`notes/PHASE6_EVAL_RESULTS.md`](notes/PHASE6_EVAL_RESULTS.md). Ground truth is pinned to what
Reg. 261/2004 *actually says* (every route distance recomputed from real coordinates before fixing the
expected amount), not to whatever the model happens to output.

### Is it correct? (15-question functional eval, `qwen2.5:3b-instruct`, temperature 0)

| Dimension | Score |
|---|---|
| Routing (picking the right lane) | 10/14 (71%) — the weak spot |
| Eligibility (does it count?) | **8/8 (100%)** |
| Amount (the gated final €) | **8/8 (100%)** |
| Citation present | **7/7 (100%)** |
| Citation correct | 6/7 (86%) |

In plain terms: **the money is always right, and so is the grounding.** Every amount and every
eligibility call was correct, and every rights answer came with a real citation — nothing invented.
The one soft spot is *sorting questions into the right lane*: when a question mixes a disruption with a
word like "refund" or "how much," the small model tends to read it as a money question. The saving grace
is that it barely matters for the answer — the money and mixed lanes both run the eligibility branch, so
even a misrouted question comes out with the **correct number**; only the path it took looks different.
The fix (force the intake step to fill a strict schema instead of replying freely) is understood and
queued for a later review phase.

### Is it fast enough? (load test, N=50, sequential)

- **One query takes ~18 s** on this hardware (mean 17.8 s, p95 25.7 s). The fastest is the off-topic
  path at 2.5 s — it skips the model entirely.
- **All of that time is the model thinking.** The LLM nodes are 100% of the work; the calculator, the
  vector search, the routing and the answer-assembly add up to basically nothing (0.0%). The system is
  slow *only* because of the local model, not because of anything in our code.
- **The single most expensive step is the RAG node (~69%)** — reading the law and writing the grounded
  answer — followed by intake (~24%). The only lever that moves latency is the number and cost of LLM
  calls, which is exactly why several steps were built to *avoid* a model call (deterministic synthesize,
  a no-model eligibility shortcut, the instant off-topic bail-out). The load test confirms each of those
  saves real time. The next lever — skip the heavy RAG step for pure money questions, which don't need
  it — is identified and deferred to the review phase.

### CPU vs GPU (the Docker caveat)

Same queries, same settings, host Metal GPU vs the CPU-only container: the in-container model is
**~5.5× slower** end to end (mean 25 s → 140 s on the LLM-heavy routes). A bare single-prompt benchmark
is only ~2.2× — the gap widens in practice because each query fires several model calls and the RAG step
does a big context prefill, which is where CPU hurts most. That ~5.5× is the entire reason Option B (the
Mac fast path) exists.

---

## Project structure

```
config.py              # every knob (env-overridable): MODEL, OLLAMA_URL, TOP_K, paths, …
streamlit_app.py       # the UI (one tab per layer); ui_components.py = shared renderers
src/
  llm.py               # get_llm() behind the LLM_BACKEND seam
  state.py             # the typed AgentState (+ append-only trace reducer)
  graph.py             # the main 7-node graph + run_agent()
  rag.py               # the compiled corrective-RAG subgraph
  tools.py             # @tool retrieve_passenger_rights + @tool calculate_compensation
  calculator.py        # pure, deterministic Art. 7 logic (haversine + band table)
  ingest.py            # generic drop-in corpus loader → structure-aware chunkers → Chroma
  store.py             # Chroma client + Ollama embeddings
eval/                  # eval_set.yaml + functional_eval.py + loadtest.py
tests/test_calculator.py
docker/                # entrypoint.sh + prepare.py (wait for Ollama → pull models → ingest)
Dockerfile  docker-compose.yml  .dockerignore
data/corpus/           # the frozen legal corpus (committed); data/chroma/ is derived (gitignored)
notes/                 # design proposal, decisions, eval results, review findings
```

One thing worth calling out: ingestion is a **generic drop-in loader**. Drop a new file into
`data/corpus/`, re-run `python -m src.ingest`, and it's detected, chunked by its structure, and indexed —
no code changes. The chunking follows the *legal* structure (by Article / Recital, splitting only
oversized articles) rather than blind fixed-size windows, so citations land on a real provision instead
of an arbitrary slice.

---

## Corpus & sources

The corpus is a **frozen, dated snapshot** committed under `data/corpus/` — it's the source of truth,
and the ChromaDB index is just rebuilt from it. Four documents: the full **Regulation (EC) No 261/2004**,
the **2024 Commission interpretative guidelines**, the EUR-Lex **legislative summary**, and a
**Your Europe** plain-language summary.

Licensing and provenance are in [`data/SOURCES.md`](data/SOURCES.md). EUR-Lex / Publications Office
content is © European Union (reusable with acknowledgement); the OpenFlights `airports.dat` the
calculator uses (not part of the RAG corpus) is **ODbL** — attributed accordingly.

---

## Reproducibility

Versions are pinned (`requirements.txt`, `python:3.14-slim`), `temperature=0` with fixed seeds where the
backend supports it, ingestion is idempotent, and the corpus is committed — so a fresh clone rebuilds the
exact same index offline. The vector store is the only derived artifact, gitignored and rebuilt
deterministically from the corpus.

---

## Caveats

- **The 2025 reform is *not* encoded.** Reg. 261/2004 is being reformed (Council position June 2025;
  Parliament TRAN committee October 2025) but isn't enacted yet. This system targets the **current,
  in-force rules**: the 3-hour threshold and the €250 / €400 / €600 bands. The proposed new thresholds
  are deliberately left out.
- **Coverage is asymmetric.** Flights *leaving* the EU are covered on any airline; flights *into* the EU
  are covered only on EU airlines. The system reflects this — and it's one of the two cases the eval
  flags as still imperfect.
- **Not legal advice.** General information only. For a real claim, check the official texts or talk to a
  qualified adviser.
