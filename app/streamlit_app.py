"""Streamlit app — the spine. One tab per build phase (see DECISIONS ui-tabs-per-layer).

Phase 1 ships the shell: a persistent sidebar (active backend / model / top-k) and the
**Chat (LLM)** tab wired straight to `get_llm()`. Later phases light up the Corpus, RAG,
Calculator, and Agent tabs; until then they render a graceful "not built yet" placeholder
so a fresh clone never errors.

Run:  streamlit run app/streamlit_app.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# `streamlit run app/streamlit_app.py` puts app/ on sys.path, not the repo root.
# Add the repo root so `import src...` resolves.
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import streamlit as st  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage  # noqa: E402

from src.config import get_config  # noqa: E402
from src.llm import get_llm  # noqa: E402

# A light system prompt: this tab talks to the raw model (a dev/demo surface), not the
# grounded agent. Grounding/citation guarantees live in the Agent tab (Phase 4).
_CHAT_SYSTEM_PROMPT = (
    "You are a helpful assistant for an EU air passenger rights prototype. "
    "This is a direct-to-model developer chat; answer plainly and concisely."
)

st.set_page_config(page_title="EU Passenger Rights — Agentic RAG", page_icon="✈️", layout="wide")


def render_sidebar() -> None:
    """Persistent sidebar: active backend / model / top-k (shown across all tabs)."""
    cfg = get_config()
    with st.sidebar:
        st.header("✈️ Passenger Rights")
        st.caption("Agentic RAG · Reg. (EC) 261/2004")
        st.divider()
        st.subheader("Active configuration")
        st.metric("Backend", cfg.llm_backend)
        st.metric("Model", cfg.model)
        st.metric("Top-k (retrieval)", cfg.top_k)
        st.caption(f"Ollama: {cfg.ollama_url}")
        st.caption(f"temperature={cfg.temperature}")


def render_chat_tab() -> None:
    """Chat (LLM) tab — direct conversation with the configured local model, streamed.

    Standard chat layout: a fixed-height, scrollable message area with the input box
    pinned directly beneath it (a top-level `st.chat_input` can't pin to the viewport
    bottom from inside a tab, so we anchor the input under a sized container instead).
    """
    st.subheader("Chat (LLM)")
    st.caption(
        "Talks directly to the local model via the `get_llm()` seam — no retrieval, "
        "no agent graph. The spine for everything built on top."
    )

    # Show the exact system prompt sent with every turn (collapsed by default).
    with st.expander("System prompt", expanded=False):
        st.markdown(f"> {_CHAT_SYSTEM_PROMPT}")

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []  # list[HumanMessage | AIMessage]

    # Scrollable transcript above; input below.
    transcript = st.container(height=460, border=True)

    def _render_message(msg) -> None:
        role = "user" if isinstance(msg, HumanMessage) else "assistant"
        with transcript.chat_message(role):
            st.markdown(msg.content)

    # Replay prior turns into the transcript.
    if st.session_state.chat_history:
        for msg in st.session_state.chat_history:
            _render_message(msg)
    else:
        transcript.caption("No messages yet — ask the model something below.")

    prompt = st.chat_input("Ask the model anything…")
    if not prompt:
        return

    user_msg = HumanMessage(content=prompt)
    st.session_state.chat_history.append(user_msg)
    _render_message(user_msg)

    messages = [SystemMessage(content=_CHAT_SYSTEM_PROMPT), *st.session_state.chat_history]
    with transcript.chat_message("assistant"):
        try:
            llm = get_llm()
            stream = (chunk.content for chunk in llm.stream(messages))
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


def render_placeholder_tab(name: str, phase: str, blurb: str) -> None:
    """Graceful 'not built yet' state for tabs that later phases will fill in."""
    st.subheader(name)
    st.info(f"**Coming in {phase}.** {blurb}")


def main() -> None:
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
