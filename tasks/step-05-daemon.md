# Step 5 — Daemon, job queue, and runtime state

**Prerequisite:** steps 2 and 4 complete and confirmed.

Files: `src/mimir/daemon/app.py`, `queue.py`, `session.py`, `modes.py`,
`state.py`

This is the spine. CLI, dashboard, and Telegram all become thin clients of it,
so the shape here determines how hard the next six steps are.

## API contract

Per `docs/02-build-spec.md` §4. Bind `127.0.0.1` only — no external interface
until Phase 6.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/chat` | Submit a request. Returns a response or a job id. |
| `GET` | `/api/status` | Mode, orb state, tier, VRAM, game mode, uptime, escalation counts |
| `POST` | `/api/mode` | Set silent / working / voice |
| `GET` | `/api/actions` | Recent actions with undo tokens |
| `POST` | `/api/undo/{token}` | Reverse a journalled action |
| `GET` | `/api/pending` | Confirmation queue |
| `POST` | `/api/pending/{id}` | Approve or deny |
| `WS` | `/ws/stream` | Live state, streamed responses, orb state changes |

`/api/chat` matches the existing dashboard client's shape — it POSTs
`{"message": "..."}`. Keep that contract.

Routes with no implementation behind them yet (`/api/actions`, `/api/undo`,
`/api/pending`) should exist and return honest empty results, not 404s. Steps 7
and 8 fill them in.

## Requirements

1. **Long jobs never block the API.** `/api/chat` returns a job id for anything
   slow and the result arrives over the WebSocket. A 7-second rung-1 call must
   not freeze the interface.
2. **One session across all clients.** CLI, dashboard, and Telegram share
   conversation context. Persist to SQLite under `{data_root}/data`.
3. **State is observable.** `/api/status` reports what the dashboard's system
   panel and orb need: current mode, orb state, active rung, VRAM, game mode,
   uptime, per-rung escalation counts.
4. **Orb states come from `config.orb_states`.** The six states are already in
   config with their emergence/scale/speed/detail/bloom values. Do not
   redefine them in code.
5. **Modes govern interruption.** Silent may not initiate. Working and Voice
   may. Enforce it in the daemon, not in each client — a client that forgets is
   then a display bug rather than a spam incident.
6. **Clean shutdown.** Cancel in-flight jobs, close the DB, unload the local
   model. A daemon that leaks a model into VRAM on restart breaks game mode.

## Explicitly NOT in this step

Router pipeline (step 6), control actions (step 7), gate (step 8), watchdog
(step 9). `/api/chat` should route to a placeholder handler that calls the
local model directly. Wiring the real pipeline is step 6's job.

## Tests — `tests/test_daemon.py`

Use FastAPI's `TestClient`. No live server required.

- `/api/status` returns every documented field
- `/api/chat` accepts `{"message": "..."}` and returns a response or job id
- A slow job returns a job id immediately rather than blocking
- WebSocket receives state changes
- `/api/mode` changes mode; Silent refuses to initiate
- Session context persists across simulated client reconnect
- Unimplemented routes return empty results, not errors
- Shutdown cancels jobs and unloads the model

## Done when

- All tests pass
- The daemon starts, answers `/api/status`, and handles a real `/api/chat`
  through the local model
- Ctrl-C shuts down cleanly with **VRAM released** — verify with `pynvml`, the
  same way step 2 was verified

## Stop here

Do not start step 6. Wait for confirmation.
