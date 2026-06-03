"""LangChain tools — the agent's two explicit capabilities.

Both capabilities are decorated `@tool`s (not plain functions buried in nodes) so there's
no argument about whether they count (CLAUDE.md guardrail #2):

- `retrieve_passenger_rights` — retrieval, lives here because the RAG subgraph uses it
  (Phase 2). It embeds the query (with the `search_query:` prefix) and runs a top-k
  similarity search over the persisted Chroma collection.
- `calculate_compensation` — the non-retrieval, deterministic, LLM-free calculator,
  arrives in Phase 3.

`retrieve_passenger_rights` returns chunk text + citation metadata so the subgraph's
`generate` node can cite `source` + `article` and never dumps raw text as a citation.
"""

from langchain_core.tools import tool

import config
from src.store import embed_query, get_collection


@tool
def retrieve_passenger_rights(query: str, top_k: int | None = None) -> list[dict]:
    """Retrieve the most relevant EU air-passenger-rights passages for a query.

    Runs a semantic similarity search over the ingested Reg. 261/2004 corpus
    (regulation text, Commission interpretative guidelines, plain-language summary) and
    returns the top matches with their citation metadata.

    Args:
        query: A natural-language question about EU air passenger rights.
        top_k: How many passages to return (defaults to config.TOP_K).

    Returns:
        A list of dicts, each with the chunk `text`, its `metadata` (source, article,
        title, url, retrieved_at, chunk_id), and a `distance` (lower = closer).
    """
    k = top_k or config.TOP_K
    collection = get_collection()
    res = collection.query(
        query_embeddings=[embed_query(query)],
        n_results=k,
        include=["documents", "metadatas", "distances"],
    )
    # Chroma returns one list per query; we issued a single query.
    docs = res["documents"][0]
    metas = res["metadatas"][0]
    dists = res["distances"][0]
    return [{"text": t, "metadata": m, "distance": d} for t, m, d in zip(docs, metas, dists)]
