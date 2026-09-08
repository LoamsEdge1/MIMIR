# MIMIR — Role System

**Status:** Draft, awaiting sign-off
**Slots into:** Phase 5 (Modules)
**Document path:** `docs/role-system.md`

---

## 1. What This Replaces

The original idea was an org chart: MIMIR as CEO, a hierarchy of agents with
roles, each output reviewed up a chain before completion.

The instinct — specialisation plus scrutiny — is correct. The literal
implementation is rejected for four reasons:

| Problem | Detail |
|---|---|
| Cost inversion | Every review layer multiplies cloud calls. A 3-tier chain is 4–8 calls per task against a $0 API target and subscription limits. |
| Correlated errors | A Sonnet reviewer checking a Sonnet analyst shares its blind spots. Agreement means little; you pay 3x for the feeling of scrutiny. |
| Latency | "Open my downloads folder" becomes 40 seconds instead of 0.75. Unused within a week. |
| Debuggability | Locating a failure in a five-agent chain is far harder than in a linear pipeline with verification stages. |

**What replaces it:** roles as configuration, not processes. Scrutiny scaled to
stakes, not applied uniformly. Verification by tools, not by a second opinion.

---

## 2. A Role Is a File, Not a Process

A role is a markdown file MIMIR loads on demand. It costs nothing extra, is
versioned in git, and is editable without touching code.

```
config/roles/
├── financial-analyst.md
├── file-librarian.md
├── code-reviewer.md
├── researcher.md
└── coursework-tutor.md
```

### Role file format

```markdown
---
name: financial-analyst
triggers: [financial]
min_rung: 2
tools: [web_search, read_file, run_python]
review: independent
---

## Scope
Market data, tickers, screening, portfolio questions.

## Method
1. Retrieve current data before stating any figure.
2. Cite source and retrieval timestamp for every number.
3. State the timeframe explicitly.

## Output standard
- No unsourced numbers, ever.
- Distinguish observation from recommendation.
- Name what would falsify the conclusion.

## Never
- Give personalised investment advice.
- State a price without a timestamp.
```

**Why frontmatter matters:** `triggers` maps task classes to roles, `min_rung`
prevents a specialist task landing on a model too weak for it, `tools` scopes
what the role may touch, and `review` sets the scrutiny tier below.

### Selection
Stage 1 produces a `task_class`. The router loads the matching role and
prepends its content. Zero extra model calls — a role changes the prompt, tool
scope, and rung floor, not the number of round trips.

---

## 3. Scrutiny Scales With Stakes

Not every task earns review. Uniform review is what makes agent hierarchies
unaffordable.

| Tier | Applies to | Review |
|---|---|---|
| **none** | Reversible, local, low-cost — file listing, app launch, chat | Pipeline verification only (stages 3 and 6) |
| **gate** | Irreversible, destructive, or outside the whitelist | Confirmation gate — **you** are the reviewer |
| **independent** | External-facing, financial, published, or academic | One review pass at a **higher rung** than produced it |

**The independent tier's rule:** the reviewer must run at a higher rung than the
producer, and receives the output plus the role's "Output standard" section —
not the original request. Reviewing against a standard catches more than
reviewing against intent, and a higher rung breaks the correlated-error problem
that makes same-model review nearly worthless.

**Ceiling:** one independent review. Not a chain. A second reviewer at the same
rung adds cost and no information.

---

## 4. Deterministic Review First

The strongest evidence for this design came from the build itself.

The Phase 2 benchmark found both local models missed **every** multistep case.
A twelve-line regex pre-check fixed all of them, cost nothing, and runs in
microseconds. No agent hierarchy would have caught it, because every agent in
the chain shared the same blind spot.

The 2026-09-08 benchmark reinforced it: both models report ~0.9 confidence
whether right or wrong. **Asking a model to assess its own work produces a
number, not a signal.**

**Order of preference for any check:**

1. **Structural** — regex, path resolution, schema validation, type checks
2. **Tool-verified** — does the file exist, did the process start, did the value change
3. **Model review** — only when 1 and 2 cannot express the check

Most quality problems are catchable at levels 1 and 2. Level 3 is the expensive
fallback, not the default.

---

## 5. Where MIMIR's "CEO" Role Actually Lives

MIMIR is the orchestrator, and that is a real job:

- Selects the role and rung
- Enforces the gate and standing orders
- Owns verification at stages 3 and 6
- Holds session context across clients
- Reports the escalation budget
- Decides when a task is genuinely done

**What it does not do:** delegate to subordinates who delegate to subordinates.
The hierarchy is in the *decision path*, not in a payroll of models.

---

## 6. Sub-Agents — Where They Are Actually Warranted

Parallel sub-agents earn their cost in exactly one situation: **independent
work over disjoint inputs**, where results merge without negotiation.

Warranted:
- Summarise twelve documents — twelve independent reads, one merge
- Screen forty tickers against fixed criteria
- Index a large folder tree in parallel

Not warranted:
- Review chains
- "Second opinions" on a judgement call
- Anything where agent B needs agent A's output to start

**Rule:** parallel when inputs are independent. Never sequential for scrutiny.

---

## 7. Build Order

| Step | Deliverable |
|---|---|
| 1 | `config/roles/` directory, frontmatter schema, loader |
| 2 | Three starter roles: `file-librarian`, `financial-analyst`, `code-reviewer` |
| 3 | Role selection wired into the router after stage 1 |
| 4 | Review tiers wired into the gate |
| 5 | Independent review at the higher rung, capped at one pass |
| 6 | Parallel sub-agents for disjoint-input work only |

Steps 1–3 deliver most of the value. Steps 5–6 are optional until a real task
demands them.

---

## 8. Resolved Decisions

**`coursework-tutor` is a teaching role, not a completion role.** It helps DJ
understand material. It does not produce submittable work.

```markdown
---
name: coursework-tutor
triggers: [coursework]
min_rung: 2
review: none
---

## Method
1. Ask what the student has already tried before explaining anything.
2. Work through the reasoning, not the answer.
3. For numeric problems: explain the method, let DJ compute, then check.
4. Explain why a wrong answer is wrong, not just what the right one is.

## Never
- Produce a submittable answer to a graded problem.
- Write an essay, paper, or discussion post to be turned in.
- Complete a problem set. Explaining every step of an equivalent worked
  example is fine; producing the graded artefact is not.
```

**No local fallback.** If the local model fails, escalate to rung 1. Never fall
back to a second local model — `llama3.1:8b` fabricated targets on 11 of 65
benchmark cases, and a fallback that invents file paths is worse than none.

---

## 9. Open Questions

1. Which roles do you want first? The three starters are a guess.
2. Should roles be able to invoke other roles, or must MIMIR always mediate?
   Recommendation: MIMIR mediates. Role-to-role calls recreate the hierarchy
   this design exists to avoid.
