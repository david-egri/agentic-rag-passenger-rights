"""Reusable Streamlit display pieces — built once, shared across tabs.

The Corpus, RAG, and (Phase 4) Agent tabs all render the same primitives: a retrieved/
ingested chunk, a citation list, the corrective-RAG trace, and the standing "not legal
advice" disclaimer. Keeping them here (DECISIONS `ui-tabs-per-layer`) means they can't
drift between tabs.
"""

import streamlit as st

# Non-negotiable #5: every answer that interprets the rules carries this. The synthesize
# node (Phase 4) reuses the same text so the agent and the RAG inspector say the same thing.
DISCLAIMER = (
    "ℹ️ This is general information about Regulation (EC) No 261/2004, not legal advice. "
    "Compensation also depends on facts a chatbot can't verify (exact times, cause of "
    "disruption, carrier). The 2025 reform of the rules is not yet enacted."
)


def render_disclaimer():
    st.caption(DISCLAIMER)


def render_chunk_card(chunk: dict, *, show_distance: bool = False):
    """Render one chunk (ingested or retrieved). `chunk` has `text` + `metadata`, and
    optionally `distance`. The header is the citation tag (source · article)."""
    m = chunk["metadata"]
    header = f"**{m.get('source', '?')}** · {m.get('article', '?')}"
    if show_distance and "distance" in chunk:
        header += f"  ·  distance `{chunk['distance']:.3f}`"
    with st.container(border=True):
        st.markdown(header)
        if m.get("title"):
            st.caption(m["title"])
        st.write(chunk["text"])
        meta_bits = [f"`{k}={m[k]}`" for k in ("doc_type", "chunk_id", "retrieved_at") if m.get(k)]
        if m.get("url"):
            meta_bits.append(f"[source]({m['url']})")
        if meta_bits:
            st.caption(" · ".join(meta_bits))


def render_citations(citations: list[dict]):
    """Compact citation list (source · article, linked to the source URL when present)."""
    if not citations:
        return
    st.markdown("**Citations**")
    for c in citations:
        label = f"{c['source']} · {c['article']}"
        st.markdown(f"- [{label}]({c['url']})" if c.get("url") else f"- {label}")


def render_rag_trace(steps: list[dict]):
    """Render the corrective-RAG loop as an ordered trace: retrieval, grade verdict,
    any query rewrite, and the final generate — so the self-correction is visible."""
    for s in steps:
        node = s["node"]
        if node == "retrieve":
            with st.expander(f"🔎 retrieve · query: _{s['query']}_", expanded=False):
                for h in s["hits"]:
                    st.markdown(f"- `{h['distance']:.3f}`  {h['source']} · {h['article']}")
        elif node == "grade_documents":
            verdict = "✅ relevant" if s["relevant"] else "❌ not relevant → rewrite"
            st.markdown(f"⚖️ **grade_documents** → {verdict}  ·  LLM said `{s['llm']}`, best distance `{s['best_distance']}`")
        elif node == "rewrite_query":
            st.markdown(f"✏️ **rewrite_query** (#{s['rewrites']}) → _{s['new_query']}_")
        elif node == "generate":
            st.markdown(f"📝 **generate** → answer with {s['n_citations']} citation(s)")
