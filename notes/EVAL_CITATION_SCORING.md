# Citation scoring for the Phase 6 functional eval

How the eval set should assert on **citations** — written during the Phase 5 review so the
Phase 6 eval set (`eval/eval_set.yaml`) and runner are built with this baked in. Motivated by
the sequencing realization that most eval ground truth is design-independent, but the
**citation-level** ground truth couples to the corpus (see `notes/PHASE5_REVIEW_FINDINGS.md`,
Group A).

---

## What "citation-level ground truth" is

A rights answer in this project must carry **citations**, and citations **reference chunk
metadata, never raw chunk text** (CLAUDE.md). Each chunk is tagged at ingestion with
`source`, `article`/`section`, `title`, `url`, `chunk_id`. A citation is therefore a
**structured pointer into the corpus** — e.g. *"Reg (EC) 261/2004, Art. 7"* — and
citation-level ground truth is the eval's assertion about **which source/article an answer
should cite**, distinct from whether it routed correctly or computed the right amount.

## Three scoring dimensions — only two couple to the corpus

Separate these, because they don't ripple into the corpus equally:

| Dimension | What it checks | Corpus-coupled? | When to write |
|---|---|---|---|
| **Presence** | Every rights/interpretive answer carries ≥1 citation | **No** — a guardrail (non-neg #3), true regardless of corpus | **Now** (baseline) |
| **Correctness** | The answer cites the *right* source/article (e.g. Art. 7) | **Yes** — "right article" only exists if a chunk with that metadata is in the store | **After the corpus pass** |
| **Grounding** | The cited passage actually supports the claim | **Yes** — depends on what text is in which chunk | **After the corpus pass** |

**Presence** is the stable guardrail check and should be in the baseline. **Correctness** and
**grounding** are the slice to pin after corpus findings #1/#2 land.

## Why correctness/grounding move when the corpus moves

Worked example:

> *"Can I get a refund if my flight is cancelled?"*

- Routing (`rights_info`), eligibility, any amount → **corpus-independent**; pin today.
- Expected citation → **corpus-dependent.** Today the best-grounded chunk for that
  plain-language phrasing may come from the **Your Europe summary**
  (`plain_language_summary.md`), making today's "correct" citation *"EU Air Passenger Rights
  Summary."* Removing that file (**finding #1**) makes that expected citation **impossible**;
  the answer must now ground in **Reg. 261/2004 Art. 8**, so the ground truth flips
  `Your Europe summary` → `Reg 261/2004, Art. 8`.
- **Finding #2** (LLM-extraction re-acquisition) moves it again: re-chunking changes
  `chunk_id`s and can shift section/article *labels* (cf. the parked OJ-notice em-dash leak,
  `Section · — …` vs a clean `Section 4.3.3`). The *fact* stays in the corpus; the *pointer*
  changes.

So routing/eligibility/amount labels survive a corpus swap untouched — **only the citation
pointers shift.** The coupling is narrow.

## How to write citation assertions so coupling stays small

Write at the **most stable granularity** so even the "coupled" part is mostly tameable:

1. **Assert `source + article/section`, never `chunk_id` or exact chunk text.** "cites Reg
   261/2004 Art. 7" survives re-chunking; "cites chunk `reg_261_2004#42`" does not.
2. **Assert the *minimum required* citation, or set-membership** — `must cite at least one of
   {Art. 5, Art. 7}` — rather than an exact list. Robust to retrieval reshuffling and to a 3B
   model citing one supporting article vs. two.
3. **Split presence from correctness.** Score *presence* in the baseline (never moves); defer
   the *specific* article until after the corpus pass — and even then, only for questions whose
   grounding doc you're adding/removing/re-parsing.
4. **Normalize before comparing.** Match on normalized `source` + article/section number
   (case-insensitive, label-tolerant) so a cosmetic label fix (em-dash leak) doesn't fail a
   semantically-correct citation.

## Suggested eval-case schema (for `eval/eval_set.yaml`)

Keep the citation expectation separate from routing/amount expectations so each can be scored
(and pinned) independently:

```yaml
- id: cancel-refund
  query: "Can I get a refund if my flight is cancelled?"
  expect:
    query_type: rights_info          # corpus-independent — pin now
    # amount / eligibility omitted (not a calc question)
    citations:
      present: true                  # presence — corpus-independent, baseline
      any_of:                        # correctness — pin AFTER corpus pass
        - { source: "Reg (EC) 261/2004", article: "8" }
      # match on normalized source + article/section; ignore chunk_id & label cosmetics
```

`present: true` goes in the baseline immediately. `any_of` (correctness) is filled/finalized
once the corpus is settled. A question with no `any_of` is still scored on presence — so the
baseline is meaningful before any citation-correctness exists.

## Scoring mechanics (for the runner)

- **Presence:** answer's parsed citation list is non-empty for rights/interpretive answers
  (and the calculator-only path is exempt — amounts come from the deterministic tool, not RAG).
- **Correctness:** ≥1 produced citation matches the `any_of` set on normalized
  `source` + `article/section`. Treat as **recall of required sources**, not exact-set equality
  — over-citing extra valid articles is not a failure; missing all required ones is.
- **Grounding (optional, heavier):** if scored, check the cited chunk's text actually contains
  the claim — likely an LLM-graded or string-overlap check; expensive, so consider a sampled
  subset rather than every case.

## Sequencing rule (one line)
Pin **presence** in the baseline now; pin **citation-correctness/grounding** only **after the
corpus pass** (findings #1 + #2), and only for cases whose grounding doc changed.
