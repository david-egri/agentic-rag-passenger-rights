"""LangChain tools — the agent's two explicit capabilities.

Both capabilities are decorated `@tool`s (not plain functions buried in nodes) so there's
no argument about whether they count (CLAUDE.md guardrail #2):

- `retrieve_passenger_rights` — the shared retrieval primitive over the Reg. 261/2004 corpus.
  It embeds the query (with the `search_query:` prefix) and runs a top-k similarity search
  over the persisted Chroma collection. Two callers use it: the corrective-RAG subgraph
  (`src/rag.py`), which grades/rewrites and generates a cited answer from the hits, and the
  main graph's `eligibility` node (`src/graph.py`), which grounds its extraordinary-
  circumstances judgment on a cause-specific query — retrieval only, no generation.
- `calculate_compensation` — the non-retrieval, deterministic, LLM-free calculator. A thin
  `@tool` wrapper; the pure Art. 7 logic (haversine, band table, threshold/reduction) lives
  in `src/calculator.py` and is what the test set targets.

`retrieve_passenger_rights` returns chunk text + citation metadata, so a caller can cite
`source` + `article` (via `citations_from_docs` in `src/rag.py`) and never dump raw text as a
citation.
"""

from langchain_core.tools import tool

import config
from src.calculator import compute_compensation
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


@tool
def calculate_compensation(
    origin_iata: str,
    dest_iata: str,
    delay_hours: float,
    disruption_type: str = "delay",
    rerouting_offered: bool = False,
) -> dict:
    """Compute the EU 261/2004 Art. 7 compensation for a disrupted flight (non-retrieval).

    Deterministic and LLM-free: resolves both airports' coordinates (OpenFlights),
    computes great-circle distance, maps it to the €250 / €400 / €600 distance band, then
    applies the 3-hour delay threshold and the 50%-reduction rule. Returns the *statutory
    candidate* amount — it does NOT judge extraordinary circumstances (that gate is applied
    when the agent synthesizes the final answer).

    Args:
        origin_iata: IATA code of the departure airport (e.g. "BUD").
        dest_iata: IATA code of the final destination (e.g. "LHR").
        delay_hours: arrival delay at the final destination, in hours.
        disruption_type: "delay", "cancellation", or "denied_boarding".
        rerouting_offered: whether the carrier offered re-routing (enables the 50% reduction
            when the arrival delay is within the band's limit).

    Returns:
        A dict with distance_km, band, base_amount_eur, threshold_met, reduction_applied,
        final_amount_eur, resolved airport names, and a human-readable `explanation`.
    """
    return compute_compensation(
        origin_iata, dest_iata, delay_hours, disruption_type, rerouting_offered
    )
