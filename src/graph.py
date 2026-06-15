"""The main agent graph — typed state + the directed agent that ties retrieval, eligibility,
and the deterministic calculator together.

Topology:

    START → classify → extract ─┬─ out_of_scope ──→ fallback → END
                                ├─ rights_info ───→ rag ──────────────→ synthesize → END
                                └─ compensation_calc / mixed → [rag, calculator]  (fan-out)

        rag → (rights_info? → synthesize : → eligibility)
        eligibility → synthesize        calculator → synthesize        (fan-in)

`classify` detects three boolean intent signals (in_scope / asks_rights / asks_amount) and the
query-type lane is derived from them in code (`_derive_query_type`) — more robust than asking the
3B model for the label directly. `extract` pulls the flight entities. The corrective-RAG
**subgraph** is reused in both the rights_info path and the eligibility branch via a single shared
`rag` node — it *invokes* the compiled `rag_graph`, it does not reimplement retrieval.

compensation_calc and mixed are a real **fan-out → fan-in**: the eligibility branch
(rag → eligibility) and the calculator branch run as independent siblings and converge at
`synthesize`. The only coupling is the gate applied there: `final = eligible ? candidate : 0` —
the calculator never waits on eligibility. `synthesize` is a **deferred** node so it waits for
*both* branches even though they are different lengths (calculator is one hop, eligibility two).

Every node appends a step to `state["trace"]` (append-only reducer) so the Streamlit Agent tab
can render the run node-by-node. All model access goes through the `get_llm()` seam
(CLAUDE.md constraint #1) — nodes use `get_llm().with_structured_output(...)` for typed output.
"""

from __future__ import annotations

import operator
from typing import Annotated, Literal, TypedDict

from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from src.calculator import DISRUPTION_TYPES
from src.llm import get_llm
from src.rag import rag_graph
from src.tools import calculate_compensation

SYSTEM_PROMPT = (
    "You are an assistant for EU air passenger rights under Regulation (EC) No 261/2004, which "
    "covers ONLY flight delays, cancellations, denied boarding, and the compensation/care they "
    "trigger. Follow the task instructions and return only the requested structured data."
)


# ------------------------------------------------------------------------------- state

QueryType = Literal["rights_info", "compensation_calc", "mixed", "out_of_scope"]


class IntentSignals(TypedDict):       # what classify's LLM call emits
    in_scope: bool
    asks_rights: bool
    asks_amount: bool


class ClassifyResult(IntentSignals):  # the signals plus the query_type derived from them
    query_type: QueryType


class FlightDetails(TypedDict):
    origin_iata: str | None
    dest_iata: str | None
    delay_hours: float | None
    disruption_type: str | None
    reason: str | None
    rerouting_offered: bool | None


class EligibilityResult(TypedDict):
    eligible: bool
    rationale: str


class AgentState(TypedDict, total=False):
    user_query: str                       # the raw question from the user
    classification: ClassifyResult        # classify's verdict; the edge dispatches on query_type
    flight_details: FlightDetails         # entities extracted by the extract node
    retrieved_docs: list[dict]            # RAG chunks (text + metadata + distance) — feeds eligibility
    rag_answer: str                       # grounded rights answer from the RAG subgraph
    rag_citations: list[dict]             # [{source, article, url}] backing rag_answer
    eligibility: EligibilityResult        # the eligibility verdict {eligible, rationale}
    calc_result: dict                     # calculate_compensation output (distance_km, band, amounts, …)
    final_answer: str                     # the composed answer shown to the user
    trace: Annotated[list, operator.add]  # per-node log for the Agent tab (append-only)


# ----------------------------------------------------------------------------- helpers

def _docs_context(docs: list[dict], n: int = 4, max_chars: int = 600) -> str:
    """Number the top retrieved chunks (truncated) as grounding context for a prompt."""
    lines = []
    for i, d in enumerate(docs[:n], 1):
        m = d["metadata"]
        lines.append(f"[{i}] ({m['source']} · {m['article']})\n{d['text'][:max_chars]}")
    return "\n\n".join(lines) if lines else "(no passages retrieved)"


def _derive_query_type(signals: dict) -> QueryType:
    """Map the classifier's boolean signals to a query-type lane."""
    if not signals.get("in_scope", True):
        return "out_of_scope"
    asks_rights = signals.get("asks_rights", False)
    asks_amount = signals.get("asks_amount", False)
    if asks_rights and asks_amount:
        return "mixed"
    if asks_amount:
        return "compensation_calc"
    return "rights_info"


# ------------------------------------------------------------------------------- nodes

def classify(state: AgentState) -> dict:
    """Classify the question by detecting three boolean intent signals; derive the lane in code.

    Asking the 3B model for three independent booleans (in_scope / asks_rights / asks_amount) and
    deriving `query_type` from them is more robust than asking it for the four-way label directly.
    """
    query = state["user_query"]
    prompt = f"""
        User message: "{query}"

        Determine three things about the message and set each independently (a message can be both
        asks_rights and asks_amount at once):

           - in_scope: Is it about a flight disruption under Reg. 261 — a delay, cancellation, or
             denied boarding (and the compensation/care it triggers)? Set false for anything else,
             including fees, charges, or prices for services (baggage / checked-bag fees, seat
             selection, pets, ticket pricing, visas) and non-flight topics — false EVEN IF it asks
             "how much" or "how much does it cost / charge".
           - asks_rights: Does it ask what the passenger is entitled to, their rights, or WHETHER a
             remedy applies — e.g. "what are my rights?", "am I entitled to anything?", "can I get a
             refund?" (an entitlement / eligibility question)?
           - asks_amount: Does it ask for the cash-compensation FIGURE — e.g. "how much", "how much
             compensation", "how much am I owed", "how much will I get", "what compensation do I get",
             "what am I owed", "what amount", "how many euros"? Asking only WHETHER a remedy or refund
             applies, without asking for the figure, is NOT asks_amount (that is asks_rights).

        Examples:
           - 'What are my rights if my flight is delayed?'
             → in_scope=true, asks_rights=true, asks_amount=false
           - 'My flight was 4 hours late — how much will I get?'
             → in_scope=true, asks_rights=false, asks_amount=true
           - 'My flight was cancelled — am I entitled to anything, and how much?'
             → in_scope=true, asks_rights=true, asks_amount=true
           - 'How much does it cost to check a second bag?'
             → in_scope=false, asks_rights=false, asks_amount=false
        """
    try:
        signals = get_llm().with_structured_output(IntentSignals).invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
    except Exception:  # small-model schema miss → _derive_query_type defaults to rights_info
        signals = {}
    if not isinstance(signals, dict):
        signals = {}

    query_type = _derive_query_type(signals)
    classification = {**signals, "query_type": query_type}
    return {"classification": classification, "trace": [{"node": "classify", "query_type": query_type}]}


def extract(state: AgentState) -> dict:
    """Extract structured flight details from the question (null for anything not stated)."""
    query = state["user_query"]
    prompt = f"""
        User message: "{query}"

        Extract `flight_details` from the message. Use null for any field not stated:
           - origin_iata: 3-letter IATA code of the DEPARTURE airport — where the flight leaves from
             ("from …"). Infer from the city name if obvious, else null.
           - dest_iata: 3-letter IATA code of the ARRIVAL airport — the final destination ("to …").
             Infer from the city name if obvious, else null.
           - delay_hours: arrival delay in hours, as a number (e.g. 4 for "4 hours late"); null if no
             delay is stated.
           - disruption_type: one of {DISRUPTION_TYPES} — "delay" for a late flight, "cancellation"
             for a cancelled one, "denied_boarding" for being bumped / overbooked.
           - reason: the cause of disruption ONLY if it is explicitly stated (e.g. "weather", "airline
             staff strike"); null if no cause is given. Do not infer or invent a cause.
           - rerouting_offered: true if the airline offered an alternative flight / re-routing, false
             if it did not, null if not mentioned.

        Direction matters — do not swap origin and destination. The origin is where the flight departs
        ("from …"); the destination is where it arrives ("to …"). In "A to B" or "A → B", A is the
        origin and B is the destination.

        Example (no cause stated, so reason is null): "My BUD to LHR flight was delayed 4 hours" →
        origin_iata=BUD, dest_iata=LHR, delay_hours=4, disruption_type=delay, reason=null,
        rerouting_offered=null.
        """
    try:
        details = get_llm().with_structured_output(FlightDetails).invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
    except Exception:  # small-model schema miss → keep going with no details
        details = {}
    if not isinstance(details, dict):
        details = {}
    # Normalise IATA codes that did come through.
    for k in ("origin_iata", "dest_iata"):
        if isinstance(details.get(k), str):
            details[k] = details[k].strip().upper() or None

    return {"flight_details": details, "trace": [{"node": "extract", "flight_details": details}]}


def rag(state: AgentState) -> dict:
    """Invoke the compiled corrective-RAG **subgraph** and map its result into AgentState.

    This is the subgraph attached as a node (CLAUDE.md guardrail #3): it calls `rag_graph.invoke`,
    it does not reimplement retrieval. Schemas differ (RAGState vs AgentState), so the mapping
    happens here at the boundary. The retrieved docs feed the eligibility node (in the eligibility
    branch); the answer/citations feed synthesize.
    """
    out = rag_graph.invoke({"question": state["user_query"], "query": state["user_query"], "rewrites": 0})
    return {
        "retrieved_docs": out.get("documents", []),
        "rag_answer": out.get("answer", ""),
        "rag_citations": out.get("citations", []),
        "trace": [
            {
                "node": "rag",
                "n_docs": len(out.get("documents", [])),
                "rewrites": out.get("rewrites", 0),
                "n_citations": len(out.get("citations", [])),
                "rag_steps": out.get("steps", []),  # the inner corrective loop, for drill-down
            }
        ],
    }


def eligibility(state: AgentState) -> dict:
    """Autonomous decision: is the disruption compensable, or an extraordinary circumstance?

    Combines the extracted `reason` with the retrieved rules (the rag node runs first in this
    branch) and the well-known EU261 carve-outs. Eligibility-agnostic of the amount — the gate is
    applied at synthesize.
    """
    details = state.get("flight_details") or {}
    reason = (details.get("reason") or "").strip()

    # No cause stated → default to compensable. Extraordinary circumstances are an exception
    # the *carrier* must prove (Art. 5(3)); absent a stated extraordinary cause, the default
    # is that compensation is in principle owed. Deterministic — and saves an LLM call.
    if not reason:
        result = {
            "eligible": True,
            "rationale": "No extraordinary cause was stated, so compensation is in principle owed "
            "(the airline would have to prove an extraordinary circumstance to be exempt).",
        }
        return {"eligibility": result, "trace": [{"node": "eligibility", **result}]}

    context = _docs_context(state.get("retrieved_docs", []))
    # Reframed around "within the carrier's control" — asking the small model directly about
    # "extraordinary" invites the error of treating every strike as extraordinary.
    prompt = f"""
        Cause of the flight disruption: "{reason}"

        Relevant retrieved rules:
        {context}

        Decide whether cash compensation under Art. 7 is in principle owed. The test: was the cause
        WITHIN the airline's own control, or an EXTRAORDINARY circumstance beyond it?

        Causes WITHIN the carrier's control — compensation IS owed (eligible = true):
           - the airline's OWN staff/crew strike
           - technical or operational problems
           - routine maintenance
           - overbooking

        EXTRAORDINARY causes beyond the carrier's control — NO cash compensation (eligible = false),
        though care/re-routing still apply:
           - bad weather
           - air-traffic-control restrictions
           - security risks
           - political instability
           - strikes by THIRD PARTIES (e.g. airport staff, ATC), not the airline's own staff

        Worked examples:
           - "strike by the airline's own cabin crew" → eligible = true (own staff, within control)
           - "snowstorm" → eligible = false
           - "air traffic control strike" → eligible = false (third party)

        Set `rationale` to one sentence naming the cause and whether it was within the carrier's control.
        """
    try:
        parsed = get_llm().with_structured_output(EligibilityResult).invoke(
            [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=prompt)]
        )
    except Exception:  # small-model schema miss → default to owed-in-principle below
        parsed = {}
    if not isinstance(parsed, dict):
        parsed = {}
    eligible = parsed.get("eligible")
    if not isinstance(eligible, bool):
        eligible = True  # default to owed-in-principle; synthesize still gates on the calc
    rationale = parsed.get("rationale") or "Eligibility depends on the verified cause of the disruption."
    result = {"eligible": eligible, "rationale": str(rationale)}
    return {"eligibility": result, "trace": [{"node": "eligibility", **result}]}


def calculator(state: AgentState) -> dict:
    """Call the deterministic, LLM-free `calculate_compensation` tool from `flight_details`.

    Computes the *statutory candidate* amount (eligibility-agnostic). Degrades gracefully: if the
    route can't be resolved (missing/unknown IATA), records an error in `calc_result` instead of
    crashing the run — synthesize handles the missing-amount case.
    """
    details = state.get("flight_details") or {}
    origin, dest = details.get("origin_iata"), details.get("dest_iata")
    if not origin or not dest:
        result = {"error": "Need both origin and destination airports to compute an amount."}
        return {"calc_result": result, "trace": [{"node": "calculator", **result}]}

    try:
        result = calculate_compensation.invoke(
            {
                "origin_iata": origin,
                "dest_iata": dest,
                "delay_hours": float(details.get("delay_hours") or 0),
                "disruption_type": details.get("disruption_type") or "delay",
                "rerouting_offered": bool(details.get("rerouting_offered")),
            }
        )
    except Exception as exc:  # unresolvable airport, bad inputs — keep the run alive
        result = {"error": f"Could not compute compensation: {exc}"}

    trace_step = {"node": "calculator"}
    if "error" in result:
        trace_step["error"] = result["error"]
    else:
        trace_step.update(
            distance_km=result["distance_km"], band=result["band"],
            candidate_eur=result["final_amount_eur"],
        )
    return {"calc_result": result, "trace": [trace_step]}


def synthesize(state: AgentState) -> dict:
    """Fan-in: apply the eligibility gate and compose the grounded final answer.

    Deterministic assembly from already-grounded parts (the RAG answer is itself grounded + cited;
    the calc_result is deterministic) — no extra LLM call, so nothing new can be hallucinated here
    and the numbers/citations stay intact. The gate is the only coupling between the two branches:
    `final = eligible ? candidate : 0`.
    """
    parts: list[str] = []
    rag_answer = state.get("rag_answer", "").strip()
    if rag_answer:
        parts.append(rag_answer)

    calc = state.get("calc_result")
    elig = state.get("eligibility")
    final_eur = None
    gated = False
    if calc is not None:
        if "error" in calc:
            parts.append(f"**Compensation:** {calc['error']}")
        else:
            candidate = calc["final_amount_eur"]
            eligible = elig.get("eligible", True) if elig else True
            final_eur = candidate if eligible else 0
            gated = elig is not None and not eligible
            route = f"{calc['origin_name']} → {calc['dest_name']} ({calc['distance_km']:,.0f} km, {calc['band']})"
            if eligible:
                line = f"**Compensation: €{final_eur}.** {route}."
                if final_eur != candidate:  # (kept for symmetry; equal when eligible)
                    line += f" Statutory amount €{candidate}."
            else:
                line = (
                    f"**Compensation: €0.** {elig['rationale']} "
                    f"You would ordinarily be owed €{candidate} for this {route.split(' (')[0]} route, "
                    "but no cash compensation is due for an extraordinary cause — though the "
                    "right to care and re-routing still applies."
                )
            if not calc["threshold_met"] and calc["disruption_type"] == "delay" and eligible:
                line = (
                    f"**Compensation: €0.** The arrival delay is under the 3-hour threshold, so no "
                    f"cash compensation is due (the statutory band for this {route} would be "
                    f"€{candidate} at 3+ hours). Care/assistance may still apply."
                )
                final_eur = 0
            parts.append(line)
            if elig and eligible:
                parts.append(f"_Eligibility: {elig['rationale']}_")

    final_answer = "\n\n".join(parts) if parts else "I couldn't produce a grounded answer for that."
    return {
        "final_answer": final_answer,
        "trace": [{"node": "synthesize", "final_eur": final_eur, "gated": gated}],
    }


def fallback(state: AgentState) -> dict:
    """Hallucination firewall — honest decline for out-of-scope questions (no LLM guess)."""
    msg = (
        "I can only help with **EU air passenger rights under Regulation (EC) No 261/2004** "
        "— flight delays, cancellations, denied boarding, and the compensation they trigger. "
        "Your question looks like it's outside that scope (e.g. baggage fees, pets, visas, or "
        "ticket pricing), so I can't answer it reliably. Try rephrasing it around a flight "
        "disruption and your rights."
    )
    return {"final_answer": msg, "trace": [{"node": "fallback"}]}


# ----------------------------------------------------------------------------- wiring

def _route_after_extract(state: AgentState):
    """The dispatch after extract. Returns node name(s); a list fans out."""
    qt = state["classification"]["query_type"]
    if qt == "out_of_scope":
        return "fallback"
    if qt == "rights_info":
        return "rag"
    return ["rag", "calculator"]  # compensation_calc / mixed → fan-out


def _route_after_rag(state: AgentState) -> str:
    """rights_info answers straight from RAG; the comp/mixed paths feed eligibility."""
    return "synthesize" if state["classification"]["query_type"] == "rights_info" else "eligibility"


def build_agent_graph():
    """Build and compile the main agent graph."""
    g = StateGraph(AgentState)
    g.add_node("classify", classify)
    g.add_node("extract", extract)
    g.add_node("rag", rag)
    g.add_node("eligibility", eligibility)
    g.add_node("calculator", calculator)
    # Deferred so the fan-in waits for BOTH branches despite their different lengths.
    g.add_node("synthesize", synthesize, defer=True)
    g.add_node("fallback", fallback)

    g.add_edge(START, "classify")
    g.add_edge("classify", "extract")
    g.add_conditional_edges("extract", _route_after_extract, ["fallback", "rag", "calculator"])
    g.add_conditional_edges("rag", _route_after_rag, ["synthesize", "eligibility"])
    g.add_edge("eligibility", "synthesize")
    g.add_edge("calculator", "synthesize")
    g.add_edge("synthesize", END)
    g.add_edge("fallback", END)
    return g.compile()


# Compiled once for import by the UI.
agent_graph = build_agent_graph()


def run_agent(user_query: str) -> AgentState:
    """Convenience wrapper: run the full graph for a query and return the final state."""
    return agent_graph.invoke({"user_query": user_query, "trace": []})


if __name__ == "__main__":
    import sys

    q = " ".join(sys.argv[1:]) or (
        "My Paris to Rome flight was cancelled due to an airline staff strike and I got in "
        "6 hours late — am I entitled to anything, and how much?"
    )
    final = run_agent(q)
    print(f"\nQ: {q}\n")
    print(f"query_type: {final.get('classification', {}).get('query_type')}")
    print(f"trace: {[s['node'] for s in final.get('trace', [])]}\n")
    print(final.get("final_answer", "(no answer)"))
