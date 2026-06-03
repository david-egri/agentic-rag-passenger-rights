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


def render_placeholder_tab(name, phase, blurb):
    """Graceful 'not built yet' state for tabs that later phases will fill in."""
    st.subheader(name)
    st.info(f"**Coming in {phase}.** {blurb}")


def main():
    render_sidebar()
    st.title("EU Air Passenger Rights — Agentic RAG")

    chat, corpus, rag, calc, agent = st.tabs(
        ["💬 Chat (LLM)", "📚 Corpus", "🔎 RAG", "🧮 Calculator", "🤖 Agent"]
    )
    with chat:
        render_chat_tab()
    with corpus:
        render_placeholder_tab(
            "Corpus", "Phase 2",
            "Browse the ingested corpus: chunks per document, Article/Recital boundaries, "
            "and per-chunk metadata.",
        )
    with rag:
        render_placeholder_tab(
            "RAG", "Phase 2",
            "Watch corrective retrieval: retrieved chunks → grade decision → rewritten "
            "query (if any) → grounded, cited answer.",
        )
    with calc:
        render_placeholder_tab(
            "Calculator", "Phase 3",
            "Deterministic compensation tool: flight inputs → distance → band → amount.",
        )
    with agent:
        render_placeholder_tab(
            "Agent", "Phase 4",
            "The product: full node-by-node agent trace + grounded answer, citations, and "
            "the 'not legal advice' disclaimer.",
        )


main()
