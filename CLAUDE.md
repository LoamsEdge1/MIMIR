# CLAUDE.md — MIMIR

Read automatically at session start. These are standing constraints, not
suggestions.

## Before writing any code

Read in order:
1. `docs/00-scope-lock.md` — what MIMIR is, permissions, persona, anti-hallucination rules
2. `docs/01-architecture.md` — stack, model ladder, router pipeline, dashboard spec
3. `docs/02-build-spec.md` — file manifest, build order, acceptance tests
4. `docs/role-system.md` — roles as config, scrutiny tiers (Phase 5)

## How work is assigned

Tasks live in `tasks/`. DJ will name one. Read it, complete only that task,
then stop and wait for confirmation. Do not run ahead to the next step.

## Non-negotiable constraints

1. **No hardcoded paths or model names.** Everything resolves from
   `config/config.yaml`. `data_root` is `C:\MIMIR` — runtime state lives
   outside the repo by design.
2. **Every registered action needs a verifier and a journal entry.** An action
   that cannot be verified or reversed does not get registered.
3. **The confidence gate is OFF.** Do not reintroduce self-reported model
   confidence as an escalation trigger. The 2026-09-08 benchmark measured both
   local models as *more* confident when wrong (qwen 0.92 right / 0.94 wrong).
   Escalation uses the chaining pre-check, hard task classes, stage 3 target
   resolution, and stage 6 verification failure.
4. **No local fallback.** On local model failure, escalate to rung 1. Never
   route to a second local model.
5. **Never invent targets.** Every file, path, and application is verified to
   exist before any action. Act on tool output, never on recall.
6. **Zero contact with `C:\JARVIS`.** Separate project. Not a reference, not a
   source, not a dependency. It is in the whitelist exclusions for this reason.
7. **No unsourced numbers.** Any figure carries a source and retrieval
   timestamp, or it is not stated.

## Router pipeline — seven stages

`docs/02-build-spec.md` still describes six. `docs/01-architecture.md` is
correct. Stage 0 is the deterministic chaining pre-check
(`src/mimir/router/chaining.py`). Reconcile 02 to match on your first pass.

0. Pre-check — deterministic chaining detection, no model
1. Classify — local model, structured JSON
2. Select tier — rung 0-3
3. Resolve targets — verify existence, never assume
4. Gate — whitelist, standing orders, destructive check
5. Execute
6. Verify — confirm the change happened; never blind-retry

## Environment

- Python 3.14.3, venv at `.venv` (`.\.venv\Scripts\python.exe`)
- Ollama local, `qwen2.5:7b-instruct-q4_K_M` at rung 0
- Cloud via `claude -p --model <name>`, subscription auth, no API key
- Windows 11, PowerShell

## Testing

`.\.venv\Scripts\python.exe -m pytest tests -q`

Benchmark (re-run after any classifier prompt change):
`.\.venv\Scripts\python.exe scripts\benchmark_local.py`

When MIMIR misclassifies something in real use, add the case to
`scripts/bench_cases.py` with the correct label. The set is meant to get
harder. A falling score after adding cases means it is working.

## Commit style

One commit per completed task. Message states what changed and why, including
the evidence behind any decision. Do not push without DJ asking.
