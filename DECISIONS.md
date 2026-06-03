# DECISIONS.md

Running log of implementation decisions and insights — trade-offs made, arbitrary choices that need revisiting, and anything non-obvious worth remembering. Append new entries at the top. Keep each entry short and dated.

Tag entries so they're easy to scan:
- **[trade-off]** — a deliberate compromise (what we gave up and why)
- **[revisit]** — an arbitrary/placeholder choice that must be revised later
- **[gotcha]** — surprising behavior or a non-obvious constraint
- **[decision]** — a settled choice worth recording so it isn't re-litigated

Format:

```
## YYYY-MM-DD — short title
**[tag]** What was decided/observed.
**Why:** the reasoning or constraint that forced it.
**Revisit if:** (for [revisit]) the condition that should trigger a second look.
```

---

<!-- Add entries below, newest first. -->

## 2026-06-04 — Agent-tab graph diagram renders via the mermaid.ink network API  (`graph-diagram-render`)
**[trade-off]** The Agent tab's "Graph structure" diagram is generated from the **live compiled graph** (`agent_graph.get_graph().draw_mermaid()` → flipped to `graph LR`) and rendered to a **PNG server-side via LangGraph's `draw_mermaid_png()` helper, which posts the Mermaid source to the external `mermaid.ink` API**. Shown with `st.image`, cached on the source string; the raw Mermaid source is always offered in an expander as an offline fallback.
**Why:** Live-from-graph means the picture can't drift from the wiring, and it adds **zero new Python deps**. A client-side render (mermaid.js in `st.components.v1.html`) was tried first but **Streamlit's component iframe silently blocks the inline JS** (neither the diagram nor any error surfaced) — the server-side PNG path sidesteps iframe/JS/CSP entirely and renders reliably. `LR` over the default `TD` keeps the tall graph short and the node text legible.
**[gotcha]** `@st.cache_data` will also cache a `None` result, so a transient `mermaid.ink` blip can stick for the session until the cache clears. Cheap to guard (skip caching on `None`) if it ever bites — left as-is for now.
**Revisit if (Phase 7 dockerization):** 🔖 `GRAPH-DIAGRAM-OFFLINE` — this needs **internet at render time**, which conflicts with non-neg #7 (run locally / reproducible) and the containerized demo: **in Docker without internet the diagram silently degrades to the Mermaid-source text.** When dockerizing, decide whether that text fallback is acceptable for the demo, or switch to a fully-local backend. LangGraph natively offers **three** image backends (per the [docs](https://docs.langchain.com/oss/python/langgraph/use-graph-api#visualize-your-graph) — verified against the installed source):
- **mermaid.ink API** — `draw_mermaid_png()` default (`draw_method=API` → `requests.get("https://mermaid.ink", …)`). *Current.* No new dep, but **network**.
- **Pyppeteer** — `draw_mermaid_png(draw_method=MermaidDrawMethod.PYPPETEER)`. **Local**, keeps the Mermaid look, but pulls `pyppeteer` (downloads a headless Chromium, ~150 MB) — heavy for a container.
- **Graphviz** — `draw_png()` (graph_png.py, needs the `graphviz` system binary + the `pygraphviz` Python pkg). **Local**, lightest of the two offline options (an `apt-get install graphviz` line + `pygraphviz` in requirements); produces a graphviz-styled diagram rather than the Mermaid look.

Leaning **Graphviz** for the Docker path if we want it to render offline; otherwise accept the text fallback. (Vendoring `mermaid.js` for a client render is a fourth, non-library route but the iframe-block issue above must be solved first.) Grep `GRAPH-DIAGRAM-OFFLINE` to jump back here.
Related: [[agent-assembly]], [[gitignore-data-for-now]].

## 2026-06-03 — Inserted a review/improve phase before eval; renumbered eval & Docker  (`phase-5-review-insert`)
**[decision]** Added **Phase 5 — Review, spot-check & improve** between agentic assembly (Phase 4) and the eval phase. With the core solution assembled, the intent is a deliberate, **human-driven** review/spot-check pass — the user exercises each route and **initiates** the improvements they want (Claude assists/executes rather than autonomously driving a feature list) — *before* the heavy functional eval and the Docker/README lock-in. Consequently the two not-yet-started phases were renumbered: **eval + load test 5 → 6**, **Docker + README 6 → 7**.
**Why:** the solution runs end-to-end but hasn't had a focused "is it right and clean?" review; doing that before the eval set and the container are fixed is cheaper than reworking afterwards. Renumbering (vs. a fractional "4.5") keeps phases a clean integer sequence; safe to do because neither phase 5 nor 6 had started — no `phase/5-*`/`phase/6-*` branches or `phase-5-*`/`phase-6-*` tags exist yet. Canonical branch names updated in CLAUDE.md (`phase/5-review-improve`, `phase/6-eval-loadtest`, `phase/7-docker-readme`).
**[gotcha]** Earlier DECISIONS entries (all dated 2026-06-03, *above-by-date but below this one*) say "Phase 5 eval" / "Phase 5 load test" — written before this insert, those now refer to **Phase 6**. They're left as-written (this log is append-only); read "Phase 5 eval/load test" in any entry predating this one as Phase 6. The forward-looking references in PLAN.md were updated in place.
Related: [[rag-grader]], [[eligibility-control-frame]], [[calculator-rules-constants]].

## 2026-06-03 — Phase 4: RAG subgraph attached as a schema-mapping wrapper node  (`agent-assembly`)
**[decision]** The main graph (`src/graph.py`) attaches the compiled corrective-RAG subgraph as a **single shared `rag` node** that calls `rag_graph.invoke(...)` and maps `RAGState ↔ AgentState` at the boundary (`question ← user_query`; `retrieved_docs/rag_answer/rag_citations ← documents/answer/citations`; inner `steps` nested under the trace). It is reused by **both** the `rights_info` path and the eligibility branch; a conditional edge *after* `rag` sends `rights_info → synthesize` and everything else `→ eligibility`.
**Why:** RAGState and AgentState have disjoint keys, so a bare `add_node(rag_graph)` (which needs a shared schema) would mis-pass state. The wrapper is LangGraph's documented different-schema-subgraph pattern and still satisfies guardrail #3 — the **compiled subgraph is invoked as a node**, not reimplemented as a plain function. Sharing one `rag` node (vs. two copies) keeps the subgraph singular and the corrective loop identical in both paths.
**[gotcha] Deferred `synthesize` for uneven-length fan-in.** `synthesize` is added with `defer=True`. The two fan-out branches are different lengths — the calculator branch is one hop (`router/planner → calculator → synthesize`), the eligibility branch is two (`… → rag → eligibility → synthesize`). Without `defer`, LangGraph (Pregel) fires `synthesize` as soon as the calculator branch reaches it (superstep N), then **again** when eligibility arrives (superstep N+1) — running it twice. `defer=True` holds it until no other tasks are pending, so the fan-in happens once. Verified: the `mixed` trace is `[intake, router, planner, calculator, rag, eligibility, synthesize]` with a single `synthesize`.
**[decision] Sync nodes (topological fan-out, not async concurrency).** The graph *structure* demonstrates independent parallel branches (what's graded); nodes are sync, so within a superstep they run sequentially. True wall-clock concurrency of rag-vs-calculator buys ~nothing here (the calculator is instant; the cost is the sequential LLM calls inside `rag → eligibility`), so async is deferred to the Phase 5 load test if the per-node timing shows it would help.
Related: [[synthesize-deterministic]], [[eligibility-control-frame]], [[rag-grader]].

## 2026-06-03 — synthesize is deterministic (no LLM), reversing the planned LLM-merge  (`synthesize-deterministic`)
**[decision]** The `synthesize` node assembles the final answer **deterministically** from already-grounded parts — the RAG answer (itself grounded + cited) plus the deterministic `calc_result` and the `eligibility` verdict — and applies the gate `final = eligible ? candidate : 0` (plus the sub-3h-threshold → €0 case). No LLM call.
**Why:** I floated an LLM-merge in the plan, but a second generative pass is a fresh hallucination surface on a 3B model — exactly what non-neg #3 (ground everything; never fabricate) and the [[rag-grader]] grounding-fragility notes warn against, and it risks mangling the euro figures/citations that are the factual payload. Deterministic assembly is grounded **by construction**, faster (one fewer LLM call per answer), and keeps the numbers/citations intact. The trade is slightly stitched prose on `mixed` (rights paragraph + compensation paragraph), acceptable for the prototype.
**Revisit if:** answer cohesion on `mixed` matters more than the hallucination risk and a larger model is in use → add a strict no-new-facts LLM merge pass behind the deterministic assembly (keep the gate/figures deterministic regardless).
Related: [[agent-assembly]], [[rag-grader]].

## 2026-06-03 — Eligibility: "within the carrier's control" frame + deterministic no-cause default  (`eligibility-control-frame`)
**[revisit]** The `eligibility` node makes the extraordinary-circumstances call two ways: **(a)** if no cause is stated, it returns `eligible=true` **deterministically** (no LLM) — extraordinary circumstances are an Art. 5(3) exception the *carrier* must prove, so the default is "owed"; **(b)** if a cause is stated, an LLM judges it, prompted around **"was the cause WITHIN the airline's own control?"** (own staff/crew strike, technical/operational issues → eligible) **vs. extraordinary/beyond control** (weather, ATC, security, third-party strikes → not eligible), with worked examples.
**Why:** The 3B model, asked directly "is this an extraordinary circumstance?", treated **every** strike as extraordinary — getting the textbook own-staff-strike carve-out (CLAUDE.md gotcha; proposal Q11) exactly backwards (€0 instead of €250). Reframing to the control test + few-shot fixed it: verified own-staff strike → eligible/€250, snowstorm → not eligible/€0, no-cause 4h delay → eligible/€250. The deterministic no-cause branch also stops the model inventing an extraordinary cause from nothing and saves an LLM call.
**Revisit (Phase 5 eval):** measure eligibility accuracy across the 15-Q set; if borderline causes (e.g. bird strike, ground-handler strike) misclassify, expand the few-shot or bump the model size per [[llm-model]].
Related: [[agent-assembly]], [[rag-grader]], [[llm-model]].

## 2026-06-03 — Metro-code alias fallback in the calculator  (`metro-aliases`)
**[decision]** `src/calculator.py` gains a small `METRO_ALIASES` map (LON→LHR, PAR→CDG, ROM→FCO, MIL→MXP, NYC→JFK, …) applied as a **fallback only when the direct IATA lookup misses**, so it never changes a real airport code's resolution.
**Why:** The intake LLM reliably emits IATA **metropolitan** codes for major cities ("London"→`LON`, "Paris"→`PAR`), which are valid IATA codes but absent from OpenFlights `airports.dat` (airport codes only) — so the calculator raised `AirportNotFound` and the amount came back as an error. The alias resolves the city's principal airport; close enough for the great-circle distance band, which is what the amount keys off. Tests still 17/17 (all use real airport codes, so the fallback path isn't exercised by them).
**[gotcha]** The eval/agent path can therefore feed `LON`/`PAR`; the calculator's own test set uses airport codes (`BUD`, `LHR`) and asserts exact distances, so band-boundary cases stay pinned. If a city's "principal airport" choice ever matters for a band boundary, pin it in the eval set.
**Revisit if:** the corpus/eval grows routes whose metro→airport choice flips a distance band → either pick the band-correct airport or require airport codes at intake.
Related: [[calculator-rules-constants]], [[agent-assembly]].

## 2026-06-03 — Calculator: statutory rules as constants; flag-driven reduction; pure-module split  (`calculator-rules-constants`)
**[decision]** The Phase 3 calculator splits into a **pure `src/calculator.py`** (haversine, OpenFlights lookup, `compute_compensation`) and a **thin `@tool` wrapper** in `src/tools.py`. Tests target the pure module directly. The Art. 7 figures live as **module constants** (`BANDS` = €250/€400/€600 at 1500/3500 km; `DELAY_THRESHOLD_HOURS = 3`), **not** a `compensation_rules.yaml` (as the proposal sketched) and **not** env-overridable.
**Why:**
- **Constants over YAML/env:** these are *in-force law*, not tunables — non-neg #2 says anchor to the current figures, and a wrong euro figure is the worst failure mode (it's eval ground truth). Making them trivially overridable invites exactly the silent band/threshold drift the recompute-distances gotcha warns about. Consistent with [[simplify-p1]] (plain constants over a config framework). Swapping a model tag is safe; swapping the law is not — so the law isn't a knob.
- **Pure-module split:** keeps the `@tool` thin and the deterministic logic directly unit-testable without tool-invocation ceremony; the calculator genuinely earns its own module (airport CSV load, haversine, band table, test set), which the "flat until it earns splitting" convention allows.
**[revisit] 🔖 `RULES-LOCATION-REVISIT` (user-flagged, 2026-06-03)** — The user wants to revisit **where the Art. 7 rules live**: currently **inline constants in `src/calculator.py`** (`BANDS`, `DELAY_THRESHOLD_HOURS`) vs. extracting them to a **separate file** — a `src/rules.py` module or a committed data file (`compensation_rules.yaml` / `.json`, as the proposal originally sketched). **Grep `RULES-LOCATION-REVISIT` to jump back here.**
**Trade to weigh when revisiting:** *inline (current)* — single source of truth, law isn't trivially overridable, zero indirection; *external file* — data/code separation, rules editable without touching code, easier to diff/review the rules table on its own, but reintroduces a load path and the "anyone can silently change the law" risk non-neg #2 warns about. No trigger forces this — it's a deliberate revisit the user reserved, not a placeholder that's wrong as-is.
**[decision]** **Eligibility-agnostic, confirmed in code:** `threshold_met`/`reduction_applied` are purely mechanical (distance / delay / rerouting). The extraordinary-circumstances gate (weather/strike → €0) is **not** here; it's applied at `synthesize` (Phase 4) as `final = eligible ? candidate : 0`. The calculator returns the *statutory candidate* amount. Delay-type uses the 3 h Sturgeon threshold; cancellation / denied boarding are candidates regardless of delay.
**[revisit]** **50%-reduction is flag-driven:** `reduction_applied = rerouting_offered AND delay_hours <= band_limit` (2/3/4 h by band, Art. 7(2)). The **long-haul (>3500 km) 3–4 h auto-50%** nuance (Sturgeon/Nelson, by analogy to Art. 7(2)(c) even without an explicit re-routing offer) is **noted but not encoded** — kept flag-driven to match the tool signature and stay simple for the prototype (user's call, 2026-06-03).
**Revisit if:** the eval set adds a long-haul 3–4 h delay case whose expected amount is €300 not €600 → then encode the auto-50% for that band; or if the reform is enacted (re-freeze figures, non-neg #2).
**[gotcha]** **BUD→LHR is 1489.5 km — just *under* the 1500 km boundary** (the proposal guessed ~1450; either way ≤1500 → €250, but it's boundary-close). Recomputed all eval routes from real OpenFlights coords before fixing test expectations; LHR→LIS (1563.9 km) is the just-*over* boundary case. Distances are asserted in the tests so an airports.dat change that flips a band fails loudly.
**[decision]** OpenFlights `airports.dat` (ODbL) fetched to `data/` (gitignored for now, like the corpus — [[gitignore-data-for-now]], settle in Phase 6) and attributed in `data/SOURCES.md`. Only new dependency is `pytest`; the calculator itself is stdlib-only (`math`, `csv`).
Related: [[simplify-p1]], [[gitignore-data-for-now]].

## 2026-06-03 — Evaluated `kevin91nl/eurlex` for corpus acquisition — not adopted  (`eurlex-spike`)
**[decision]** Spiked the `eurlex` library (MIT, v0.1.12) as a possible systematic EU-legislation downloader/parser (CELEX → HTML → structured DataFrame via SPARQL/Cellar). **Not adopted** for our corpus; spike deps uninstalled (not in `requirements.txt`).
**Why (empirical, tested on every relevant doc):**
- **Reg 261/2004 (`32004R0261`)** → only **2 unstructured rows** (one a 27k-char blob), no Article/Recital columns. Its parser targets the **modern** EUR-Lex HTML; the 2004 act is served as old flat HTML it can't structure. Our chunker yields 44 clean Article/Recital chunks — strictly better here.
- **2024 guidelines (`52024XC05687`)** → 462 rows but **0 labelled sections** (it's a notice, not a regulation; section numbers land only in an unstructured `group` field). Our notice chunker yields 87 citable `Section N.N.N` chunks.
- **Legissum (`LEGISSUM:l24173`)** and **Your Europe** → **not fetchable** (not a CELEX / not EUR-Lex).
- Sanity check: on the README's modern example (`32019R0947`) it works well — **520 rows, 23 articles**. So it's genuinely good for *modern* regulations/directives, just not our mix.
**Takeaway for scaling:** `eurlex` is a legitimate option **if** the corpus grows to many modern CELEX acts; cite it in the Phase 6 data-collection writeup as the scaling path. It also validates our design (Cellar-not-WAF; structure-by-article). For the current 4-doc corpus, our hand-rolled loader is better-fitted.
Related: [[corpus-2024-guidelines]], [[gitignore-data-for-now]].

## 2026-06-03 — Gitignore the whole `data/` tree (temporary)  (`gitignore-data-for-now`)
**[revisit]** `/data/` is gitignored in full — the frozen corpus, `data/SOURCES.md`, `data/corpus/sources.json`, and the derived `data/chroma/` all stay local, out of git. This **departs from** the CLAUDE.md repo-hygiene rule and reproducibility non-negotiable, which say to commit the frozen corpus snapshot (chroma only is derived/ignored).
**Why:** User's call (2026-06-03) to keep the repo data-free for now, with an explicit checkpoint to settle it **before sharing the repo**. I recommended against it (the corpus is small/static/text/public/licensed and reproducibility-critical, and the acquisition is WAF-fragile — exactly why a committed snapshot helps); recorded here as a deliberate, reversible deferral rather than a silent rule-break.
**Consequence:** no git backup of the curated corpus — it exists only in this working tree until the decision is revisited; a fresh clone can't run `python -m src.ingest` (no corpus) and citation provenance (`sources.json`) isn't in the repo.
**Revisit (Phase 6, before sharing):** choose either (a) commit the frozen snapshot (un-ignore `data/corpus/` + `SOURCES.md`, keep `data/chroma/` ignored), or (b) a committed **`scripts/fetch_corpus.py`** that re-derives the corpus from documented URLs — regulation + 2024 guidelines via the Publications Office Cellar API, legissum via `requests` + the EUR-Lex TXT/HTML export endpoint — so a fresh clone reproduces it. Provenance + fetch methods are preserved in [[corpus-2024-guidelines]] and (locally) `data/SOURCES.md`.
Related: [[corpus-2024-guidelines]].

## 2026-06-03 — Embeddings reuse local Ollama (`nomic-embed-text`), not sentence-transformers  (`embeddings-ollama`)
**[decision]** RAG embeddings run through the **local Ollama** model `nomic-embed-text` via `OllamaEmbeddings` (already a dependency through `langchain-ollama`), replacing the docs' `BAAI/bge-small-en-v1.5` + `sentence-transformers`. The shared seam lives in `src/store.py` (embedder + Chroma collection); `config.EMBEDDING_MODEL` default changed accordingly.
**Why:** `sentence-transformers` hard-depends on **torch** — hundreds of MB and the single biggest cp314-wheel risk. The user already had `nomic-embed-text` pulled, so reusing Ollama adds **zero new heavy deps** (no torch / no onnx), reuses infra the project already requires, and erased most of the Phase 2 install risk. nomic is a solid 768-dim model.
**[gotcha]** `nomic-embed-text` is trained with **task prefixes**: documents must be embedded as `search_document: …` and queries as `search_query: …`. Using the same prefix for both (or none) measurably degrades retrieval. `src/store.py` applies the asymmetric prefixes in one place (`embed_documents` vs `embed_query`); Chroma is always handed vectors explicitly so its default onnx EF never activates.
**How to apply:** never call Ollama embeddings directly from nodes — go through `src.store.embed_documents` / `embed_query` so the prefix asymmetry stays correct by construction. Two consumers (ingest write-side, tool read-side) is why `store.py` is its own module.
**Revisit if:** retrieval quality proves weak → try a stronger embedder (bge-m3 via Ollama, or fastembed's bge-small ONNX, still torch-free), or split the embedding model from the chat model knob if they need different tags.
Related: [[python-314-resolved]], [[corpus-2024-guidelines]], [[rag-grader]].

## 2026-06-03 — Python 3.14 wheel risk retired for Phase 2 deps  (`python-314-resolved`)
**[decision]** The open risk in [[python-314]] is closed: a `--only-binary=:all:` install of `langgraph==1.2.4` + `chromadb==1.5.9` resolved cleanly on cp314 — including the transitive native deps `onnxruntime`, `tokenizers`, `grpcio`, `uvloop`, `watchfiles` — with **no source builds**. Full stack (streamlit + chromadb + langgraph + langchain-ollama) imports together and the embedding round-trip works.
**Why:** Avoiding torch (via [[embeddings-ollama]]) removed the one dependency most likely to lack a cp314 wheel; everything remaining shipped wheels. 3.14 stays the pin; no fallback to 3.13/3.12 needed.
**[gotcha]** Installing chromadb downgraded `protobuf` 7.35.0 → 6.33.6 (its OTel cap) and `websockets` 16.0 → 15.0.1; Streamlit still imports and boots fine (HTTP 200). Top-level pins in `requirements.txt`; if a transitive break surfaces later, pin the transitive explicitly.
**Revisit if:** Phase 3 (calculator: only stdlib + math expected) or later deps reintroduce a package without cp314 wheels.
Related: [[python-314]], [[embeddings-ollama]].

## 2026-06-03 — Corpus: 2024 interpretative guidelines; fetched via Cellar API  (`corpus-2024-guidelines`)
**[decision]** Frozen corpus = three docs in `data/corpus/`: **(1)** Reg (EC) 261/2004 full text (CELEX `32004R0261`), **(2)** the **2024** Commission Interpretative Guidelines (Commission Notice, OJ `C/2024/5687`, 25.9.2024) — **replacing the 2016 version** named in the proposal — and **(3)** the official Your Europe plain-language summary (extracted to Markdown). Provenance for citations is in `data/corpus/sources.json`; human/licensing record in `data/SOURCES.md`.
**Why:** The 2024 guidelines are a genuine update (cite CJEU case law through 2023–2024, ~2.3× the 2016 text), so they're the more current authoritative interpretation — strictly better for grounding. The user surfaced the OJ link.
**[gotcha]** `eur-lex.europa.eu` is behind an **AWS WAF JavaScript challenge** — but it keys on the client: `curl` gets HTTP 202 with an empty/anti-bot body, while Python **`requests`** (default User-Agent) passes and returns the real HTML. Two faithful routes, both used here:
- **Publications Office Cellar REST API** (`http://publications.europa.eu/resource/celex/<CELEX>` or `/resource/oj/<OJ-id>`, `Accept:` content negotiation: `text/html` for the regulation, `application/xhtml+xml` for the OJ notice) — no WAF at all. Used for docs 1–2.
- **EUR-Lex TXT/HTML export** (`/legal-content/EN/TXT/HTML/?uri=<CELEX|LEGISSUM>:<id>`) via `requests` — used for the legissum. Note Cellar does **not** serve a content datastream for `LEGISSUM:l24173` (only a metadata notice), so the export endpoint is the route for legislative summaries.
**[decision]** Corpus carries **both** plain-language summaries: the **EUR-Lex legislative summary** (`LEGISSUM:l24173`, semantic `<h1>`–`<h3>` structure) and the **Your Europe** summary (richer, with compensation tables). They overlap but improve colloquial→formal recall; the loader handles N docs. *(Initially I wrongly concluded the legissum was unfetchable — curl/Cellar failed and WebFetch only paraphrases — and substituted Your Europe; the user supplied the `requests` + TXT/HTML-export route, which works. Lesson: try `requests` against the EUR-Lex export endpoint before giving up on a EUR-Lex URL.)*
**[decision]** Added a **`html_headings` chunker** (semantic `<h1>`–`<h4>` → section chunks) and tightened `detect_doc_type` so "notice" requires the `ti-grseq-1` class (the legissum mentions "interpretative guidelines" in its related-docs and was misrouted). This makes the generic loader handle the common semantic-HTML case, not just the two EUR-Lex markups.
**Revisit if:** the 2025 reform is enacted (then re-freeze against the new in-force text — but only when enacted; non-negotiable #2).
Related: [[embeddings-ollama]].

## 2026-06-03 — RAG grader: LLM verdict + distance floor; generate grounding firewall  (`rag-grader`)
**[revisit]** The corrective-RAG `grade_documents` node decides relevance with the LLM **plus** a cosine-distance safety floor: `relevant = llm_says_yes OR best_distance <= GRADE_DISTANCE_FLOOR` (default **0.25**, a `config` knob).
**Why:** The `qwen2.5:3b` grader is biased toward "no" — it rejected obviously-relevant retrieval (top hit at 0.144) on the bare "relevant *and sufficient*?" prompt, firing a needless rewrite every query. Fixes: (a) reframe to "is at least ONE passage relevant?" on truncated (600-char) snippets, and (b) the distance floor so a strong vector hit isn't discarded on a bad grade. The floor is a placeholder — too high (0.35) let mediocre retrieval skip a useful rewrite; 0.25 is a first guess.
**[gotcha]** `generate` grounding is fragile on a 3B model: too-strict "reply EXACTLY …" wording caused over-refusal of legitimate in-scope questions; too-loose let world knowledge leak (answered "Paris" for "capital of France"). Current prompt: answer only from passages, cite `[n]`, **no outside knowledge / no invented figures**, say so if uncovered, complete sentences (it sometimes emitted a bare `[1]`). Out-of-scope is ultimately the **router's** job in Phase 4 (RAG won't see "capital of France"); exact compensation amounts are the **calculator's** job (Phase 3), not RAG — so RAG's fuzzy math is acceptable.
**Revisit (in Phase 5 eval):** tune `GRADE_DISTANCE_FLOOR` and `TOP_K` against the 15-Q set; if grounded-answer quality is still weak, bump to a 7–8B instruct model (per [[llm-model]]) or split a larger model for generation only.
Related: [[llm-model]], [[embeddings-ollama]], [[drop-dummy-llm]].

## 2026-06-03 — Simplify Phase 1: drop config framework, flatten layout  (`simplify-p1`)
**[decision]** After reviewing the first Phase 1 build, traded structure for readability/iteration speed (it's an interview prototype — "quality, not quantity"):
- **Config:** replaced `config.yaml` + a `Config` dataclass (YAML load, env-mapping, `lru_cache`, key validation, ~100 lines) with a single root **`config.py`** of plain constants + `os.getenv` defaults (~20 lines). Still centralized + env-overridable → honors the "config over hardcoding" convention; drops type validation and external YAML editing.
- **LLM seam:** kept `get_llm()` (it *is* the required seam — CLAUDE.md non-neg #1) but gutted the internals — removed the `_BACKENDS` registry, builder indirection, and custom error class. Now ~6 lines: one guard + construct `ChatOllama`. Adding a stub later is one `if` branch.
- **Layout:** moved the Streamlit entrypoint from `app/streamlit_app.py` to repo-root **`streamlit_app.py`**, deleting the `sys.path.insert` hack (root is on `sys.path` automatically). Kept the **`src/`** package — it's the home for the agent code landing in P2–P4 (`graph.py`, `rag/`, `tools/`, `state.py`, `ingest.py`); flattening it now would just be re-introduced later.
**Why:** The framework-y pieces were speculative gold-plating for a six-knob, one-backend prototype; they hurt readability and slowed iteration without buying anything yet. The simplifications preserve every non-negotiable (local LLM, single `get_llm()` seam, knobs-in-one-place, reproducibility/`temperature=0`).
**Revisit if:** config grows many interdependent knobs (then a typed/validated loader earns its place) or a real second LLM backend lands (then a small dispatch returns).
Related: [[python-314]], [[model-tag]], [[drop-dummy-llm]], [[build-approach-ui-spine]].

## 2026-06-03 — Python pin moved 3.12 → 3.14  (`python-314`)
**[revisit]** The local machine only had Python **3.14.5** installed (no 3.12). Rather than `brew install python@3.12`, we moved the pin to **3.14**: `.python-version` = `3.14`, and the Docker base becomes `python:3.14-slim` (Phase 6). Supersedes the 3.12 decision in [[python-env]].
**Why:** Lowest-friction path on the available machine; 3.14 had native cp314 wheels for the entire Phase 1 stack (streamlit 1.58, langchain-ollama 1.1, pydantic, numpy, pyarrow) — `pip install` resolved cleanly with no source builds.
**Revisit if:** Phase 2 ML deps (chromadb, sentence-transformers, torch) lack cp314 wheels → fall back to 3.13 or 3.12 (would then require installing that interpreter). This is the main open risk of the 3.14 choice.
Related: [[python-env]], [[build-approach-ui-spine]].

## 2026-06-03 — Local model tag is `qwen2.5:3b-instruct`  (`model-tag`)
**[decision]** `config.py` `MODEL` defaults to **`qwen2.5:3b-instruct`** — the tag already pulled locally — rather than the canonical `qwen2.5:3b` written in the docs. Same underlying Qwen2.5 3B Instruct model; avoids a redundant ~1.9 GB pull. Refines [[llm-model]].
**Why:** The instruct tag was already present in Ollama; `qwen2.5:3b` resolves to the same instruct weights anyway. The `model` knob keeps it swappable, so the literal string is not load-bearing.
Related: [[llm-model]].

## 2026-06-03 — Working agreement: plan-first, user drives commits/merges  (`working-agreement`)
**[decision]** Per-phase loop: orient (read PLAN next phase + skim DECISIONS) → **post a short plan and wait for approval before coding** → branch+push → build (ticking PLAN, logging to DECISIONS) → **the user explicitly triggers every commit, merge, and tag** (never autonomous, even mid-phase) → on approval, update PLAN status and do the merge/tag/push. Documented in CLAUDE.md (Working agreement).
**Why:** Keeps the user in control of integration and history, and makes the collaboration loop survive fresh contexts (a cold agent otherwise wouldn't know to plan-first or that the user drives commits). Matches the rhythm used while planning.
**Revisit if:** the user later wants faster cycles (e.g. autonomous checkpoint commits on the branch, or just-build for small phases).
Related: [[git-workflow]].

## 2026-06-03 — Pinned LLM: qwen2.5:3b (constrained hardware)  (`llm-model`)
**[revisit]** Default Ollama model pinned to **`qwen2.5:3b`** (Qwen2.5 3B Instruct); `llama3.2:3b` is the alternative. `config.py` `MODEL` knob makes it swappable.
**Why:** User confirmed constrained hardware, so 3B is the tier. Qwen2.5 3B has good structured/JSON-output adherence, which matters for intake (JSON), router, and the RAG grader. Reproducibility non-negotiable wants a concrete pin, not a candidate list.
**Revisit if:** routing/extraction reliability or generation quality proves weak at 3B → bump to a 7–8B instruct model (Llama 3.1 8B / Qwen2.5 7B), or split models (small for routing/extraction, larger for final generation). Also revisit if a different model handles structured output more reliably.
Related: [[drop-dummy-llm]].

## 2026-06-03 — Git workflow: phase branches, merge commits, phase tags  (`git-workflow`)
**[decision]** One branch per phase named `phase/N-slug`; integrate into `main` via `--no-ff` merge commits; annotate each phase's merge commit with a `phase-N-slug` tag; keep phase branches (don't delete) and push `main` + branches + tags. Non-phase branches use `type/slug` (`fix/`, `docs/`, `chore/`, `refactor/`, `spike/`), chosen per case. Full convention in CLAUDE.md (Git workflow).
**Why:** Merge commits keep a visible per-phase boundary in history; tags make each completed phase a referenceable checkpoint (easy to diff/checkout a phase); kept+pushed branches preserve the per-phase record on the remote. Matches the branch-per-phase plan and the documentation-routing setup.
**How to apply:** branch from up-to-date `main`; publish the branch early; `git merge --no-ff` then `git tag -a phase-N-slug`; push `main`, the branch, and the tag.
Related: [[build-approach-ui-spine]].

## 2026-06-03 — Drop the dummy LLM backend for now (keep the seam)  (`drop-dummy-llm`)
**[revisit]** No dummy/stub LLM backend is built. Only `ollama` is wired — but behind a pluggable `LLM_BACKEND` seam (`get_llm()`), so one can be added later as a single backend branch.
**Why:** The brief only offers the dummy as a *hardware fallback* ("if [a real local LLM] is not possible"), which isn't our situation. Its one genuine engineering benefit — isolating LLM latency in the load test — is a late-phase concern, so carrying a stub (and its per-call-site structured stubs) through P1–P4 is cost without payoff. The bottleneck analysis will instead lean on per-node timing from the trace.
**How to apply:** Nodes must call the `get_llm()` abstraction, never Ollama directly, so the seam stays cheap to extend. Don't scatter Ollama client calls across nodes.
**Revisit if:** the load test's per-node timing isn't conclusive enough to pin the bottleneck → add a stub backend for a clean real-vs-stub A/B. (Also the original fallback reason returns if the target hardware can't run the chosen model.)
Related: [[build-approach-ui-spine]], [[python-env]].

## 2026-06-03 — Python env: venv + pinned requirements + Python 3.12  (`python-env`)
**[decision]** Local env is stdlib **`venv`** with deps pinned in **`requirements.txt`**; Python pinned to **3.12** via `.python-version`; the Dockerfile uses `python:3.12-slim` so local and container match. No Poetry/conda/uv. Resolves the old `requirements.txt / pyproject.toml` ambiguity in the proposal repo tree → `requirements.txt`.
**Why:** Lowest-ceremony option consistent with the "no Make / plain commands" stance, no extra tooling for a reviewer to install, and it closes the reproducibility gaps the docs had left open (no isolation strategy, no Python version pin). 3.12 has solid wheel support across LangGraph/Chroma/sentence-transformers.
**How to apply:** `python3.12 -m venv .venv && . .venv/bin/activate` then `pip install -r requirements.txt`. Keep `.python-version` and the Dockerfile base in sync at 3.12.
**Revisit if:** a dependency lacks a 3.12 wheel (fall back to 3.11) or native/ML deps turn painful via pip (consider conda).
Related: [[build-approach-ui-spine]].

## 2026-06-03 — Streamlit UI evolves as one-tab-per-layer  (`ui-tabs-per-layer`)
**[decision]** The UI is a tabbed app that gains a tab each phase: **Chat (LLM)** → **Corpus** → **RAG** → **Calculator** → **Agent**. The first four are inspector/dev-demo tabs; the **Agent** tab is the product and is the one that satisfies the task's UI requirement (agent steps + RAG result).
**Why:** Keeps every layer independently runnable and demonstrable (great for a live walkthrough and as the functional-test harness), and makes otherwise-invisible scoring criteria visible — the Corpus tab shows "quality processing"/structure-aware chunking; the RAG tab surfaces the corrective grade→rewrite loop (the most "agentic" behaviour). Over-delivers on the deliberately-minimal brief without much cost.
**How to apply:**
- Build display components **once** (chunk card, citation list, trace-step renderer) and reuse them in the RAG and Agent tabs so they can't drift.
- Persistent **sidebar** (not a tab) shows active backend / model / top-k.
- Inspector tabs handle the **not-built-yet/empty** state gracefully (corpus not ingested, no Chroma) so a fresh clone doesn't error.
**Revisit if:** tab count or per-tab complexity starts to sprawl — then group inspectors behind a single "Pipeline inspector" tab and keep Agent as the top-level product.
Related: [[build-approach-ui-spine]].

## 2026-06-03 — Build approach: Streamlit-as-spine, reordered, no Make, functional-first  (`build-approach-ui-spine`)
**[decision]** Reworked the build order and process: (1) **Streamlit is the spine** — a minimal chat UI exists from Phase 1 and gains a visualization each phase; (2) **reordered** to LLM backend + chat → corpus + RAG → calculator → agentic assembly → eval + load test → Docker + README; (3) **dropped Make** in favor of plain documented commands; (4) **functional testing** (through the UI + the 15-Q eval) over classical unit tests.
**Why:** The UI-as-spine keeps every stage runnable and demonstrable, and doubles as the functional-test harness — which is why functional testing through it is sufficient for most of the app. LLM-first de-risks the Ollama backend immediately and gives something runnable on day one. Make added ceremony without value for a prototype this size. Reordering breaks no acceptance criteria (those constrain the final artifact, not build order).
**Exceptions / guards:**
- The **calculator keeps a small direct test set** — it's deterministic, trivially testable, and produces the compensation amounts (and eval ground truth); a wrong euro figure is the worst failure mode, so verifying it only through a chat box is too weak.
- The retrieval tool (`retrieve_passenger_rights`) is born in the **corpus/RAG** phase (the subgraph uses it); the dedicated tools phase is the **calculator**.
- The required **functional eval (15 Qs), load test, Docker, and README** remain as explicit late phases — they're graded deliverables; the eval is itself a functional test.
- **Reproducibility** is independent of Make and still holds: pinned versions, `temperature=0`, idempotent ingest, frozen corpus.
**Revisit if:** the app grows enough that manual/functional verification stops catching regressions — then add targeted tests at the seams (RAG grading, router classification).

## 2026-06-03 — Calculator is eligibility-agnostic; gating happens at fan-in
**[decision]** In the `mixed` path, the eligibility branch and the calculator branch are siblings that run independently and converge at `synthesize`; the calculator does **not** depend on eligibility.
**Why:** This resolves the apparent contradiction "why compute an amount before eligibility is fixed?" The two branches consume *different* inputs — eligibility needs the disruption *reason* + rules (RAG); the calculator needs only route + delay. Neither consumes the other's output. The dependency is a **combination dependency at fan-in** (`final = eligible ? candidate_amount : 0`), not an input dependency between branches — which is exactly what fan-out → fan-in expresses. The calculator therefore computes the **statutory candidate amount** (what Art. 7 awards for that distance band + delay), and the gate is applied at merge. Computing an amount that may be zeroed is free (deterministic, no LLM) and useful: it lets synthesize give a counterfactual ("you'd ordinarily be owed €400, but the cause was weather → no compensation, though care/rerouting still apply").
**Revisit if:** the calculator's contract ever changes to return the *final* amount owed (consuming eligibility) — then the branches are no longer independent, the fan-out collapses to a sequential gate, and the "independent execution" demonstration is lost. Keep the calculator eligibility-agnostic.
**Note:** The §4.3 ASCII diagram has been redrawn (2026-06-03) to show two sibling branches (RAG→eligibility, calculator) fanning in at synthesize, with the gate applied there.

## 2026-06-03 — "Agentic" = directed/structured agent, not open-ended planner
**[decision]** The agent's control flow is governed by the LangGraph structure (router dispatches, edges decide branches), rather than an open-ended planner that freely selects tools at runtime.
**Why:** Predictability and testability matter more than open-ended autonomy for an evaluable interview prototype. The task explicitly equates "agentic" with conditional routing + decomposition + state, all of which this satisfies. The corrective-RAG grade→rewrite loop is the most defensibly "agentic" element. Be ready to articulate this as a deliberate trade-off if probed.
**Revisit if:** the goal shifts toward demonstrating open-ended/model-driven tool selection — then add an LLM tool-calling step (e.g. intake autonomously invoking the calculator) to strengthen the claim.

## 2026-06-03 — Router is an explicit node, not a bare conditional edge
**[decision]** Implement the router as a genuine state-updating node that writes its routing decision into `state`, with the conditional branch as the edge *after* it.
**Why:** Costs nothing, removes the node-vs-edge inconsistency in the original proposal, and makes the routing choice visible in the Streamlit trace/"agent steps" panel — which directly scores the "demonstrate agent operation" requirement.
