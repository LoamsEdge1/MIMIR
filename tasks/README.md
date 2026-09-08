# Tasks

One file per build step. Planning happens in Claude chat; the task file is the
handoff artefact Claude Code executes.

## How to use

1. Open Claude Code at `C:\MIMIR\MIMIR` (the repo root — not `C:\MIMIR`).
2. Tell it: `Read tasks/<file>.md and complete it.`
3. It stops at the end of that task and waits for confirmation.

`CLAUDE.md` loads automatically, so standing constraints never need restating.

## Naming

```
step-NN-short-descriptor.md
```

Numbers follow the build order in `docs/02-build-spec.md` §8. Sequential rather
than dated — order matters more than date here.

## Status

| Step | Task | Status |
|---|---|---|
| 1 | Repo skeleton, config, logging | done (in chat) |
| 2 | `llm/local.py` — Ollama client | done |
| 3 | Local model benchmark | done (in chat) |
| 4 | `llm/cloud.py` — `claude -p` wrapper | **next** |
| 5 | Daemon, queue, state | not written |
| 6 | Router stages 0-2, 6 | not written |
| 7 | Scripted control, registry, journal | not written |
| 8 | Gate and whitelist enforcement | not written |
| 9 | Game watchdog | not written |
| 10 | CLI | not written |
| 11 | Persona layer | not written |
| 12 | Task Scheduler | not written |

Steps 1 and 3 were completed during planning, which is why the remaining
sequence starts mid-list.
