"""Functional eval — run the agent over `eval/eval_set.yaml` and score it.

This is the project's primary functional test (CLAUDE.md: functional over unit tests). It
drives the *real* compiled graph via `run_agent()` — the same `.invoke()` path the UI's
Agent tab uses — so a passing eval means the assembled agent behaves, end to end.

What it scores, per case (only the dimensions the case pins):
  - **routing**   — `query_type` matches (anchored to Reg. 261/2004 correctness)
  - **eligibility** — the `eligible` verdict matches (extraordinary-circumstances gate)
  - **amount**    — the GATED final euro figure matches (synthesize's `final_eur`)
  - **citations** — presence (guardrail) and, where pinned, `any_of` correctness
                    (normalized source + optional article/section, set-membership)

`known_fail` cases (the two 3B limitations from Phase 5 spot-checks) are scored like any
other but reported separately, so the baseline distinguishes a *known gap* from a *new
regression*. See `notes/EVAL_CITATION_SCORING.md` for the citation-scoring design.

Run:  python -m eval.functional_eval [--json PATH] [--id CASE_ID ...]
"""

from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import yaml

from src.graph import run_agent

EVAL_SET = Path(__file__).with_name("eval_set.yaml")
DEFAULT_JSON = Path(__file__).with_name("last_run.json")

# Dimensions in a stable display order.
DIMENSIONS = ["routing", "eligibility", "amount", "cite_present", "cite_correct"]


# ----------------------------------------------------------------- extraction helpers

def _final_amount(state: dict) -> int | None:
    """The gated final euro amount — synthesize records it as `final_eur` in the trace.

    None when the run never reached synthesize (out_of_scope → fallback) or produced no
    amount (a pure rights_info answer). That's distinct from an amount of 0 (a real gated
    or sub-threshold result), so amount scoring only fires on cases that pin `amount_eur`.
    """
    for step in reversed(state.get("trace", [])):
        if step.get("node") == "synthesize":
            return step.get("final_eur")
    return None


def _norm_source(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _article_key(s: str) -> str:
    """Reduce an article/section label to a comparable token.

    'Art. 8' -> '8'; 'Section 4.3.3' -> '4.3.3'; 'Recital 12' -> '12'; topical labels
    ('Compensation') -> 'compensation'. Label-tolerant so a cosmetic fix (e.g. the OJ-notice
    em-dash leak) doesn't fail a semantically-correct citation.
    """
    s = (s or "").strip().lower()
    s = re.sub(r"\b(art\.?|article|section|sect\.?|recital|rec\.?)\b", "", s)
    s = s.strip(" .:-—–()")
    s = re.sub(r"\s*\(\d+/\d+\)$", "", s)  # drop split markers like '(1/2)'
    return re.sub(r"\s+", " ", s).strip()


def _citation_matches(produced: list[dict], any_of: list[dict]) -> bool:
    """True if ≥1 produced citation is in the `any_of` set (recall, not exact equality).

    A produced citation matches an entry when the normalized source is equal AND (the entry
    pins no article, OR the entry's article-key matches the produced one — either contains
    the other, to tolerate 'Art. 7' vs 'Art. 7(1)' style differences).
    """
    for want in any_of:
        want_src = _norm_source(want.get("source", ""))
        want_art = _article_key(want.get("article", "")) if want.get("article") else None
        for c in produced:
            if _norm_source(c.get("source", "")) != want_src:
                continue
            if want_art is None:
                return True
            got_art = _article_key(c.get("article", ""))
            if got_art == want_art or (want_art and (want_art in got_art or got_art in want_art)):
                return True
    return False


# ----------------------------------------------------------------------- scoring

def score_case(case: dict) -> dict:
    """Run one case through the agent and score every dimension it pins."""
    expect = case.get("expect", {})
    t0 = time.perf_counter()
    state = run_agent(case["query"])
    elapsed = time.perf_counter() - t0

    actual = {
        "query_type": state.get("query_type"),
        "eligible": (state.get("eligibility") or {}).get("eligible"),
        "amount_eur": _final_amount(state),
        "citations": state.get("rag_citations", []) or [],
    }

    results: dict[str, bool | None] = {d: None for d in DIMENSIONS}

    # routing — always pinned.
    results["routing"] = actual["query_type"] == expect.get("query_type")

    # eligibility / amount — only when the case pins them.
    if "eligible" in expect:
        results["eligibility"] = actual["eligible"] == expect["eligible"]
    if "amount_eur" in expect:
        results["amount"] = actual["amount_eur"] == expect["amount_eur"]

    # citations — presence and/or correctness, gated by `required`.
    cit = expect.get("citations", {}) or {}
    if cit.get("required"):
        results["cite_present"] = len(actual["citations"]) > 0
    if cit.get("any_of"):
        results["cite_correct"] = _citation_matches(actual["citations"], cit["any_of"])

    scored = {d: v for d, v in results.items() if v is not None}
    known = case.get("known_fail") or {}
    known_dims = set(known.get("dimensions", []))
    # Map the case-level known-fail dims onto our dimension keys.
    known_keys = set()
    for d in known_dims:
        if d == "routing":
            known_keys.add("routing")
        elif d == "eligibility":
            known_keys.add("eligibility")
        elif d == "amount":
            known_keys.add("amount")

    return {
        "id": case["id"],
        "category": case.get("category"),
        "query": case["query"].strip(),
        "expect": expect,
        "actual": actual,
        "results": scored,
        "passed": all(scored.values()) if scored else True,
        "known_fail": known,
        "known_keys": sorted(known_keys),
        "elapsed_s": round(elapsed, 2),
    }


# ----------------------------------------------------------------------- reporting

_MARK = {True: "✅", False: "❌", None: "·"}


def _fmt_actual(c: dict) -> str:
    a = c["actual"]
    bits = [str(a["query_type"])]
    if a["eligible"] is not None:
        bits.append(f"elig={a['eligible']}")
    if a["amount_eur"] is not None:
        bits.append(f"€{a['amount_eur']}")
    bits.append(f"cites={len(a['citations'])}")
    return " ".join(bits)


def report(cases: list[dict]) -> dict:
    print("\n" + "=" * 78)
    print("FUNCTIONAL EVAL — eval/eval_set.yaml")
    print("=" * 78)

    header = f"{'id':<24} {'route':<5} {'elig':<5} {'amt':<5} {'c?':<3} {'c✓':<3}  {'sec':>5}"
    print(header)
    print("-" * 78)

    dim_tally = {d: [0, 0] for d in DIMENSIONS}  # [passed, total] excluding known-fails
    known_as_expected = 0
    known_total = 0
    surprises: list[str] = []

    for c in cases:
        r = c["results"]
        row = (
            f"{c['id']:<24} "
            f"{_MARK.get(r.get('routing')):<2}   "
            f"{_MARK.get(r.get('eligibility')):<2}   "
            f"{_MARK.get(r.get('amount')):<2}   "
            f"{_MARK.get(r.get('cite_present')):<1}  "
            f"{_MARK.get(r.get('cite_correct')):<1}  "
            f"{c['elapsed_s']:>5.1f}"
        )
        tag = ""
        if c["known_fail"]:
            tag = f"  🔖 {c['known_fail'].get('ref', 'known')}"
        print(row + tag)

        for d, passed in r.items():
            is_known = d in c["known_keys"]
            if is_known:
                known_total += 1
                if not passed:
                    known_as_expected += 1
                else:
                    surprises.append(f"{c['id']}:{d} unexpectedly PASSED (known-fail)")
                continue
            dim_tally[d][1] += 1
            if passed:
                dim_tally[d][0] += 1

    print("-" * 78)

    # Per-dimension accuracy (excluding known-fails).
    print("\nPer-dimension accuracy (excluding known-fails):")
    for d in DIMENSIONS:
        p, t = dim_tally[d]
        if t:
            print(f"  {d:<14} {p}/{t}  ({100*p/t:.0f}%)")

    # Per-category pass rate.
    cats: dict[str, list[int]] = {}
    for c in cases:
        if c["known_fail"]:
            continue
        cats.setdefault(c["category"], [0, 0])
        cats[c["category"]][1] += 1
        if c["passed"]:
            cats[c["category"]][0] += 1
    print("\nPer-category case pass rate (excluding known-fails):")
    for cat, (p, t) in sorted(cats.items()):
        print(f"  {cat:<20} {p}/{t}")

    # Headline numbers.
    scored_cases = [c for c in cases if not c["known_fail"]]
    passed_cases = sum(1 for c in scored_cases if c["passed"])
    print("\n" + "=" * 78)
    print(f"OVERALL (excluding known-fails):  {passed_cases}/{len(scored_cases)} cases fully pass")
    print(
        f"KNOWN-FAILS:                      {known_as_expected}/{known_total} dimensions failed as documented"
    )
    if surprises:
        print("  ⚠️  Surprises (known-fail now passing — update the eval set?):")
        for s in surprises:
            print(f"      - {s}")
    total_s = sum(c["elapsed_s"] for c in cases)
    print(f"WALL TIME:                        {total_s:.1f}s for {len(cases)} cases "
          f"(avg {total_s/len(cases):.1f}s/case)")
    print("=" * 78 + "\n")

    return {
        "n_cases": len(cases),
        "passed_excl_known": passed_cases,
        "scored_excl_known": len(scored_cases),
        "known_dims_failed_as_expected": known_as_expected,
        "known_dims_total": known_total,
        "surprises": surprises,
        "dim_tally": dim_tally,
        "wall_time_s": round(total_s, 1),
    }


# ----------------------------------------------------------------------- entrypoint

def main() -> None:
    ap = argparse.ArgumentParser(description="Functional eval over eval/eval_set.yaml")
    ap.add_argument("--json", type=Path, default=DEFAULT_JSON, help="where to write the JSON result")
    ap.add_argument("--id", action="append", help="run only these case id(s)")
    args = ap.parse_args()

    cases_spec = yaml.safe_load(EVAL_SET.read_text())
    if args.id:
        wanted = set(args.id)
        cases_spec = [c for c in cases_spec if c["id"] in wanted]
        if not cases_spec:
            raise SystemExit(f"No cases matched --id {args.id}")

    print(f"Running {len(cases_spec)} case(s) through the agent graph…")
    scored = [score_case(c) for c in cases_spec]
    summary = report(scored)

    args.json.write_text(json.dumps({"summary": summary, "cases": scored}, indent=2, ensure_ascii=False))
    print(f"Wrote detailed results → {args.json}")


if __name__ == "__main__":
    main()
