"""Corrective-RAG subgraph — a modular, compiled `StateGraph`.

This is the most defensibly "agentic" part of the system: retrieval that grades its own
results and self-corrects before answering.

    retrieve → grade_documents → (relevant? → generate
                                  not relevant? → rewrite_query → retrieve …)

The grade→rewrite loop is **bounded** by `config.REWRITE_MAX_RETRIES` so latency stays
sane; once retries are exhausted the graph generates from whatever it has (and the
`generate` node is instructed to admit insufficient support rather than invent — the
hallucination firewall).

It is a genuinely **compiled subgraph** (`build_rag_graph().compile()`), so in Phase 4 the
main agent attaches it via `add_node` unchanged — which is what makes it "a subgraph that
does not count toward the 5 main nodes" (CLAUDE.md guardrail #3). It keeps its own typed
`RAGState`; the full `AgentState` lands in Phase 4.

Every node appends a step to `steps` so the Streamlit RAG tab can render the corrective
loop (retrieved chunks → grade decision → rewritten query → grounded answer).
"""

from __future__ import annotations

import operator
from typing import Annotated, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage

import config
from src.llm import get_llm
from src.tools import retrieve_passenger_rights


class RAGState(TypedDict, total=False):
    question: str                       # the original question (never mutated)
    query: str                          # current search query (rewritten on retry)
    documents: list[dict]               # retrieved chunks (text + metadata + distance)
    relevant: bool                      # grader verdict on the current documents
    rewrites: int                       # how many rewrites have happened (bounded)
    answer: str                         # grounded final answer
    citations: list[dict]               # [{source, article, url}] backing the answer
    steps: Annotated[list, operator.add]  # per-node trace for the UI


def passages_block(documents: list[dict], max_chars: int | None = None) -> str:
    """Number the retrieved chunks with their citation tags for an LLM prompt.

    Shared by the RAG `grade`/`generate` nodes and the main graph's `eligibility` grounding,
    so every passage block fed to the small model has the same shape. `max_chars` truncates
    each passage — used by the grader (and eligibility) so the model judges on focused snippets
    rather than being swamped by full sections.
    """
    lines = []
    for i, d in enumerate(documents, 1):
        m = d["metadata"]
        text = d["text"] if max_chars is None else d["text"][:max_chars]
        lines.append(f"[{i}] ({m['source']} · {m['article']})\n{text}")
    return "\n\n".join(lines) if lines else "(no passages retrieved)"


def citations_from_docs(docs: list[dict]) -> list[dict]:
    """Build dedup'd citation dicts from retrieved docs (metadata only, never raw text).

    One citation per (source, article) pair, in first-seen order. Shared by the `generate`
    node and the eligibility grounding in the main graph so both emit the same
    `{source, article, url}` shape — which is what lets `synthesize` dedup-merge the two
    citation sets correctly.
    """
    seen, citations = set(), []
    for d in docs:
        m = d["metadata"]
        key = (m["source"], m["article"])
        if key not in seen:
            seen.add(key)
            citations.append({"source": m["source"], "article": m["article"], "url": m.get("url", "")})
    return citations


# --------------------------------------------------------------------------- nodes
def retrieve(state: RAGState) -> dict:
    query = state.get("query") or state["question"]
    docs = retrieve_passenger_rights.invoke({"query": query})
    step = {
        "node": "retrieve",
        "query": query,
        "hits": [
            {"source": d["metadata"]["source"], "article": d["metadata"]["article"], "distance": d["distance"]}
            for d in docs
        ],
    }
    return {"documents": docs, "steps": [step]}


def grade_documents(state: RAGState) -> dict:
    """Judge whether retrieval is on-topic enough to answer from — else trigger a rewrite.

    The LLM grader makes the call (the autonomous decision), but a strong vector hit acts
    as a safety floor: if the closest passage is within `config.GRADE_DISTANCE_FLOOR`
    cosine distance, we keep it even if the small grader says no — that guards against the
    3B model's false negatives discarding obviously-relevant retrieval.
    """
    prompt = (
        f"Question: {state['question']}\n\n"
        f"Retrieved passages:\n{passages_block(state['documents'], max_chars=600)}\n\n"
        "Is at least ONE passage on-topic and useful for answering this question about EU "
        "air passenger rights? A passage counts as relevant even if it only partly helps. "
        "Answer with one word: yes or no."
    )
    reply = get_llm().invoke(
        [
            SystemMessage(content="You grade retrieval relevance. Reply with exactly one word: yes or no."),
            HumanMessage(content=prompt),
        ]
    ).content
    llm_yes = reply.strip().lower().startswith("y")
    best = min((d["distance"] for d in state["documents"]), default=1.0)
    relevant = llm_yes or best <= config.GRADE_DISTANCE_FLOOR
    return {
        "relevant": relevant,
        "steps": [
            {"node": "grade_documents", "relevant": relevant, "llm": reply.strip(), "best_distance": round(best, 3)}
        ],
    }


def rewrite_query(state: RAGState) -> dict:
    """Reformulate the query to improve retrieval, then loop back to retrieve."""
    prompt = (
        f"The following search query did not retrieve passages that answer the user's "
        f"question well. Rewrite it to improve semantic retrieval from a legal corpus on EU "
        f"air passenger rights (Regulation 261/2004). Return ONLY the rewritten query.\n\n"
        f"User question: {state['question']}\n"
        f"Current query: {state.get('query') or state['question']}"
    )
    new_query = get_llm().invoke(
        [
            SystemMessage(content="You rewrite search queries for legal retrieval. Output only the query."),
            HumanMessage(content=prompt),
        ]
    ).content.strip().strip('"')
    rewrites = state.get("rewrites", 0) + 1
    return {
        "query": new_query,
        "rewrites": rewrites,
        "steps": [{"node": "rewrite_query", "rewrites": rewrites, "new_query": new_query}],
    }


def generate(state: RAGState) -> dict:
    """Answer strictly from the retrieved passages; cite source + article; admit gaps."""
    docs = state["documents"]
    prompt = (
        f"Question: {state['question']}\n\n"
        f"Passages:\n{passages_block(docs)}\n\n"
        "Answer the question using ONLY the information in the passages above, citing the "
        "passages you rely on inline like [1], [2]. Do NOT use outside knowledge and do NOT "
        "invent figures, articles, or rules. If the passages genuinely do not address the "
        "question, say that they do not cover it. Write the answer as complete sentences "
        "(never reply with only a citation marker). Be concise."
    )
    answer = get_llm().invoke(
        [
            SystemMessage(
                content=(
                    "You answer EU air passenger rights questions strictly from the provided "
                    "passages. Never invent figures, articles, or rules that are not in the "
                    "passages, and never answer from outside knowledge — if the passages do "
                    "not contain the answer, say so."
                )
            ),
            HumanMessage(content=prompt),
        ]
    ).content.strip()

    # Citations reference metadata (source + article + url), never raw chunk text.
    citations = citations_from_docs(docs)
    return {"answer": answer, "citations": citations, "steps": [{"node": "generate", "n_citations": len(citations)}]}


# --------------------------------------------------------------------------- wiring
def _route_after_grade(state: RAGState) -> str:
    """Relevant, or out of retries → generate; otherwise rewrite and retry (bounded)."""
    if state.get("relevant") or state.get("rewrites", 0) >= config.REWRITE_MAX_RETRIES:
        return "generate"
    return "rewrite_query"


def build_rag_graph():
    """Build and compile the corrective-RAG subgraph."""
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(RAGState)
    g.add_node("retrieve", retrieve)
    g.add_node("grade_documents", grade_documents)
    g.add_node("rewrite_query", rewrite_query)
    g.add_node("generate", generate)

    g.add_edge(START, "retrieve")
    g.add_edge("retrieve", "grade_documents")
    g.add_conditional_edges("grade_documents", _route_after_grade, {"generate": "generate", "rewrite_query": "rewrite_query"})
    g.add_edge("rewrite_query", "retrieve")
    g.add_edge("generate", END)
    return g.compile()


# Compiled once for import by the UI (and, in Phase 4, the main graph via add_node).
rag_graph = build_rag_graph()


def run_rag(question: str) -> RAGState:
    """Convenience wrapper: run the subgraph for a question and return the final state."""
    return rag_graph.invoke({"question": question, "query": question, "rewrites": 0})


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or "How much compensation for a 4-hour arrival delay on a 2000 km flight?"
    final = run_rag(q)
    print(f"\nQ: {q}\n")
    print(final["answer"])
    print("\nCitations:")
    for c in final["citations"]:
        print(f"  - {c['source']} · {c['article']}")
    print(f"\n(steps: {[s['node'] for s in final['steps']]})")
