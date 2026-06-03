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


def _flight_summary(details: dict) -> str:
    """One-line summary of the non-null extracted flight fields (or a placeholder)."""
    bits = []
    if details.get("origin_iata") or details.get("dest_iata"):
        bits.append(f"{details.get('origin_iata') or '?'} → {details.get('dest_iata') or '?'}")
    if details.get("delay_hours") is not None:
        bits.append(f"{details['delay_hours']}h delay")
    if details.get("disruption_type"):
        bits.append(str(details["disruption_type"]))
    if details.get("reason"):
        bits.append(f"cause: {details['reason']}")
    if details.get("rerouting_offered"):
        bits.append("re-routed")
    return " · ".join(bits) if bits else "_no flight details extracted_"


def render_agent_trace(steps: list[dict]):
    """Render the main agent run node-by-node — the "agent steps" panel that scores the
    "demonstrate agent operation" requirement. Each of the 7 nodes prints what it decided;
    the `rag` node drills down into the corrective-RAG subgraph (reusing render_rag_trace)."""
    icons = {
        "intake": "📥", "router": "🧭", "planner": "🗂️", "rag": "🔎",
        "eligibility": "⚖️", "calculator": "🧮", "synthesize": "🧩", "fallback": "🚫",
    }
    for i, s in enumerate(steps, 1):
        node = s["node"]
        head = f"{icons.get(node, '•')} **{i}. {node}**"
        if node == "intake":
            st.markdown(f"{head} → classified as `{s['query_type']}`")
            st.caption(f"flight details: {_flight_summary(s.get('flight_details') or {})}")
        elif node == "router":
            st.markdown(f"{head} → route `{s['route']}`")
        elif node == "planner":
            st.markdown(f"{head} → decomposed into {len(s['subtasks'])} subtasks")
            for t in s["subtasks"]:
                st.caption(f"• {t}")
        elif node == "rag":
            st.markdown(
                f"{head} → retrieved {s['n_docs']} passages, {s['rewrites']} rewrite(s), "
                f"{s['n_citations']} citation(s)"
            )
            if s.get("rag_steps"):
                with st.expander("corrective-RAG subgraph trace", expanded=False):
                    render_rag_trace(s["rag_steps"])
        elif node == "eligibility":
            verdict = "✅ compensable" if s.get("eligible") else "❌ extraordinary → no cash"
            st.markdown(f"{head} → {verdict}")
            st.caption(s.get("rationale", ""))
        elif node == "calculator":
            if s.get("error"):
                st.markdown(f"{head} → ⚠️ {s['error']}")
            else:
                st.markdown(
                    f"{head} → {s['distance_km']:,.0f} km ({s['band']}) → candidate €{s['candidate_eur']}"
                )
        elif node == "synthesize":
            extra = " · gated to €0 (extraordinary)" if s.get("gated") else ""
            amt = f"€{s['final_eur']}" if s.get("final_eur") is not None else "—"
            st.markdown(f"{head} → final amount {amt}{extra}")
        elif node == "fallback":
            st.markdown(f"{head} → out-of-scope, honest decline")
