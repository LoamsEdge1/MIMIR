# MIMIR

A locally-hosted AI orchestrator for Windows 11. Not a single model — a routing
daemon that receives natural-language requests, decides which model tier and
control method handles them, executes, verifies, and reports.

**Private repository.** Contains whitelist paths, standing orders, and machine
structure. Not a portfolio piece.

## Layout

```
C:\MIMIR\
├── MIMIR\        ← this repo (code only)
├── data\         ← memory db, index      (never committed)
├── logs\         ← runtime logs          (never committed)
└── journal\      ← undo journals         (never committed)
```

Runtime state lives in the parent by design. A broken `.gitignore` cannot leak it.

## Setup

```powershell
cd C:\MIMIR\MIMIR
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env    # then fill in
```

Requires Ollama running locally and the `claude` CLI authenticated.

## Documentation

Read in order before touching code:

| Doc | Contents |
|---|---|
| `docs/00-scope-lock.md` | What MIMIR is, permissions, persona, anti-hallucination rules |
| `docs/01-architecture.md` | Stack decisions, model ladder, router, dashboard spec |
| `docs/02-build-spec.md` | File manifest, build order, acceptance tests |

## Ground rules

1. All paths resolve from `config/config.yaml`. Never hardcode.
2. Every registered action requires a verifier and a journal entry.
3. Never assert a fact not retrieved this session.
4. Verify before acting; verify after acting.
5. Zero contact with the separate JARVIS project.

## Status

Phase 2 — core skeleton. Environment verified on Python 3.14.3,
RTX 3060 Ti (8GB), all three cloud rungs reachable.
