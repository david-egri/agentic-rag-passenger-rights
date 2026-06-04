# Phase 7 — Docker + README: Implementation Plan

> **Status:** scoping/design only — not started. This is the consolidated plan worked out
> before kicking off `phase/7-docker-readme`. It expands the Phase 7 stub in `PLAN.md:81-86`
> and records the *why* behind each choice (the decision entries should be mirrored into
> `DECISIONS.md` when the phase starts). See `notes/TASK_DESCRIPTION.md` §3 + §5 for the
> graded requirements this satisfies.

---

## 1. Goal & acceptance bar

**Goal:** a reproducible entry point — package the existing solution so a fresh clone runs
end-to-end with documented commands.

**Done when:**
- `docker compose up` runs the whole system end-to-end (Streamlit UI + Ollama + grounded RAG + calculator).
- A fresh clone can be set up **from the README alone** — corpus committed, models pulled, Chroma rebuilt by ingest.

**What the task spec demands (`TASK_DESCRIPTION.md`):**
- **Dockerfile — mandatory** (§3, line 52-53).
- **docker-compose.yml — bonus** for "wrapping multi-component solutions" (§3, line 54). Our app + Ollama
  is genuinely multi-component, so the bonus is earned by the 2-container design — **no UI/API split needed**.
- **README — mandatory** (§5): problem, architecture + design justification, eval/perf summary, install/run.
- **Reproducibility** is a graded criterion (§5) — the *reason* the Dockerfile exists, and the real bar to build to.

---

## 2. Key finding: scope is "new files + one decision", not code changes

Verified against the code: **dockerization touches zero application logic.** Every value Docker
needs to change flows through `config.py` via env override, and the code reads from `config.*`:

| What Docker changes | Where | Hardcoded? |
|---|---|---|
| Ollama URL (`localhost` → `ollama` service) | `config.py:15` → `llm.py:22`, `store.py:31` (`base_url=config.OLLAMA_URL`) | **No** — env-overridable |
| Chroma path | `config.py:29` → `store.py:49` | **No** |
| Corpus path | `config.py:31` → `ingest.py:249` | **No** |
| Airports data path | `config.py:37` → `calculator.py:72` | **No** |

The only `localhost`/`11434` literal in the tree is the *default* on `config.py:15`, wrapped in
`os.getenv`. This is the payoff of the Phase 1 config seam ("config over hardcoding") — Docker was
effectively pre-paid. The work is authoring new files + one repo-hygiene decision (commit corpus).

---

## 3. Target architecture — 2 containers

```
┌─────────────────────── docker compose ───────────────────────┐
│                                                               │
│   ┌─────────────────┐         ┌──────────────────────────┐   │
│   │   app            │  HTTP   │   ollama                 │   │
│   │  (whole solution)│────────▶│  (LLM + embeddings)      │   │
│   │                  │ :11434  │                          │   │
│   │  python:3.14-slim│         │  image: ollama/ollama    │   │
│   │  Streamlit :8501 │         │  serves:                 │   │
│   │  + LangGraph     │         │   • qwen2.5:3b-instruct  │   │
│   │  + RAG + calc    │         │   • nomic-embed-text     │   │
│   └────────┬─────────┘         └───────────┬──────────────┘   │
│            │                               │                  │
│      ┌─────┴──────┐                  ┌─────┴──────┐           │
│      │ vol: chroma │                 │ vol: models │          │
│      │ (derived)   │                 │ (~2.2 GB)   │          │
│      └────────────┘                  └────────────┘          │
│                                                               │
└───────────────────────────────────────────────────────────────┘
         host :8501  ──▶  browser (Streamlit UI)
```

### Service 1 — `ollama` (standalone LLM + embedding server)
- Official `ollama/ollama` image (pulled, not built).
- Serves **both** the chat model (`qwen2.5:3b-instruct`) and the embedding model (`nomic-embed-text`) —
  one server, both `llm.py` and `store.py` point at the same `OLLAMA_URL`.
- **Named volume** on `/root/.ollama` so ~2.2 GB of models survive `down`/`up`.
- **Healthcheck** so the app waits until it's actually serving.
- **Resource limits** declared in compose (a 3B model has a real memory floor).

### Service 2 — `app` (the entire solution, one image)
- Built from `python:3.14-slim` (matches the local `.python-version` pin → identical wheel resolution).
- Contains all of `src/` + `streamlit_app.py` + `ui_components.py` + `config.py`.
- The compiled `graph` is called **in-process** by Streamlit (`graph.stream`) — the live trace panel
  stays trivial, no HTTP/SSE. This protects the graded "demonstrate agent operation" requirement.
- Talks to Ollama via `OLLAMA_URL=http://ollama:11434` (one env var — no code change).
- **Named volume** on `data/chroma` so the derived vector store persists.
- **Entrypoint:** idempotent `python -m src.ingest` → `streamlit run streamlit_app.py`.
- Publishes `8501` to the host.

---

## 4. Corpus vs. Chroma — what lives where, built when

| Artifact | Lives where | Built when |
|---|---|---|
| **Corpus** (`data/corpus/` + `airports.dat`) | Git repo (committed) | authored once, frozen |
| **App code + deps** | Docker **image** | `docker build` |
| **Chroma vector DB** | Named **volume** | **runtime**, by the entrypoint, after Ollama is healthy |

**Critical ordering point:** Chroma is **not** built in the Dockerfile. Ingestion calls Ollama to embed
each chunk, and Ollama is not reachable during `docker build` (isolated, no sibling services). So the
Chroma build is a **runtime** step in the entrypoint, gated on the Ollama healthcheck:

```
docker build      →  bake CODE + deps into image   (NO ingestion)
docker compose up →  ollama starts → healthy
                     app entrypoint: 1) python -m src.ingest  ← Chroma built HERE (idempotent)
                                     2) streamlit run …
```

Consequence: **first `up` is slower** (embeds the whole corpus once); subsequent starts are a no-op
because the volume keeps Chroma. Worth a one-line README mention. `data/chroma/` stays **gitignored**
and in `.dockerignore` — never bake a stale vector store into the image or repo.

---

## 5. Files to create (zero `src/` logic changes)

1. **`Dockerfile`** — multi-stage (builder → slim runtime), non-root user, layer-cache ordering
   (`COPY requirements.txt` → `pip install` → *then* `COPY` source).
2. **`.dockerignore`** — exclude `.venv/`, `data/chroma/`, `.git/`, `__pycache__/`, `*.pyc`.
3. **`docker-compose.yml`** — both services, healthcheck-gated `depends_on`, named volumes
   (models + chroma), resource limits on Ollama.
4. **entrypoint script** — idempotent `src.ingest` → launch Streamlit.
5. **`README.md`** — full rewrite (see §7).
6. **`DECISIONS.md` entries** — own the conscious deviations (see §8).

---

## 6. Decisions (recommendations baked in — lock at phase start)

| # | Decision | Recommendation | Why |
|---|---|---|---|
| D1 | **Model pull into Ollama** (fresh container starts empty; host models don't carry in) | Init sidecar (or entrypoint pull) for one-command `up`; document manual `docker compose exec ollama ollama pull …` as fallback | Best "fresh clone, one command" reproducibility |
| D2 | **macOS / GPU reality** | Portable compose-Ollama as **default**; document host-native Ollama override (`OLLAMA_URL=http://host.docker.internal:11434`) as the Apple-Silicon fast path | A Linux container can't use the Apple GPU → in-container Ollama is CPU-only/slow on Mac. Env seam makes this a README note, not a code branch |
| D3 | **Corpus provenance** (currently `/data/` fully gitignored — see DECISIONS `gitignore-data-for-now`) | **Commit the frozen corpus snapshot** — un-ignore `data/corpus/` + `airports.dat`; keep `data/chroma/` ignored. Carry `data/SOURCES.md` attribution into a tracked location | Simplest + robust; CLAUDE.md hygiene prefers committing the frozen corpus; fetch-script is fragile (EUR-Lex WAF, per `corpus-2024-guidelines`) |
| D4 | **Ingestion placement** | Entrypoint (idempotent) for prototype convenience; note the smell in DECISIONS | Pragmatic; a separate init-job is the "proper" pattern but overkill here |
| D5 | **Callable API (UI/API split or sibling endpoint)** | **Defer** as a stretch goal | Rubric already satisfied by app+ollama; additive later with zero rework (parallel in-process entry point, never on the trace path) |

---

## 7. README contents (mandatory deliverable)

- **Problem & objective** — EU air passenger rights (Reg. 261/2004); user need; why agentic RAG fits.
- **Architecture + design justification** — the graph (≥5 nodes, routing, fan-out/fan-in), the modular
  RAG subgraph, the two tools (retrieval + deterministic calculator), typed state; the directed-agent
  framing; local-LLM choice + trade-offs.
- **Eval + perf summary** — pull from `notes/PHASE6_EVAL_RESULTS.md` (routing/eligibility/amount/citation
  scores; N=50 latency, `rag` bottleneck, optimizations).
- **Install / run** — both paths: `docker compose up` (portable) and the host-Ollama fast path on macOS;
  plus the plain `venv` commands from CLAUDE.md.
- **Caveats** — the pending 2025 reform is **not** encoded (non-negotiable #2); "not legal advice".

---

## 8. Best-practice notes (industry lens, beyond the rubric)

These are what turn "I wrote a Dockerfile" into "I made defensible deployment decisions":

- **Aligned with best practice:** Ollama-as-its-own-service (Twelve-Factor attached resource), config via
  env (Twelve-Factor), Chroma isolated as the one stateful volume.
- **Conscious deviation 1 — no UI/API split.** By the book, Streamlit is a presentation layer and the
  agent belongs behind a stateless API (independent scaling, Streamlit's re-run model is hostile to
  long work). We **right-size** to a single-user local prototype: the split's benefits are unrealized,
  its costs (FastAPI + SSE/WS to preserve the live trace) are real. Deliberate right-sizing > reflexive
  microservices. → DECISIONS entry.
- **Conscious deviation 2 — ingest in entrypoint.** Mixes a one-time data job with the serving process;
  the "proper" pattern is a separate init job. Acceptable for a prototype for one-command convenience.
  → DECISIONS entry.
- **Image hygiene (non-negotiable even for a prototype):** multi-stage build, non-root user,
  `.dockerignore`, cache-friendly layer order, exact/pinned base image, `HEALTHCHECK` +
  `depends_on: condition: service_healthy`, Ollama resource limits.
- **The macOS/GPU caveat (D2)** is the single highest-value real-world insight — documenting it signals
  understanding of the deployment substrate, not just `docker build`.

---

## 9. Execution checklist (when the phase kicks off)

1. Lock decisions D1–D5 (§6).
2. Branch `phase/7-docker-readme` from `main`; push early.
3. Un-ignore + commit the corpus snapshot (D3) + attribution.
4. Write `.dockerignore`, `Dockerfile` (multi-stage, non-root), entrypoint.
5. Write `docker-compose.yml` (2 services, healthcheck, volumes, limits, model-pull per D1).
6. Verify `docker compose up` end-to-end on a clean state (models pull, ingest builds Chroma, UI serves).
7. Rewrite `README.md` (§7).
8. Add `DECISIONS.md` entries for D1–D5 + the two deviations.
9. Tick `PLAN.md` Phase 7 boxes; close with the `--no-ff` merge + `phase-7-docker-readme` tag (on the user's say-so).

---

## 10. Plain-language summary (no jargon)

Think of the project as having two parts that need to run together:

1. **The "brain server" (Ollama)** — a ready-made program that runs the local AI model. We don't build
   this ourselves; we just use the official version. It's heavy and does its own thing, so it gets its
   **own box** (container).

2. **Our app** — everything we wrote: the chat screen, the step-by-step agent, the law-lookup, and the
   compensation calculator. This goes in a **second box**.

A small "recipe" file (**docker-compose.yml**) says "start both boxes and let them talk to each other."
So instead of installing Python, the AI model, and the database by hand, anyone can type one command —
`docker compose up` — and the whole thing comes alive.

A few practical realities we planned around:

- **The text the AI reads** (the EU law documents) is small and unchanging, so we just **store it in the
  project** like any other file. ✅
- **The searchable index** the AI uses (the "vector database") is *built from* those documents, so we
  **don't store it** — we let the app **build it automatically the first time it starts**. That first
  start is a bit slower because it's doing that work once; after that it's instant because it remembers.
- **The AI model files are big (~2 GB)**, so we tell the system to **download them once and keep them**,
  instead of re-downloading every time.
- **On a Mac specifically**, the AI runs faster if it uses the computer directly instead of from inside a
  box (Apple's chip won't share its speed with the box). So we offer **two ways to run it**: the simple
  all-in-one way (works anywhere, a bit slower on Mac), and a faster Mac-friendly way — and we explain
  both in the README. Switching between them is just one setting, no code change.
- We could also split our app into a separate "engine" and "screen," like a real production system —
  but for a single-person demo that's extra complexity for no real benefit, so we keep it simple now and
  leave the door open to add it later. We can also add a small "call it like a service" feature later
  without touching anything we've built.

**Bottom line:** the hard thinking was already done back when we set the project up to read its settings
from the environment — so dockerizing means **writing a few new setup files, not changing the actual
program.** One decision to make (store the law documents in the repo — yes), and the rest is careful
plumbing. Then anyone, anywhere, can run the whole thing with a single command.
