"""The typed agent state — one object carried across every node of the main graph.

`AgentState` is the contract between nodes (CLAUDE.md: "typed state" is a hard requirement,
not ceremony). Each node reads the keys it needs and returns a partial dict that LangGraph
merges in. Most keys overwrite; `trace` is the exception — it uses an `operator.add`
reducer so every node *appends* its step (the fan-out branches each contribute) and the
Streamlit Agent tab can render the run node-by-node.

Mirrors §4.2 of the proposal. `total=False` so partial updates are valid TypedDicts.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

QueryType = Literal["rights_info", "compensation_calc", "mixed", "out_of_scope"]


class AgentState(TypedDict, total=False):
    user_query: str             # the raw question from the user
    query_type: QueryType       # intake's classification; the router dispatches on it
    flight_details: dict        # {origin_iata, dest_iata, delay_hours, disruption_type, reason, rerouting_offered}
    subtasks: list[str]         # planner's decomposition of a `mixed` query
    retrieved_docs: list[dict]  # RAG chunks (text + metadata + distance) — feeds eligibility
    rag_answer: str             # grounded rights answer from the RAG subgraph
    rag_citations: list[dict]   # [{source, article, url}] backing rag_answer
    eligibility: dict           # {eligible: bool, rationale: str}
    calc_result: dict           # calculate_compensation output (distance_km, band, amounts, …)
    final_answer: str           # the composed answer shown to the user
    trace: Annotated[list, operator.add]  # per-node log for the Agent tab (append-only)
