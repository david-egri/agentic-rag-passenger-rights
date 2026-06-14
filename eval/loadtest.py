"""Load test — run N queries through the agent and attribute the latency bottleneck.

Goal (CLAUDE.md): push 50–200 queries through the graph, measure end-to-end latency, and
**attribute the bottleneck via per-node timing** — is it local-LLM generation, or the
retrieval/calculator/assembly around it?

Timing is collected with LangGraph's `stream_mode="debug"` (paired `task` / `task_result`
events carry per-node timestamps), layered *alongside* the semantic `trace` rather than
stuffed into it — the `TRACE-VS-TIMING` decision (DECISIONS `trace-in-state`). The semantic
trace stays a presentation artifact; this module owns performance numbers.

The query pool is the 15-case eval set, cycled round-robin to N so the route mix is balanced
and the run is reproducible (no randomness). Runs are sequential and single-threaded: a single
local Ollama serializes generation on the model, so concurrency would only queue requests and
muddy per-node attribution — the bottleneck question is about *where the time goes per run*.

Run:  python -m eval.loadtest [--n 50] [--json PATH]
"""

from __future__ import annotations

import argparse
import json
import statistics
import time
from datetime import datetime
from pathlib import Path

import yaml

from src.graph import agent_graph

EVAL_SET = Path(__file__).with_name("eval_set.yaml")
DEFAULT_JSON = Path(__file__).with_name("loadtest_last.json")

# Which main-graph nodes call the LLM (for the bottleneck split). `rights` wraps the whole
# corrective-RAG subgraph (retrieve + LLM grade + LLM generate, maybe a rewrite loop), so its
# time is LLM-dominated. `eligibility` is LLM only when a cause is stated (vector retrieval + an
# LLM judgment; no-cause is a deterministic shortcut). calculator/synthesize/fallback are LLM-free.
LLM_NODES = {"classify", "extract", "rights", "eligibility"}


def _load_pool() -> list[str]:
    cases = yaml.safe_load(EVAL_SET.read_text())
    return [c["query"].strip() for c in cases]


def _run_once(query: str) -> tuple[float, dict[str, float]]:
    """Run one query via the debug stream; return (total_seconds, {node: seconds})."""
    starts: dict[str, datetime] = {}      # task id -> start timestamp
    names: dict[str, str] = {}            # task id -> node name
    node_times: dict[str, float] = {}     # node name -> summed seconds (this run)

    t0 = time.perf_counter()
    for ev in agent_graph.stream({"user_query": query, "trace": []}, stream_mode="debug"):
        etype = ev.get("type")
        if etype not in ("task", "task_result"):
            continue
        payload = ev.get("payload", {})
        tid = payload.get("id")
        ts = datetime.fromisoformat(ev["timestamp"])
        if etype == "task":
            starts[tid] = ts
            names[tid] = payload.get("name")
        else:  # task_result — pair with its start
            start = starts.get(tid)
            if start is not None:
                name = names.get(tid, "?")
                node_times[name] = node_times.get(name, 0.0) + (ts - start).total_seconds()
    total = time.perf_counter() - t0
    return total, node_times


def run_loadtest(n: int) -> dict:
    pool = _load_pool()
    print(f"Load test: {n} queries (pool of {len(pool)}, round-robin), sequential…\n")

    totals: list[float] = []
    per_node_runs: dict[str, list[float]] = {}
    wall0 = time.perf_counter()

    for i in range(n):
        query = pool[i % len(pool)]
        total, node_times = _run_once(query)
        totals.append(total)
        for node, secs in node_times.items():
            per_node_runs.setdefault(node, []).append(secs)
        # flush=True so progress is visible live even when stdout is redirected to a file
        # (block-buffered otherwise — none of the lines would appear until the run ended).
        print(f"  [{i+1:>3}/{n}] {total:5.1f}s  {query[:58]}", flush=True)
    wall = time.perf_counter() - wall0

    return _summarize(totals, per_node_runs, wall, n)


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = max(0, min(len(s) - 1, int(round((p / 100) * (len(s) - 1)))))
    return s[k]


def _summarize(totals: list[float], per_node_runs: dict[str, list[float]], wall: float, n: int) -> dict:
    grand_total_node = sum(sum(v) for v in per_node_runs.values())
    node_rows = []
    for node, runs in per_node_runs.items():
        tot = sum(runs)
        node_rows.append({
            "node": node,
            "calls": len(runs),
            "total_s": round(tot, 2),
            "mean_s": round(tot / len(runs), 3),
            "share_pct": round(100 * tot / grand_total_node, 1) if grand_total_node else 0.0,
            "is_llm": node in LLM_NODES,
        })
    node_rows.sort(key=lambda r: r["total_s"], reverse=True)

    llm_total = sum(r["total_s"] for r in node_rows if r["is_llm"])
    nonllm_total = sum(r["total_s"] for r in node_rows if not r["is_llm"])

    return {
        "n": n,
        "wall_s": round(wall, 1),
        "throughput_qps": round(n / wall, 3) if wall else 0.0,
        "latency_s": {
            "mean": round(statistics.mean(totals), 2),
            "p50": round(_pct(totals, 50), 2),
            "p90": round(_pct(totals, 90), 2),
            "p95": round(_pct(totals, 95), 2),
            "max": round(max(totals), 2),
            "min": round(min(totals), 2),
        },
        "node_breakdown": node_rows,
        "llm_vs_rest": {
            "llm_total_s": round(llm_total, 2),
            "nonllm_total_s": round(nonllm_total, 2),
            "llm_share_pct": round(100 * llm_total / (llm_total + nonllm_total), 1) if (llm_total + nonllm_total) else 0.0,
        },
    }


def report(s: dict) -> None:
    print("\n" + "=" * 78)
    print(f"LOAD TEST — {s['n']} queries")
    print("=" * 78)
    lat = s["latency_s"]
    print(f"Wall time:   {s['wall_s']}s   throughput: {s['throughput_qps']} q/s")
    print(f"Latency (s): mean {lat['mean']}  p50 {lat['p50']}  p90 {lat['p90']}  "
          f"p95 {lat['p95']}  max {lat['max']}  min {lat['min']}")

    print("\nPer-node timing (summed across all runs):")
    print(f"  {'node':<14} {'kind':<5} {'calls':>6} {'total_s':>9} {'mean_s':>8} {'share':>7}")
    print("  " + "-" * 56)
    for r in s["node_breakdown"]:
        kind = "LLM" if r["is_llm"] else "·"
        print(f"  {r['node']:<14} {kind:<5} {r['calls']:>6} {r['total_s']:>9} "
              f"{r['mean_s']:>8} {r['share_pct']:>6}%")

    lv = s["llm_vs_rest"]
    print("\nBottleneck split:")
    print(f"  LLM nodes:     {lv['llm_total_s']}s  ({lv['llm_share_pct']}% of node time)")
    print(f"  Everything else: {lv['nonllm_total_s']}s  ({round(100-lv['llm_share_pct'],1)}%)")
    print("=" * 78 + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Load test the agent graph (per-node timing)")
    ap.add_argument("--n", type=int, default=50, help="number of queries (brief: 50–200)")
    ap.add_argument("--json", type=Path, default=DEFAULT_JSON, help="where to write the JSON result")
    args = ap.parse_args()

    summary = run_loadtest(args.n)
    report(summary)
    args.json.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"Wrote load-test results → {args.json}")


if __name__ == "__main__":
    main()
