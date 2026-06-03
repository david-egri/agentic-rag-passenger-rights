"""The main agent graph — the 7-node directed agent that ties P1–P3 together.

Topology (matches §4.3 of the proposal exactly):

    START → intake → router ─┬─ out_of_scope ──→ fallback → END
                             ├─ rights_info ───→ rag ───────────────────→ synthesize → END
                             ├─ compensation_calc → [rag, calculator]  (fan-out)
                             └─ mixed → planner → [rag, calculator]     (fan-out)

        rag → (rights_info? → synthesize : → eligibility)
        eligibility → synthesize        calculator → synthesize         (fan-in)

The seven main nodes are **intake, router, planner, eligibility, calculator, synthesize,
fallback** (≥5 required). The corrective-RAG **subgraph** is reused in both the
`rights_info` path and the eligibility branch via a single shared `rag` node, and does NOT
count toward the seven (CLAUDE.md guardrail #3) — the `rag` node *invokes the compiled
`rag_graph`*, it does not reimplement it.

`compensation_calc` and `mixed` are a real **fan-out → fan-in**: the eligibility branch
(rag → eligibility) and the calculator branch run as independent siblings and converge at
`synthesize`. The only coupling is the gate applied there: `final = eligible ? candidate
: 0` — the calculator never waits on eligibility (DECISIONS: calculator is
eligibility-agnostic). `synthesize` is a **deferred** node so it waits for *both* branches
even though they are different lengths (the calculator branch is one hop, the eligibility
branch two) — LangGraph would otherwise fire it twice.

Every node appends a step to `state["trace"]` (append-only reducer) so the Streamlit Agent
tab can render the run node-by-node.
"""

from __future__ import annotations

import json

from langchain_core.messages import HumanMessage, SystemMessage

from src.calculator import DISRUPTION_TYPES
from src.llm import get_llm
from src.rag import rag_graph
from src.state import AgentState
from src.tools import calculate_compensation

# ---------------------------------------------------------------------------- helpers

def _parse_json(text: str) -> dict:
    """Best-effort JSON extraction from a small model's reply.

    qwen2.5:3b usually returns clean JSON but sometimes wraps it in ```json fences or adds
    a sentence. Strip fences, then fall back to slicing the outermost braces. Returns {} on
    failure so callers can apply defaults rather than crash.
    """
    t = text.strip()
    if t.startswith("```"):
        t = t.split("```", 2)[1] if "```" in t[3:] else t
        t = t.removeprefix("json").removeprefix("JSON").strip()
        t = t.split("```")[0].strip()
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        start, end = t.find("{"), t.rfind("}")
        if 0 <= start < end:
            try:
                return json.loads(t[start : end + 1])
            except (json.JSONDecodeError, ValueError):
                return {}
        return {}


def _docs_context(docs: list[dict], n: int = 4, max_chars: int = 600) -> str:
    """Number the top retrieved chunks (truncated) as grounding context for a prompt."""
    lines = []
    for i, d in enumerate(docs[:n], 1):
        m = d["metadata"]
        lines.append(f"[{i}] ({m['source']} · {m['article']})\n{d['text'][:max_chars]}")
    return "\n\n".join(lines) if lines else "(no passages retrieved)"


# ------------------------------------------------------------------------------- nodes

def intake(state: AgentState) -> dict:
    """Extract flight entities and classify intent — one structured-JSON LLM call.

    Writes `flight_details` and `query_type`. Tolerant of missing fields: a general rights
    question carries no flight, an out-of-scope question carries neither.
    """
    query = state["user_query"]
    prompt = (
        f'User message: "{query}"\n\n'
        "You are the intake step of an EU air-passenger-rights assistant (Regulation (EC) "
        "No 261/2004), which covers ONLY flight delays, cancellations, denied boarding, and "
        "the compensation/care they trigger. Do two things and return JSON only:\n"
        "1. Classify `query_type` as exactly one of:\n"
        '   - "rights_info": asks about rights/rules for a disruption in general, no specific '
        "amount needed.\n"
        '   - "compensation_calc": asks HOW MUCH money for a specific disrupted flight, '
        "without also asking to explain the rights.\n"
        '   - "mixed": asks BOTH what they are entitled to / their rights AND how much money.\n'
        '   - "out_of_scope": NOT about a flight disruption under Reg. 261 — e.g. baggage '
        "fees, pets, seat selection, visas, ticket pricing, refunds for voluntary changes, "
        "non-flight topics. Out-of-scope EVEN IF it mentions a flight or asks 'how much'.\n"
        "Examples: 'What are my rights if my flight is cancelled?' → rights_info. "
        "'My BUD→LHR flight was 4h late, how much do I get?' → compensation_calc. "
        "'My flight was cancelled for a strike — am I entitled to anything and how much?' → "
        "mixed. 'How much to bring a dog on the plane?' → out_of_scope.\n"
        "2. Extract `flight_details` when present (else null fields): origin_iata, dest_iata "
        "(3-letter IATA codes; infer from city names if obvious, else null), delay_hours "
        "(number, arrival delay), disruption_type (one of "
        f"{DISRUPTION_TYPES}), reason (the stated cause of disruption, e.g. \"weather\", "
        '"airline staff strike", or null), rerouting_offered (true/false/null).\n\n'
        'Return ONLY JSON: {"query_type": "...", "flight_details": {"origin_iata": ..., '
        '"dest_iata": ..., "delay_hours": ..., "disruption_type": ..., "reason": ..., '
        '"rerouting_offered": ...}}'
    )
    reply = get_llm().invoke(
        [
            SystemMessage(content="You extract structured data and return JSON only — no prose, no fences."),
            HumanMessage(content=prompt),
        ]
    ).content
    parsed = _parse_json(reply)

    query_type = parsed.get("query_type")
    if query_type not in ("rights_info", "compensation_calc", "mixed", "out_of_scope"):
        query_type = "rights_info"  # safest default: ground an answer rather than decline
    details = parsed.get("flight_details") or {}
    if not isinstance(details, dict):
        details = {}
    # Normalise IATA codes that did come through.
    for k in ("origin_iata", "dest_iata"):
        if isinstance(details.get(k), str):
            details[k] = details[k].strip().upper() or None

    return {
        "query_type": query_type,
        "flight_details": details,
        "trace": [{"node": "intake", "query_type": query_type, "flight_details": details}],
    }


def router(state: AgentState) -> dict:
    """Explicit routing node — records the decision in the trace (the conditional edge that
    actually dispatches reads `query_type`). A node, not a bare conditional edge, so the
    routing choice is visible in the Agent tab (CLAUDE.md guardrail #5)."""
    qt = state["query_type"]
    return {"trace": [{"node": "router", "route": qt}]}


def planner(state: AgentState) -> dict:
    """Decompose a `mixed` query into subtasks — the LLM emits them (not a hardcoded split).

    The subtasks are recorded for the trace; the actual independent execution is the
    fan-out to the rag and calculator branches wired after this node.
    """
    prompt = (
        f'User question: "{state["user_query"]}"\n\n'
        "This question needs BOTH a rights explanation and a compensation amount. Break it "
        "into 2-4 concrete subtasks an assistant would carry out. Return ONLY a JSON array "
        'of short strings, e.g. ["Determine if the disruption is compensable", "Compute the '
        'compensation amount for the route and delay", "Explain the passenger\'s rights"].'
    )
    reply = get_llm().invoke(
        [
            SystemMessage(content="You decompose a task into subtasks and return a JSON array of strings only."),
            HumanMessage(content=prompt),
        ]
    ).content
    parsed = _parse_json(reply if reply.strip().startswith("{") else f'{{"subtasks": {reply.strip()}}}')
    subtasks = parsed.get("subtasks") if isinstance(parsed, dict) else None
    if not isinstance(subtasks, list) or not subtasks:
        # Fallback decomposition keeps the trace meaningful if the small model misbehaves.
        subtasks = [
            "Determine whether the disruption is compensable (extraordinary circumstances?)",
            "Compute the statutory compensation amount for the route and delay",
            "Explain the passenger's rights and combine into one answer",
        ]
    subtasks = [str(s) for s in subtasks][:4]
    return {"subtasks": subtasks, "trace": [{"node": "planner", "subtasks": subtasks}]}


def rag(state: AgentState) -> dict:
    """Invoke the compiled corrective-RAG **subgraph** and map its result into AgentState.

    This is the subgraph attached as a node (CLAUDE.md guardrail #3): it calls
    `rag_graph.invoke`, it does not reimplement retrieval. Schemas differ (RAGState vs
    AgentState), so the mapping happens here at the boundary — the documented LangGraph
    pattern for a different-schema subgraph. The retrieved docs feed the eligibility node
    (in the eligibility branch); the answer/citations feed synthesize.
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

    Combines the extracted `reason` with the retrieved rules (the rag node runs first in
    this branch) and the well-known EU261 carve-outs. Sets `eligibility {eligible,
    rationale}`. Eligibility-agnostic of the amount — the gate is applied at synthesize.
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
    prompt = (
        f"Cause of the flight disruption: \"{reason}\"\n\n"
        f"Relevant retrieved rules:\n{context}\n\n"
        "Decide whether cash compensation under Art. 7 is in principle owed. The test: was "
        "the cause WITHIN the airline's own control, or an EXTRAORDINARY circumstance beyond "
        "it?\n"
        "- WITHIN the carrier's control → compensation IS owed (eligible = true): the "
        "airline's OWN staff/crew strike, technical or operational problems, routine "
        "maintenance, overbooking.\n"
        "- EXTRAORDINARY, beyond control → NO cash compensation (eligible = false), though "
        "care/re-routing still apply: bad weather, air-traffic-control restrictions, security "
        "risks, political instability, and strikes by THIRD PARTIES (e.g. airport staff, "
        "ATC), not the airline's own staff.\n"
        "Worked examples: \"strike by the airline's own cabin crew\" → eligible = true (own "
        "staff, within control). \"snowstorm\" → eligible = false. \"air traffic control "
        "strike\" → eligible = false (third party).\n\n"
        'Return ONLY JSON: {"eligible": true/false, "rationale": "one sentence naming the '
        'cause and whether it was within the carrier\'s control"}'
    )
    reply = get_llm().invoke(
        [
            SystemMessage(
                content="You judge EU261 compensation eligibility by whether the cause was within "
                "the airline's control. Return JSON only."
            ),
            HumanMessage(content=prompt),
        ]
    ).content
    parsed = _parse_json(reply)
    eligible = parsed.get("eligible")
    if not isinstance(eligible, bool):
        eligible = True  # default to owed-in-principle; synthesize still gates on the calc
    rationale = parsed.get("rationale") or "Eligibility depends on the verified cause of the disruption."
    result = {"eligible": eligible, "rationale": str(rationale)}
    return {"eligibility": result, "trace": [{"node": "eligibility", **result}]}


def calculator(state: AgentState) -> dict:
    """Call the deterministic, LLM-free `calculate_compensation` tool from `flight_details`.

    Computes the *statutory candidate* amount (eligibility-agnostic). Degrades gracefully:
    if the route can't be resolved (missing/unknown IATA), records an error in `calc_result`
    instead of crashing the run — synthesize handles the missing-amount case.
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

    Deterministic assembly from already-grounded parts (the RAG answer is itself grounded +
    cited; the calc_result is deterministic) — no extra LLM call, so nothing new can be
    hallucinated here and the numbers/citations stay intact. The gate is the only coupling
    between the two branches: `final = eligible ? candidate : 0`.
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

def _route_from_router(state: AgentState):
    """The 4-way dispatch after the router node. Returns node name(s); a list fans out."""
    qt = state["query_type"]
    if qt == "out_of_scope":
        return "fallback"
    if qt == "rights_info":
        return "rag"
    if qt == "mixed":
        return "planner"
    return ["rag", "calculator"]  # compensation_calc → fan-out


def _route_after_rag(state: AgentState) -> str:
    """rights_info answers straight from RAG; the comp/mixed paths feed eligibility."""
    return "synthesize" if state["query_type"] == "rights_info" else "eligibility"


def build_agent_graph():
    """Build and compile the main agent graph."""
    from langgraph.graph import END, START, StateGraph

    g = StateGraph(AgentState)
    g.add_node("intake", intake)
    g.add_node("router", router)
    g.add_node("planner", planner)
    g.add_node("rag", rag)
    g.add_node("eligibility", eligibility)
    g.add_node("calculator", calculator)
    # Deferred so the fan-in waits for BOTH branches despite their different lengths.
    g.add_node("synthesize", synthesize, defer=True)
    g.add_node("fallback", fallback)

    g.add_edge(START, "intake")
    g.add_edge("intake", "router")
    g.add_conditional_edges("router", _route_from_router, ["fallback", "rag", "planner", "calculator"])
    g.add_edge("planner", "rag")        # fan-out branch 1 (→ eligibility after rag)
    g.add_edge("planner", "calculator")  # fan-out branch 2 (independent)
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
    print(f"query_type: {final.get('query_type')}")
    print(f"trace: {[s['node'] for s in final.get('trace', [])]}\n")
    print(final.get("final_answer", "(no answer)"))
