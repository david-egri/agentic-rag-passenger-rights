# Project Proposal — Agentic RAG Chatbot for EU Air Passenger Rights

> **Purpose of this document.** This is the design spec and build guide for an Agentic RAG chatbot (LangGraph, Python) that answers questions about EU air passenger rights and computes flight-disruption compensation. It is written to be handed to **Claude Code** as the source of truth during implementation: it states the corpus, the chunking strategy, the LangGraph node/tool design, the evaluation plan, and an acceptance checklist mapped to the grading criteria.
>
> **Scope discipline.** This is an interview prototype. Favor a small, clean, reproducible build over breadth. "Quality processing, not quantity" is an explicit grading criterion.

---

## 0. TL;DR for the implementer

- **Domain:** EU air passenger rights (Regulation (EC) No 261/2004) — a passenger-facing assistant that (a) explains rights and (b) computes compensation entitlement.
- **Why this domain:** naturally produces conditional routing (info-lookup vs. computation), a genuine non-retrieval tool (distance + rules math), decomposable mixed questions, a tiny authoritative free corpus, and deterministic ground truth for evaluation.
- **Corpus:** 3 authoritative text documents (regulation + interpretive guidelines + plain-language summary) for RAG, plus the OpenFlights airport dataset + a small rules table for the calculator tool. All free.
- **Stack:** Python, LangGraph, ChromaDB (vector store), `sentence-transformers` (local embeddings), local LLM via **Ollama** (with a **dummy/stub LLM** mode for CI and load testing), Streamlit UI, Docker + docker-compose.
- **Agentic shape:** main graph with 7 nodes (≥5 required) + a modular **RAG subgraph** (does not count toward the 5) that implements corrective RAG (retrieve → grade → optional rewrite → generate). Two tools: `retrieve_passenger_rights` (retrieval) and `calculate_compensation` (non-retrieval).

---

## 1. Problem Definition & Justification

### 1.1 The problem
Air passengers in the EU have strong statutory rights to care, rerouting, and cash compensation when flights are delayed, cancelled, or overbooked — but those rights are buried in legal text, riddled with exceptions ("extraordinary circumstances"), and the compensation amount depends on a distance calculation most travelers can't do in their head. As a result, a large share of eligible passengers never claim, and many ask for compensation they aren't entitled to.

### 1.2 Why it's relevant
Flight disruption is a high-volume, high-friction consumer problem across the EU. The rules are stable, public, and authoritative, yet practically inaccessible to the people they protect. A grounded assistant that both *explains* and *quantifies* entitlement closes a real information gap.

### 1.3 What user need it fulfills
A passenger after a disruption has two intertwined questions: **"Am I entitled to anything?"** (interpretation of the rules against their situation) and **"How much, exactly?"** (a deterministic calculation). They need a single answer that is correct, grounded in the regulation, and explained in plain language.

### 1.4 Why agentic RAG is the right approach
- **Heterogeneous intents → routing.** "What are my rights?" needs retrieval over legal text; "how much am I owed for a 4h delay from BUD to LHR?" needs a calculation. A router that dispatches to different subgraphs is load-bearing, not decorative.
- **Decomposition.** "My staff-strike-cancelled Paris–Rome flight got me in 6h late — am I owed anything and how much?" must be split into an eligibility judgment (RAG) and a compensation computation (tool), then recombined.
- **Grounding + non-retrieval computation in one flow.** Pure RAG can't reliably do distance math; a pure calculator can't reason about exceptions. The agent orchestrates both and keeps grounded citations.
- **Self-correction (corrective RAG).** Legal questions are sensitive to retrieval quality; a grade-and-rewrite loop in the RAG subgraph materially improves answer faithfulness.

### 1.5 Honest limitation to state in the README
Regulation (EC) No 261/2004 is currently under reform: the EU Council agreed a negotiating position in June 2025 and the Parliament's TRAN committee adopted its guidelines in October 2025 (notably disagreeing on whether to raise the delay threshold from 3 hours to 4–6 hours). As of build time this is **not yet enacted**, so the prototype targets the **current in-force rules** and treats the corpus as a **frozen, dated snapshot**. Surfacing this in the README demonstrates domain awareness and is cheap to write.

---

## 2. Corpus

All sources are free and redistributable; commit a frozen snapshot into the repo under `data/corpus/` with a `SOURCES.md` recording URL + retrieval date + license/attribution.

### 2.1 Text corpus (feeds the RAG subgraph) — keep it to 3 documents

| # | Document | Role | Source |
|---|----------|------|--------|
| 1 | **Regulation (EC) No 261/2004**, full consolidated text | Backbone: articles & recitals, authoritative wording | EUR-Lex: `https://eur-lex.europa.eu/eli/reg/2004/261/oj/eng` |
| 2 | **Commission Interpretative Guidelines on Regulation 261/2004** (Commission Notice, OJ C 214, 15.6.2016) | Explains the fuzzy parts (extraordinary circumstances, how delay is measured, edge cases) in near-Q&A form — best retrieval value | EUR-Lex (search the title; CELEX `52016XC0615(01)`) |
| 3 | **Plain-language summary** of EU air passenger rights | Bridges colloquial user phrasing to formal regulation wording (improves recall) | EUR-Lex summary page (`legissum` for 261/2004) or the official `europa.eu` air passenger rights page |

> **Do not** scrape claim-farm blogs or add dozens of documents. Three authoritative, well-chunked sources is the correct judgment call for this brief.

### 2.2 Structured data (feeds the non-retrieval calculator tool)

| Asset | Role | Source |
|-------|------|--------|
| **OpenFlights `airports.dat`** | IATA/ICAO code → latitude/longitude for ~7,000 airports; used to compute great-circle distance | `openflights.org/data.html` or the `jpatokal/openflights` GitHub repo (ODbL — attribute it) |
| **Compensation rules table** (author it yourself, small JSON/YAML) | Distance bands → entitlement amounts and delay thresholds, plus the 50%-reduction rerouting rule | Hand-built from Reg. 261/2004 Art. 7; commit to `data/rules/compensation_rules.yaml` |

**Current in-force rules to encode (anchor the calculator to these):**
- Delay ≥ **3 hours** at final destination → compensation may be due (subject to "extraordinary circumstances").
- Distance bands (Art. 7):
  - ≤ 1500 km → **€250**
  - 1500–3500 km (and all intra-EU flights over 1500 km) → **€400**
  - > 3500 km → **€600**
- **50% reduction** where the airline offers re-routing and the arrival delay stays under band-specific limits (2h / 3h / 4h respectively).
- Distance is the **great-circle distance between departure and final destination** (haversine on the OpenFlights coordinates).

---

## 3. Corpus Processing & Chunking Strategy

**Principle: chunk by legal structure, not by fixed token windows.** Being able to explain this choice in the interview is itself a signal of judgment.

### 3.1 Pipeline (`src/ingest/`)
Write ingestion as a **generic, drop-in directory loader**, not a per-document hand-tuned script: dropping a new file into `data/corpus/` → detect its type → apply the matching chunker → re-run ingestion → it's indexed, **with no code changes**. That "adding a new regulation/guideline is a drop-in operation" is exactly what the *scalable data integration* criterion rewards.

1. **Acquire & freeze** — download the 3 docs to `data/corpus/`, prefer the EUR-Lex HTML (cleanly structured) over PDF.
2. **Parse structure** — dispatch on document type to the right structure-aware chunker: regulation → split on **Article** and **Recital** boundaries; guidelines → split on their section/heading boundaries. Each resulting unit is one logical chunk. New document types add a chunker behind the same dispatch, not a new pipeline.
3. **Size guard** — if a single article exceeds ~1000 tokens, sub-split on paragraph numbering (Art. 7(1), 7(2)...) with a small overlap (~50 tokens) so cross-paragraph references survive.
4. **Attach metadata to every chunk** (critical for clean citations and for the grader node):
   ```json
   {
     "source": "Reg_261_2004 | Interpretive_Guidelines | Summary",
     "article": "Art. 7" ,
     "title": "Right to compensation",
     "url": "https://eur-lex.europa.eu/...",
     "retrieved_at": "2026-06-03",
     "chunk_id": "reg261_art7_p1"
   }
   ```
5. **Embed** with a local model (see 5.1) and persist to **ChromaDB** at `data/chroma/`. Make ingestion idempotent (re-running rebuilds cleanly) and expose it as a documented command (e.g. `python -m src.ingest`).

### 3.2 Retrieval config
- Top-k = 4–6 to start; expose as config.
- Store the metadata so the **generate** node can emit citations like `[Reg 261/2004, Art. 7]` — never raw chunk text.
- Optional but recommended: keep an in-memory **embedding cache** so the load test isn't dominated by re-embedding identical queries.

---

## 4. Architecture — How the Domain Maps to the Required Design

### 4.1 Requirement → design mapping (use this table in the README)

| Task requirement | How this design satisfies it |
|------------------|------------------------------|
| ≥ 5 nodes | Main graph has **7 nodes** (see 4.3) |
| Autonomous decision-making / conditional routing | **Router** node (writes the routing decision to state) + conditional edge after it; post-eligibility conditional edge; grade→rewrite decision inside the RAG subgraph |
| Decomposition into subtasks **and independent execution** | **Planner** node emits subtasks via the LLM; `mixed` runs as a **fan-out → fan-in** of a RAG/eligibility branch and a calculator branch that converge at synthesize |
| State management for intermediate results | Typed `AgentState` carried across all nodes (see 4.2) |
| ≥ 2 tools, ≥ 1 non-retrieval | `retrieve_passenger_rights` (retrieval) + `calculate_compensation` (non-retrieval math), both as explicit LangChain `@tool`s |
| Dedicated modular RAG subgraph, not counted in the 5 | Separate **compiled `StateGraph`** added to the main graph via `add_node` (invoked as a single node) |

### 4.2 State schema (`src/state.py`)
```python
from typing import TypedDict, Literal, Optional
class AgentState(TypedDict, total=False):
    user_query: str
    query_type: Literal["rights_info", "compensation_calc", "mixed", "out_of_scope"]
    flight_details: dict        # {origin_iata, dest_iata, delay_hours, disruption_type, reason}
    subtasks: list[str]         # populated by planner for mixed queries
    retrieved_docs: list[dict]  # chunk text + metadata
    rag_answer: str
    rag_citations: list[dict]
    eligibility: dict           # {eligible: bool, rationale: str}
    calc_result: dict           # {distance_km, band, amount_eur, reduction_applied}
    final_answer: str
    trace: list[dict]           # per-node log for the Streamlit "agent steps" panel
```

### 4.3 Main graph nodes (the ≥5)
```
                              ┌───────────────┐
       user query ──────────► │   1. INTAKE   │  extract flight_details + classify query_type
                              └───────┬───────┘
                                      ▼
                              ┌───────────────┐
                              │   2. ROUTER   │  node — writes query_type to state
                              └───────┬───────┘
                                      │ conditional edge on query_type
          ┌───────────────────┬───────┴───────────┬──────────────────────┐
     rights_info         out_of_scope           mixed             compensation_calc
          │                   │                    │                      │
          ▼                   ▼                    ▼                      │
   ┌─────────────┐     ┌─────────────┐      ┌─────────────┐               │
   │     RAG     │     │ 7. FALLBACK │      │ 3. PLANNER  │               │
   │   SUBGRAPH  │     │   honest    │      │  LLM emits  │               │
   │ (rights ans)│     │   decline   │      │   subtasks  │               │
   └──────┬──────┘     └──────┬──────┘      └──────┬──────┘               │
          │                   │                    └───────────┬──────────┘
          │                   │                                │  FAN-OUT — two
          │                   │                    ┌───────────┴───────────┐  independent
          │                   │                    ▼                       ▼  branches
          │                   │          ┌──────────────────┐   ┌──────────────────┐
          │                   │          │   RAG SUBGRAPH   │   │  5. CALCULATOR   │
          │                   │          │        │         │   │  deterministic   │
          │                   │          │        ▼         │   │  tool, no LLM    │
          │                   │          │  4. ELIGIBILITY  │   │ → candidate €amt │
          │                   │          │   is it owed?    │   │  (eligibility-   │
          │                   │          │                  │   │   agnostic)      │
          │                   │          └─────────┬────────┘   └─────────┬────────┘
          │                   │                    └───────────┬──────────┘
          │                   │                                │  FAN-IN
          │                   │                                ▼
          │                   │                  ┌──────────────────────────────┐
          └───────────────────┼─────────────────►│        6. SYNTHESIZE         │
                              │                  │  gate: final = eligible      │
                              │                  │         ? candidate : 0      │
                              │                  │  + rights answer + citations │
                              │                  │  + "not legal advice"        │
                              │                  └───────────────┬──────────────┘
                              ▼                                  ▼
                             END                                END

Notes:
- The **router** is a real node (writes `query_type` to state); the 4-way split is the conditional
  edge after it. `rights_info` → RAG subgraph → synthesize; `out_of_scope` → fallback → END.
- `mixed` and `compensation_calc` share the same **fan-out → fan-in**: an eligibility branch
  (RAG subgraph → eligibility) and a calculator branch run as **independent** siblings. `mixed`
  passes through the **planner** first (LLM emits subtasks); `compensation_calc` enters the fan-out
  directly. The modular RAG subgraph is reused in both the `rights_info` and eligibility branches.
- The branches are independent because they consume different inputs (reason+rules vs. route+delay);
  the only coupling is the **gate at synthesize** (`final = eligible ? candidate : 0`), so the
  calculator never waits on eligibility.
```

1. **Intake / Query Understanding** — extract `flight_details` entities (origin, destination, delay hours, disruption type, stated reason) and classify intent into one of the four `query_type`s. One LLM call with a structured-output prompt (return JSON).
2. **Router** — a genuine node that writes its routing decision into `state` (so it shows up in the trace panel); a conditional edge *after* it dispatches on `query_type`: `rights_info` → RAG only; `compensation_calc` → calculator path; `mixed` → planner; `out_of_scope` → fallback. (Node + following edge, **not** a bare conditional edge — pick one model and keep it consistent.)
3. **Planner / Decomposer** — for `mixed`, the **LLM emits** the subtasks (not a hardcoded split), then the graph **fans out** to a RAG/eligibility branch and a calculator branch that run independently and **fan in** at synthesize. This is what demonstrates "decomposition into subtasks **and independent execution**."

   These branches are genuinely independent because they consume **different inputs**: eligibility needs the disruption *reason* + the rules (RAG); the calculator needs only route + delay. Neither consumes the other's output — so the calculator is **eligibility-agnostic** and computes the **statutory candidate amount** (what Art. 7 awards for that distance band + delay). The dependency between "is it owed?" and "how much?" is a **combination dependency at fan-in**, not an input dependency between branches: `final_amount = eligible ? candidate_amount : 0`, applied at synthesize. Computing a candidate amount that may be zeroed is free (the calculator is deterministic, no LLM) and useful — synthesize can give a counterfactual ("you'd ordinarily be owed €400, but the cause was weather → no compensation due, though care/rerouting still apply").
4. **Eligibility** — autonomous decision node: combines retrieved rules + extracted reason to decide whether the disruption is compensable (e.g., own-airline staff strike = **not** extraordinary → eligible; weather = extraordinary → not eligible). Sets `eligibility` and conditionally suppresses compensation.
5. **Compensation Calculator** — calls the `calculate_compensation` tool (non-retrieval).
6. **Synthesize / Compose** — merges everything into a grounded, plain-language final answer **with citations** and a one-line "this is general information, not legal advice" disclaimer.
7. **Fallback / Out-of-scope** — handles questions the corpus doesn't cover (baggage fees, pets, visas) with an honest "outside my scope" reply. This is your hallucination firewall.

### 4.4 RAG subgraph (modular, NOT counted in the 5) — `src/rag/graph.py`
Implement **corrective RAG** so it's genuinely "agentic":
```
retrieve ──► grade_documents ──► (relevant?) ──► generate (grounded + citations)
                   │
                   └─ (not relevant) ──► rewrite_query ──► retrieve (loop, max 1–2 times)
```
- **retrieve** — vector search via the `retrieve_passenger_rights` tool.
- **grade_documents** — LLM (or heuristic) judges whether retrieved chunks actually answer the question.
- **rewrite_query** — if not, reformulate and retry once or twice (bounded loop to avoid runaway latency).
- **generate** — answer strictly from retrieved chunks; if support is insufficient, say so rather than inventing. Emits `rag_citations`.

Build this as an actually-compiled `StateGraph` and attach it to the main graph via `add_node` so it's literally a subgraph invoked as a node — **not** a Python function the main graph calls. That wiring is exactly the "callable from the main workflow but does not count toward the nodes" requirement.

---

## 5. Tools

Both capabilities are exposed as explicit LangChain `@tool`s (not plain functions buried in nodes), so there's no ambiguity about whether they count. Wrapping the calculator as a `@tool` does **not** introduce an LLM call — it stays deterministic.

### 5.1 Tool 1 — `retrieve_passenger_rights(query: str) -> list[dict]` (retrieval)
- Embeds the query with the local embedding model and runs top-k similarity search over ChromaDB.
- Returns chunk text + metadata. Used inside the RAG subgraph's `retrieve` node.

### 5.2 Tool 2 — `calculate_compensation(origin_iata, dest_iata, delay_hours, disruption_type, rerouting_offered=False) -> dict` (NON-retrieval — the centerpiece)
Deterministic, testable, no LLM:
1. Look up coordinates for both airports from the OpenFlights table.
2. Compute great-circle distance (haversine).
3. Map distance → band → base amount from `compensation_rules.yaml`.
4. Apply the 3-hour threshold and the 50%-reduction rule where relevant.
5. Return `{distance_km, band, base_amount_eur, reduction_applied, final_amount_eur, threshold_met}`.

> This is what makes the domain shine: a real computation that retrieval cannot do, with deterministic output that doubles as exact eval ground truth.

### 5.3 Optional extra tools (mention as "future work" unless time permits)
- `lookup_airport(name_or_iata)` — fuzzy-resolve airport names to IATA codes (improves UX when users type "Heathrow" not "LHR"). Can be folded into Tool 2.
- `check_claim_deadline(country, flight_date)` — claim limitation periods vary by member state; a small date tool. Adds a third, clearly non-retrieval capability if you want more agentic surface.

---

## 6. Model Selection (no paid APIs)

### 6.1 Recommendation
- **LLM:** run a local **instruct model via Ollama** (OpenAI-compatible endpoint → trivial LangChain/LangGraph integration). Good default: a **7–8B instruct** model (e.g., Llama 3.1 8B Instruct or Qwen2.5 7B Instruct, or a newer equivalent). For constrained hardware, drop to a **3B instruct** model for the routing/extraction calls and keep the larger model only for final generation.
- **Embeddings:** `BAAI/bge-small-en-v1.5` (strong quality, CPU-friendly) with `all-MiniLM-L6-v2` as the lighter fallback. Both run locally via `sentence-transformers`.

### 6.2 Trade-offs to write up
- 7–8B instruct models handle structured routing + grounded answering well and run on a consumer GPU (or CPU, slowly); below ~3B, routing/extraction reliability drops.
- Quantized GGUF (Q4/Q5) cuts memory and latency at a small quality cost — worth it for the prototype and relevant to your bottleneck analysis.

### 6.3 Dummy LLM mode (build this — it's not just a fallback)
Provide a `DummyLLM` (config flag `LLM_BACKEND=dummy`) returning canned/structured responses. Two reasons: (1) the brief explicitly permits dummy LLMs if local resources don't allow a real one, and (2) it lets you run the **load test against orchestration + retrieval only**, isolating LLM latency from graph overhead — directly useful for the bottleneck analysis in §8.

---

## 7. User Interface (Streamlit) — `app/streamlit_app.py`

**Tabs as the spine.** The UI grows one tab per build phase, so each layer stays independently demonstrable. The first four are **inspector tabs** (dev/demo surfaces); the **Agent** tab is the product that satisfies the brief's UI requirement (**the agent's main steps** + **the RAG result**).

1. **Chat (LLM)** — raw chat with the active backend (ollama/dummy). Sanity-checks the model layer.
2. **Corpus** — browse the processed corpus: chunks per document, the Article/Recital structure boundaries, per-chunk metadata, and counts. Makes "quality processing" + structure-aware chunking visible.
3. **RAG** — enter a query and watch the corrective loop: retrieved chunks (scores + metadata) → **grade** decision → **rewritten query** (if any) → **generated** answer with citations. This surfaces the most "agentic" part of the system.
4. **Calculator** — flight inputs → `{distance, band, amount}`; exercises the deterministic non-retrieval tool.
5. **Agent** *(the product)* — the full graph via `graph.stream`: render `state["trace"]` (which `query_type` the router chose, whether decomposition happened, retrieved chunks with source/article, the eligibility decision + rationale, the calculator's `{distance, band, amount}`), plus the final grounded answer, **citations** (source + article + snapshot date), and the **"general information, not legal advice"** disclaimer.

Conventions:
- A persistent **sidebar** (not a tab) shows active backend / model / top-k across all tabs.
- Build display pieces **once** — chunk card, citation list, trace-step renderer — and reuse them in the RAG and Agent tabs so they can't drift apart.
- Inspector tabs must handle the **not-built-yet / empty** state gracefully (e.g. corpus not ingested) so a fresh clone doesn't error.

Implementation tip: stream the LangGraph run (`graph.stream`) and append each node's output to the Agent tab's trace so the user literally watches the agent work — this is what scores the "demonstrates the agent's operation" point.

---

## 8. Evaluation & Performance Analysis

### 8.1 Functional evaluation (`eval/functional_eval.py`)
- Run the **starter eval set** (§9) through the full graph.
- For **calculator** questions: exact-match the `final_amount_eur` against ground truth (deterministic → clean pass/fail).
- For **rights/RAG** questions: check (a) correctness of the key fact and (b) that the answer is grounded in the expected source/article (citation contains the right article). A lightweight LLM-as-judge or keyword/citation assertion is fine at this scale.
- For **out-of-scope** questions: assert the fallback path fired (no fabricated answer).
- Report per-path accuracy and a short error analysis.

### 8.2 Performance / load test (`eval/load_test.py`)
- Replay **50–200 queries** (sample/repeat the eval set) through the graph; support concurrency.
- Report **latency p50 / p95 / p99**, mean, and throughput (queries/min). Optionally break latency down **per node** (retrieval vs. LLM generation vs. calculator) using the trace timestamps.
- **Run it twice:** once with the real LLM, once with `LLM_BACKEND=dummy`, to separate LLM time from orchestration time.
- **Expected bottleneck:** local LLM generation latency (and the corrective-RAG rewrite loop when it triggers). The deterministic calculator and vector search will be negligible by comparison.
- **Optimization suggestions to write up (pick 1–2 concrete ones):**
  1. Use a smaller/quantized model for the high-frequency routing+extraction calls; reserve the larger model for final synthesis.
  2. Add a **semantic cache** for repeated/similar queries; cache embeddings and retrieval results.
  3. Cap the corrective-RAG rewrite loop (e.g., max 1 retry) and run independent subtasks **concurrently** for `mixed` queries.

---

## 9. Starter Evaluation Set (15 questions)

Each item lists the **path it exercises** and the **expected answer / ground truth**. Distances are approximate — verify against your OpenFlights computation and adjust expected amounts if a route lands in a different band.

| # | Question | Path / node tested | Expected answer (ground truth) |
|---|----------|--------------------|--------------------------------|
| 1 | How long must a delay be before I may be entitled to compensation? | RAG (rights_info) | At least **3 hours** at the final destination. |
| 2 | What care must an airline provide during a long delay? | RAG | Meals/refreshments, communication, and accommodation if an overnight stay is needed (Art. 9). |
| 3 | If my flight is cancelled because of bad weather, am I owed compensation? | RAG / eligibility | **No** — weather is an "extraordinary circumstance"; care/rerouting may still apply. |
| 4 | Does the regulation cover a New York → Paris flight on a US airline? | RAG | **Yes** — arriving in the EU; though non-EU→EU on a non-EU carrier is **not** covered. (Test the inverse too.) |
| 5 | Does it cover a Paris → New York flight on any airline? | RAG | **Yes** — departing from an EU airport. |
| 6 | Is a strike by the airline's own staff an extraordinary circumstance? | RAG / eligibility | **No** (own-staff strike is generally within the carrier's control) → compensation may be due. |
| 7 | My flight from Budapest to London was delayed 4 hours. How much am I owed? | Calculator (compensation_calc) | ~1450 km → ≤1500 km band → **€250**. |
| 8 | Madrid to New York, cancelled, I arrived 7 hours late on a rebooking. Compensation? | Calculator | ~5760 km → >3500 km band → **€600**. |
| 9 | Paris to Rome delayed 3.5 hours. How much? | Calculator | ~1100 km → ≤1500 km → **€250**. |
| 10 | Frankfurt to Cairo (≈2900 km) delayed 5 hours. How much? | Calculator | 1500–3500 km band → **€400**. |
| 11 | My Paris–Rome flight was cancelled due to an airline staff strike and I got in 6 hours late — am I entitled to anything, and how much? | **Mixed** (planner → RAG eligibility + calculator) | Eligible (staff strike not extraordinary); ~1100 km → **€250**. |
| 12 | My flight was delayed only 1 hour. Do I get cash compensation? | Calculator / eligibility | **No** cash compensation (below 3h threshold); may still get assistance. |
| 13 | The airline offered re-routing and I arrived 2 hours late on a short-haul flight. What compensation? | Calculator (reduction rule) | Likely **50% reduction** applies → **€125** for ≤1500 km. |
| 14 | Can I bring my dog in the cabin? | **Out-of-scope** (fallback) | Politely declines — not covered by Reg. 261/2004. |
| 15 | What's Ryanair's checked-baggage fee? | **Out-of-scope** (fallback) | Politely declines — outside scope (airline pricing, not the regulation). |

> Add 1–2 "edge" items if time allows: a route exactly near a band boundary, and a denied-boarding (overbooking) scenario.

---

## 10. Things Easy to Overlook (include these — they score points)

1. **Hallucination firewall.** The `generate` node must answer only from retrieved chunks and the fallback node must fire for out-of-scope queries. Grade this in the eval (items 14–15).
2. **Citations, always.** Every rights answer cites source + article. This is the cheapest way to demonstrate "quality processing" and trustworthiness.
3. **"Not legal advice" disclaimer** in every answer that interprets the rules.
4. **Reproducibility hygiene** (a named grading criterion): pin Python (3.12, via `.python-version`) and isolate with a stdlib `venv`, pin dependency versions in `requirements.txt`, set `temperature=0` and a fixed seed where supported, commit the frozen corpus snapshot + `SOURCES.md`, make ingestion idempotent, and document the plain run commands (create venv, install, ingest, then `streamlit run`). The Dockerfile pins the same `python:3.12-slim` base so local and container match.
5. **Observability for the UI requirement.** The `trace` in state isn't optional polish — it's what makes the "show the agent's steps" requirement real.
6. **Config over hardcoding.** `LLM_BACKEND`, model names, top-k, Ollama URL via env/`config.yaml`. Enables the dummy-mode load test and clean Docker wiring.
7. **Unit tests for the calculator.** Deterministic and trivial to test — easy, high-credibility coverage (distance bands, threshold, reduction rule).
8. **Licensing note.** OpenFlights data is ODbL — attribute it in `SOURCES.md`. EUR-Lex content is reusable with source acknowledgment.
9. **Snapshot/reform caveat** in the README (see §1.5).

---

## 11. Suggested Repository Structure

```
eu261-agentic-rag/
├── README.md                      # problem, architecture + design justification, eval/perf summary, install/run
├── CLAUDE.md                      # Claude Code working agreement (conventions, commands, non-negotiables)
├── PLAN.md                        # living phased implementation plan + status
├── DECISIONS.md                   # running log of implementation decisions (trade-offs, revisit-later choices)
├── notes/
│   ├── PROJECT_PROPOSAL.md        # this file — full design rationale
│   └── TASK_DESCRIPTION.md        # original task brief
├── Dockerfile                     # base python:3.12-slim (matches local env)
├── docker-compose.yml             # bonus: app + ollama services
├── requirements.txt               # pinned deps (installed into a stdlib venv)
├── .python-version                # pins Python 3.12
├── config.yaml
├── data/
│   ├── corpus/                    # frozen text snapshot (3 docs)
│   ├── rules/compensation_rules.yaml
│   ├── airports.dat               # OpenFlights
│   ├── chroma/                    # persisted vector store (gitignored or committed small)
│   └── SOURCES.md                 # urls, dates, licenses
├── src/
│   ├── state.py
│   ├── graph.py                   # main LangGraph workflow (7 nodes)
│   ├── nodes/                     # intake, router, planner, eligibility, calculator, synthesize, fallback
│   ├── rag/
│   │   ├── graph.py               # RAG subgraph (corrective RAG)
│   │   └── nodes.py               # retrieve, grade, rewrite, generate
│   ├── tools/
│   │   ├── retrieval.py           # retrieve_passenger_rights
│   │   └── compensation.py        # calculate_compensation (+ haversine, airport lookup)
│   ├── ingest/                    # parse + chunk + embed + persist
│   └── llm.py                     # backend switch: ollama | dummy
├── app/streamlit_app.py
├── eval/
│   ├── eval_set.yaml              # the 15 questions + ground truth
│   ├── functional_eval.py
│   └── load_test.py
└── tests/
    └── test_compensation.py
```

---

## 12. Build Roadmap

The live, phased build plan and its status are maintained in **`PLAN.md`** (the proposal stays focused on design rationale; the plan is the living doc). Current approach is Streamlit-as-spine: LLM backend + minimal chat UI → corpus + RAG subgraph → calculator → agentic assembly → functional eval + load test → Docker + README, with the UI gaining a visualization each phase.

---

## 13. Acceptance Checklist (mapped to the grading criteria)

- [ ] **Problem relevance & justification** documented (§1 in README).
- [ ] **≥ 5 nodes** in the main graph (have 7) with **conditional routing** (router + eligibility).
- [ ] **Decomposition + independent execution** — planner emits subtasks (LLM, not hardcoded); `mixed` runs as a fan-out → fan-in of parallel branches.
- [ ] **State management** via typed `AgentState`.
- [ ] **≥ 2 tools**, with **≥ 1 non-retrieval** (calculator); both as explicit `@tool`s.
- [ ] **Modular RAG subgraph** — compiled `StateGraph` added via `add_node`, **not** counted among the 5.
- [ ] **Quality + scalable corpus processing** (structure-aware chunking + metadata + citations; generic drop-in ingestion loader).
- [ ] **No paid API**; local LLM justified, **dummy mode** available.
- [ ] **Streamlit UI** shows agent steps + RAG result + citations + disclaimer.
- [ ] **Dockerfile** present; **docker-compose.yml** bonus.
- [ ] **Functional eval** (15 Qs) with methodology + results.
- [ ] **Load test** (50–200 queries): latency metrics + bottleneck + 1–2 optimizations.
- [ ] **Reproducibility**: pinned versions, frozen corpus, seeds, idempotent ingest, install/run guide.
- [ ] **README** covers problem, architecture + design justification, eval/perf summary, install/run.

---

*Snapshot note: rules and figures reflect Regulation (EC) No 261/2004 as in force at build time; an EU reform was in negotiation as of late 2025 and is not yet enacted. Verify the figures against your committed corpus snapshot.*
