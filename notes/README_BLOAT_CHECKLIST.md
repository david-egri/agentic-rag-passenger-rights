# README Bloat Checklist

Working checklist for **Phase A — expand `README.md` in place** (capture everything, don't polish).
Phase B later distills this into the target README, ordered by the
[TASK_DESCRIPTION.md](TASK_DESCRIPTION.md) deliverables enumeration
(problem & objective → architecture & justification → eval & performance → install & run).

> Discipline: **capture, don't polish.** Redundancy is fine now (distill cuts it). Prefer the *why*
> over the *what*. Don't invent — mark unverified claims `[CHECK]`. When in doubt, put it in.

---

## The rubric words to answer literally
- [ ] **Why *agentic* RAG** (not just why RAG) — why a graph/agent beats a single prompt here
- [ ] **Autonomous decision-making** — name the exact spots: router picks the lane, eligibility judges fault, corrective-RAG decides to retry
- [ ] **Decomposition into subtasks + independent execution** — the mixed-query fan-out, in those words
- [ ] **State management for intermediate results** — AgentState carries results between nodes
- [ ] **Justification of design decisions** — every "why this and not that" you can think of

## Design decisions to spell out (the "why", not just the "what")
- [ ] Why **two separate graphs / two separate states** instead of one
- [ ] Why the **calculator is deterministic / model-free** (and that it doubles as eval ground truth)
- [ ] Why an **explicit router node** instead of a bare conditional edge
- [ ] Why a **bounded** rewrite loop (and what the cap buys you)
- [ ] Why **qwen2.5:3b** specifically (8 GB ceiling, JSON strength, prose trade-off)
- [ ] Why **nomic-embed-text via Ollama** (avoids torch, one runtime)
- [ ] Why **structure-aware chunking** (by Article/Recital) over fixed windows
- [ ] Why **synthesize is plain code** (no second hallucination chance)
- [ ] Why **local-only / no paid API** (constraint and consequence)

## Trade-offs and limits (state them openly — reviewers reward honesty)
- [ ] **Workflow vs. autonomous agent** — what you gave up (open-ended autonomy) vs. bought (predictability, testability)
- [ ] The **routing weak spot** (71%) and *why it barely affects the answer*
- [ ] The **~18 s/query** cost and that it's the local model, not your code
- [ ] **CPU vs GPU 5.5×** and what follows from it
- [ ] **Known imperfections** (asymmetric EU coverage edge case, deferred fixes)

## Requirement-evidence to make explicit
- [ ] **≥5 nodes** — you have 7, name them
- [ ] **≥2 tools, one non-retrieval** — name both
- [ ] **RAG subgraph doesn't count toward the 5** — say it
- [ ] **Streamlit shows agent steps + RAG result** — the live trace + tabs
- [ ] **Dockerfile (compose = bonus)** — you have both
- [ ] **15-question eval + 50–200 load test** — the numbers

## Things worth adding that aren't there yet
- [ ] A **"requirements → where satisfied" map** (even rough — distill later)
- [ ] A **screenshot** of the Agent tab trace (or a note to add one)
- [ ] Anything good still trapped in **`DECISIONS.md`** or the **proposal** that never reached the README
- [ ] Concrete **example queries** and what each demonstrates

---

## Phase B reminder (distill target — do later)
Target README top-level order = TASK_DESCRIPTION deliverables enumeration:
1. [ ] Description of the problem and the objective
2. [ ] Overview of the system architecture and justification of design decisions
3. [ ] Summary of the functional evaluation and performance test results
4. [ ] Installation and running guide

(Install goes **last** — right for the interview-reviewer audience.)
