# Repository cleanup plan

Pre-submission pruning of implementation-scaffolding docs. Goal: keep the repo to the
**product** (README + code + corpus + attribution) plus a small set of curated reference
notes, and drop the phased-build process residue. All deletions are git-reversible; no code
or config is touched except the noted reference fixes.

**Status: planned — not yet executed.**

---

## Guiding principle

The `README.md` + code + corpus + `SOURCES.md` is the *product*; everything else is *process
evidence*. The detailed README — which already carries a "justification of design decisions"
section and per-component trade-off callouts — compensates for the deleted rationale docs.
Phasing history is preserved in git.

---

## `/` (root)

| File | Action | Detail |
|------|--------|--------|
| `README.md` | **KEEP** | The deliverable. Unchanged. |
| `CLAUDE.md` | **REWRITE** | Strip the phased-build machinery (document map, per-phase working agreement, git-workflow-per-phase) and all references to `PLAN`/`DECISIONS`/`PROJECT_PROPOSAL`. Keep a general operational guide: what the project is, non-negotiables, tech stack, commands, architecture quick-reference, conventions. |
| `DECISIONS.md` | **DELETE** | The README's design-decisions section + trade-off callouts carry the rationale for the final design; git history holds the rest. |
| `PLAN.md` | **DELETE** | Phasing/status lives in git history. |

## `data/`

| File | Action | Detail |
|------|--------|--------|
| `data/SOURCES.md` | **KEEP** | Legal attribution (ODbL / EUR-Lex); the only doc the README links to. |
| `data/corpus/plain_language_summary.md` | **KEEP** | Corpus *content* the RAG ingests — not a doc. |

## `notes/` (directory survives, slimmed 7 → 3 files)

| File | Action | Detail |
|------|--------|--------|
| `EVAL_CITATION_SCORING.md` | **KEEP** (+ ref-fix) | Retarget its one pointer to `PHASE5_REVIEW_FINDINGS.md` → the new improvements doc. Optionally de-phase the title/intro prose. |
| `PHASE6_EVAL_RESULTS.md` | **RENAME → `EVAL_RESULTS.md`** | Drop the phase prefix. Neutralize the now-dangling inline `DECISIONS …` tags (they point at the deleted log) by converting them to plain prose. |
| `PHASE5_REVIEW_FINDINGS.md` | **DISTILL → new file, then DELETE** | Source for the new `FUTURE_IMPROVEMENTS.md`; original removed afterward. |
| `PROJECT_PROPOSAL.md` | **DELETE** | README compensates. |
| `PHASE7_IMPLEMENTATION_PLAN.md` | **DELETE** | Process residue. |
| `README_BLOAT_CHECKLIST.md` | **DELETE** | Process residue. |
| `TASK_DESCRIPTION.md` | **DELETE** | The interview prompt — not shipped back. |
| **`FUTURE_IMPROVEMENTS.md`** | **NEW** | Forward-looking only, distilled from Phase 5's findings + parking lot: structured-output intake for routing accuracy; teach the two blind spots (ATC-not-extraordinary, EU-scope-asymmetry); conditional RAG to make calc-only queries faster; add Reg. (EC) 889/2002 (baggage) + broaden scope; RAG multi-hop reference-following; long-haul >3500 km 3–4 h 50% nuance; delay-only robustness. Each item cross-checked against current code so the doc lists only genuinely-open items + known limitations — not anything already fixed in later phases. |

## Cross-cutting reference fixes

- `eval/functional_eval.py:16` → **no change** — it points to `EVAL_CITATION_SCORING.md`, which is kept.
- `EVAL_CITATION_SCORING.md` → retarget its `PHASE5_REVIEW_FINDINGS.md` reference to the new doc.
- `EVAL_RESULTS.md` (renamed) → strip dangling `DECISIONS`/phase inline tags.
- `CLAUDE.md` (rewritten) → contains no references to deleted docs.
- **Verify (read-only) before deleting:** `README.md` has no prose reference to `DECISIONS`/`PLAN`/`PROJECT_PROPOSAL` (earlier scan shows it only links `data/SOURCES.md`).

## Net result

- `notes/` goes from **7 files → 3**: `EVAL_CITATION_SCORING.md`, `EVAL_RESULTS.md`, `FUTURE_IMPROVEMENTS.md`.
- Root loses `DECISIONS.md` + `PLAN.md`.
- `CLAUDE.md` becomes a general operational guide.
- No code or config touched beyond the reference fixes above. All deletions are git-reversible.
