"""Streamlit app — the spine. One tab per build phase (see DECISIONS ui-tabs-per-layer).

Phase 1 ships the shell: a persistent sidebar (active backend / model / top-k) and the
**Chat (LLM)** tab wired straight to `get_llm()`. Later phases light up the Corpus, RAG,
Calculator, and Agent tabs; until then they render a graceful "not built yet" placeholder
so a fresh clone never errors.

Run:  streamlit run streamlit_app.py
"""

import streamlit as st
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

import config
from src.llm import get_llm
from ui_components import (
    render_agent_step,
    render_chunk_card,
    render_citations,
    render_disclaimer,
    render_graph_diagram,
    render_rag_trace,
)

# A light system prompt: this tab talks to the raw model (a dev/demo surface), not the
# grounded agent. Grounding/citation guarantees live in the Agent tab (Phase 4).
CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant for an EU air passenger rights prototype. "
    "This is a direct-to-model developer chat; answer plainly and concisely."
)

st.set_page_config(page_title="EU Passenger Rights — Agentic RAG", page_icon="✈️", layout="wide")


def render_sidebar():
    """Persistent sidebar: active backend / model / top-k (shown across all tabs)."""
    with st.sidebar:
        st.header("✈️ Passenger Rights")
        st.caption("Agentic RAG · Reg. (EC) 261/2004")
        st.divider()
        st.subheader("Active configuration")
        st.metric("Backend", config.LLM_BACKEND)
        st.metric("Model", config.MODEL)
        st.metric("Top-k (retrieval)", config.TOP_K)
        st.caption(f"Ollama: {config.OLLAMA_URL}")
        st.caption(f"temperature={config.TEMPERATURE}")


def render_chat_tab():
    """Chat (LLM) tab — direct conversation with the configured local model, streamed.

    Standard chat layout: a fixed-height, scrollable transcript with the input box
    pinned directly beneath it.
    """
    st.subheader("Chat (LLM)")
    st.caption(
        "Talks directly to the local model via the `get_llm()` seam — no retrieval, "
        "no agent graph. The spine for everything built on top."
    )

    # Show the exact system prompt sent with every turn (collapsed by default).
    with st.expander("System prompt", expanded=False):
        st.markdown(f"> {CHAT_SYSTEM_PROMPT}")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []  # list[HumanMessage | AIMessage]

    # Scrollable transcript above; input below.
    transcript = st.container(height=460, border=True)

    def render_message(msg):
        role = "user" if isinstance(msg, HumanMessage) else "assistant"
        with transcript.chat_message(role):
            st.markdown(msg.content)

    if st.session_state.chat_history:
        for msg in st.session_state.chat_history:
            render_message(msg)
    else:
        transcript.caption("No messages yet — ask the model something below.")

    prompt = st.chat_input("Ask the model anything…")
    if not prompt:
        return

    user_msg = HumanMessage(content=prompt)
    st.session_state.chat_history.append(user_msg)
    render_message(user_msg)

    messages = [SystemMessage(content=CHAT_SYSTEM_PROMPT), *st.session_state.chat_history]
    with transcript.chat_message("assistant"):
        try:
            stream = (chunk.content for chunk in get_llm().stream(messages))
            reply = st.write_stream(stream)
        except Exception as exc:  # surface backend/connection errors instead of a stack trace
            reply = None
            st.error(
                f"Could not reach the LLM backend: {exc}\n\n"
                "Is Ollama running and the model pulled? "
                "Try `ollama serve` and `ollama pull` the configured model."
            )

    if reply:
        st.session_state.chat_history.append(AIMessage(content=reply))


def _load_corpus_chunks():
    """Pull all ingested chunks from Chroma, grouped by source. Returns (groups, total)
    or (None, 0) if the store isn't built yet — so the tab degrades gracefully."""
    try:
        from src.store import get_collection

        col = get_collection()
        total = col.count()
        if not total:
            return None, 0
        got = col.get(include=["documents", "metadatas"])
        chunks = [{"text": d, "metadata": m} for d, m in zip(got["documents"], got["metadatas"])]
        chunks.sort(key=lambda c: c["metadata"].get("chunk_id", ""))
        groups = {}
        for c in chunks:
            groups.setdefault(c["metadata"]["source"], []).append(c)
        return groups, total
    except Exception:
        return None, 0


def render_corpus_tab():
    """Corpus inspector — makes structure-aware chunking visible: counts, the Article/
    Recital/Section boundaries, and per-chunk citation metadata."""
    st.subheader("Corpus")
    st.caption(
        "Browse the ingested, structure-aware chunks. Chunking follows legal structure "
        "(Article / Recital / numbered section / heading), not fixed token windows."
    )
    groups, total = _load_corpus_chunks()
    if not groups:
        st.info(
            "**Corpus not ingested yet.** Run `python -m src.ingest` to parse "
            "`data/corpus/` into ChromaDB, then reload this tab."
        )
        return

    cols = st.columns(len(groups) + 1)
    cols[0].metric("Total chunks", total)
    for col, (src, chunks) in zip(cols[1:], groups.items()):
        col.metric(src, len(chunks))

    source = st.selectbox("Document", list(groups.keys()))
    chunks = groups[source]
    needle = st.text_input("Filter (article label or text contains…)", "").strip().lower()
    if needle:
        chunks = [
            c for c in chunks
            if needle in c["metadata"]["article"].lower() or needle in c["text"].lower()
        ]
    st.caption(f"{len(chunks)} chunk(s)")
    for c in chunks:
        render_chunk_card(c)


def render_rag_tab():
    """RAG inspector — run the corrective-RAG subgraph and watch it self-correct:
    retrieve → grade → (rewrite → retrieve) → grounded, cited answer."""
    st.subheader("RAG")
    st.caption(
        "Runs the compiled corrective-RAG subgraph (`src/rag.py`). Watch the grade→rewrite "
        "loop, then the grounded answer with citations. This is the standalone retrieval "
        "layer — the full agent (with routing, eligibility, calculator) arrives in Phase 4."
    )

    _, total = _load_corpus_chunks()
    if not total:
        st.info("**Corpus not ingested yet.** Run `python -m src.ingest` first.")
        return

    examples = [
        "Is a strike by the airline's own staff an extraordinary circumstance?",
        "What rights do I have if my flight is cancelled?",
        "Am I covered if I fly from outside the EU to the EU on a non-EU airline?",
    ]
    example = st.selectbox("Example question (or type your own below)", ["—"] + examples)
    default = "" if example == "—" else example
    question = st.text_input("Question", value=default)

    if not st.button("Run RAG", type="primary") or not question.strip():
        return

    try:
        from src.rag import rag_graph

        inputs = {"question": question, "query": question, "rewrites": 0}
        final = None
        with st.spinner("Retrieving, grading, and generating…"):
            for state in rag_graph.stream(inputs, stream_mode="values"):
                final = state
    except Exception as exc:
        st.error(
            f"Could not run RAG: {exc}\n\nIs Ollama running (LLM + `{config.EMBEDDING_MODEL}` "
            "embeddings)? Try `ollama serve`."
        )
        return

    st.markdown("#### Corrective-RAG trace")
    render_rag_trace(final.get("steps", []))

    st.markdown("#### Answer")
    st.write(final.get("answer", "_(no answer)_"))
    render_citations(final.get("citations", []))
    render_disclaimer()

    with st.expander(f"Retrieved passages ({len(final.get('documents', []))})", expanded=False):
        for d in final.get("documents", []):
            render_chunk_card(d, show_distance=True)


def render_calculator_tab():
    """Calculator inspector — exercise the deterministic, LLM-free compensation tool:
    flight inputs → distance → band → amount, with the threshold/reduction mechanics shown."""
    st.subheader("Calculator")
    st.caption(
        "Runs `calculate_compensation` (`src/calculator.py`) — deterministic, no LLM, no "
        "retrieval. Great-circle distance (OpenFlights) → Art. 7 band → amount, with the "
        "3-hour delay threshold and the 50%-reduction rule. Returns the *statutory candidate* "
        "amount; the extraordinary-circumstances gate is the agent's job (Phase 4)."
    )

    examples = {
        "—": ("", "", 4.0, "delay", False),
        "Budapest → London, delayed 4 h": ("BUD", "LHR", 4.0, "delay", False),
        "Madrid → New York, cancelled, +7 h": ("MAD", "JFK", 7.0, "cancellation", False),
        "Frankfurt → Cairo, delayed 5 h": ("FRA", "CAI", 5.0, "delay", False),
        "Paris → Rome, delayed 2 h (under threshold)": ("CDG", "FCO", 2.0, "delay", False),
        "Paris → Rome, re-routed within 2 h (50% rule)": ("CDG", "FCO", 1.5, "cancellation", True),
    }
    example = st.selectbox("Example (or fill the fields below)", list(examples.keys()))
    o_def, d_def, delay_def, dtype_def, rr_def = examples[example]

    c1, c2, c3 = st.columns(3)
    origin = c1.text_input("Origin IATA", value=o_def, max_chars=3).strip().upper()
    dest = c2.text_input("Destination IATA", value=d_def, max_chars=3).strip().upper()
    delay = c3.number_input("Arrival delay (hours)", min_value=0.0, value=delay_def, step=0.5)

    c4, c5 = st.columns(2)
    from src.calculator import DISRUPTION_TYPES

    dtype = c4.selectbox("Disruption type", DISRUPTION_TYPES, index=DISRUPTION_TYPES.index(dtype_def))
    rerouting = c5.checkbox("Re-routing offered", value=rr_def,
                            help="Enables the 50% reduction when arrival is within the band's limit.")

    if not st.button("Calculate", type="primary"):
        return
    if not origin or not dest:
        st.warning("Enter both origin and destination IATA codes.")
        return

    try:
        from src.calculator import compute_compensation

        r = compute_compensation(origin, dest, delay, dtype, rerouting)
    except Exception as exc:
        st.error(f"Could not calculate: {exc}")
        return

    st.markdown(f"#### {r['origin_name']} → {r['dest_name']}")
    m1, m2, m3 = st.columns(3)
    m1.metric("Distance", f"{r['distance_km']:,.0f} km")
    m2.metric("Band", r["band"])
    m3.metric("Final amount", f"€{r['final_amount_eur']}",
              delta=None if r["final_amount_eur"] == r["base_amount_eur"]
              else f"from €{r['base_amount_eur']}")

    g1, g2, g3 = st.columns(3)
    g1.markdown(f"Base amount: **€{r['base_amount_eur']}**")
    g2.markdown(f"3 h threshold met: {'✅' if r['threshold_met'] else '❌'}")
    g3.markdown(f"50% reduction: {'✅ applied' if r['reduction_applied'] else '— not applied'}")

    st.info(r["explanation"])
    with st.expander("Raw tool output", expanded=False):
        st.json(r)
    render_disclaimer()


def render_agent_tab():
    """Agent tab — the product. Runs the full 7-node agent graph and walks the nodes:
    intake → router → (planner) → rag/eligibility ‖ calculator → synthesize, with the
    grounded final answer, citations, and the 'not legal advice' disclaimer."""
    st.subheader("Agent")
    st.caption(
        "The full agentic-RAG graph (`src/graph.py`): intake classifies the query, the router "
        "dispatches, `mixed`/`compensation_calc` fan out to an eligibility branch (RAG → "
        "eligibility) and the deterministic calculator, and synthesize gates and composes the "
        "answer. Watch every node below."
    )

    with st.expander("📊 Graph structure (the wiring behind the agent)", expanded=False):
        st.caption(
            "Generated live from the compiled graph (`agent_graph.get_graph().draw_mermaid()`), "
            "so it always matches the code. Solid edges are unconditional; dashed edges are "
            "conditional routes. The `rag` node invokes the corrective-RAG subgraph (not shown)."
        )
        from src.graph import agent_graph

        render_graph_diagram(agent_graph)

    _, total = _load_corpus_chunks()
    if not total:
        st.info("**Corpus not ingested yet.** Run `python -m src.ingest` first (the agent needs retrieval).")
        return

    examples = [
        "What are my rights if my flight is cancelled?",
        "My flight from Budapest to London was delayed 4 hours. How much compensation do I get?",
        "My Paris to Rome flight was cancelled due to an airline staff strike and I got in 6 hours late — am I entitled to anything, and how much?",
        "My Madrid to New York flight was cancelled because of a snowstorm. What are my rights and how much am I owed?",
        "How much does it cost to bring a dog on the flight?",
    ]
    example = st.selectbox("Example question (or type your own below)", ["—"] + examples)
    default = "" if example == "—" else example
    question = st.text_input("Your question", value=default)

    if not st.button("Run agent", type="primary") or not question.strip():
        return

    try:
        from src.graph import agent_graph

        final = None
        rendered = 0  # how many trace steps we've already drawn (the trace is append-only)
        with st.status("Running the agent graph…", expanded=True) as status:
            # The graph is streamed in `values` mode: each yield is a full state snapshot, so
            # the append-only `trace` grows step by step. Render each new node as it arrives so
            # the user watches the agent work live (CLAUDE.md: stream + append to the trace).
            for state in agent_graph.stream({"user_query": question, "trace": []}, stream_mode="values"):
                final = state
                trace = state.get("trace", [])
                for i in range(rendered, len(trace)):
                    render_agent_step(i + 1, trace[i])
                rendered = len(trace)
            status.update(label="Agent run complete", state="complete")
    except Exception as exc:
        st.error(
            f"Could not run the agent: {exc}\n\nIs Ollama running (LLM + `{config.EMBEDDING_MODEL}` "
            "embeddings)? Try `ollama serve`."
        )
        return

    st.markdown("#### Answer")
    st.markdown(final.get("final_answer", "_(no answer)_"))
    render_citations(final.get("rag_citations", []))
    render_disclaimer()

    docs = final.get("retrieved_docs", [])
    if docs:
        with st.expander(f"Retrieved passages ({len(docs)})", expanded=False):
            for d in docs:
                render_chunk_card(d, show_distance=True)


def main():
    render_sidebar()
    st.title("EU Air Passenger Rights — Agentic RAG")

    chat, corpus, rag, calc, agent = st.tabs(
        ["💬 Chat (LLM)", "📚 Corpus", "🔎 RAG", "🧮 Calculator", "🤖 Agent"]
    )
    with chat:
        render_chat_tab()
    with corpus:
        render_corpus_tab()
    with rag:
        render_rag_tab()
    with calc:
        render_calculator_tab()
    with agent:
        render_agent_tab()


main()
