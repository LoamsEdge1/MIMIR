# MIMIR — Phase 2: Core Skeleton Build Spec

**Status:** Ready to execute
**Repo root:** `C:\MIMIR\MIMIR`
**Branch:** `phase-2-skeleton`
**Document path:** `docs/02-build-spec.md`
**Prerequisites:** `00-scope-lock.md` and `01-architecture.md` signed off

**Target:** a daemon that boots with Windows, answers from the CLI, escalates to cloud when warranted, controls files and applications inside the whitelist, and unloads itself when a game launches.

**Out of scope this phase:** vision control, file indexing, market module, dashboard, Telegram, voice.

---

## 1. Environment Prerequisites

Run before any code.

```powershell
python --version          # need 3.12.x
winget install Ollama.Ollama
ollama pull qwen2.5:7b-instruct-q4_K_M
ollama pull llama3.1:8b-instruct-q4_K_M
ollama pull nomic-embed-text
claude -p "reply with ok" --model claude-opus-5
```

Create the runtime tree outside the repo:

```powershell
mkdir C:\MIMIR\data, C:\MIMIR\logs, C:\MIMIR\journal
```

---

## 2. Dependencies

`requirements.txt`

```
fastapi==0.115.*
uvicorn[standard]==0.32.*
pydantic==2.*
pydantic-settings==2.*
pyyaml==6.*
httpx==0.27.*
typer==0.15.*
rich==13.*
psutil==6.*
nvidia-ml-py==12.*
uiautomation==2.*
pywin32==308
python-dotenv==1.*
pytest==8.*
```

`uiautomation` and `pywin32` are installed now but only exercised in Phase 3. They're in the manifest so the environment is built once.

---

## 3. File Manifest

Every file to create. Nothing else.

### Core
| Path | Purpose |
|---|---|
| `src/mimir/__init__.py` | Package marker, version string |
| `src/mimir/config.py` | Loads `config.yaml` + `.env` via pydantic-settings. Resolves `data_root`. **All paths originate here.** |
| `src/mimir/logging_setup.py` | Rotating file handler to `{data_root}/logs`, console handler, structured format |

### Daemon
| Path | Purpose |
|---|---|
| `src/mimir/daemon/app.py` | FastAPI app, route definitions, WebSocket, startup/shutdown lifecycle |
| `src/mimir/daemon/queue.py` | Async job queue. Submit, status, cancel. Long jobs never block the API. |
| `src/mimir/daemon/session.py` | Conversation context shared across all clients, persisted to SQLite |
| `src/mimir/daemon/modes.py` | Silent / Working / Voice state. Governs interruption permission. |
| `src/mimir/daemon/state.py` | Runtime state singleton — current mode, orb state, tier, escalation counters |

### Router
| Path | Purpose |
|---|---|
| `src/mimir/router/pipeline.py` | Orchestrates the seven stages in order |
| `src/mimir/router/chaining.py` | Stage 0 — deterministic chaining pre-check, no model |
| `src/mimir/router/classify.py` | Stage 1 — local model emits intent + task class as JSON |
| `src/mimir/router/tiers.py` | Stage 2 — rung selection from task class, confidence, game state |
| `src/mimir/router/resolve.py` | Stage 3 — verify every file, path, app target actually exists |
| `src/mimir/router/gate.py` | Stage 4 — whitelist, destructive-action, standing-orders check |
| `src/mimir/router/execute.py` | Stage 5 — dispatch to control layer or model tier |
| `src/mimir/router/verify.py` | Stage 6 — confirm the intended change occurred |

### Models
| Path | Purpose |
|---|---|
| `src/mimir/llm/local.py` | Ollama HTTP client. Generate, JSON mode, load, **unload**. |
| `src/mimir/llm/cloud.py` | `claude -p` subprocess wrapper. Model selection, JSON output, timeout, session resume. |

### Control
| Path | Purpose |
|---|---|
| `src/mimir/control/registry.py` | Action registry — name, handler, destructive flag, verifier |
| `src/mimir/control/scripted.py` | Tier 1 implementations |
| `src/mimir/control/journal.py` | Undo journal writer to `{data_root}/journal` |

### Watchers
| Path | Purpose |
|---|---|
| `src/mimir/watchers/game_mode.py` | GPU poll, model unload, router state flip, restore |

### Persona
| Path | Purpose |
|---|---|
| `src/mimir/persona/rules.py` | Persona on/off decision by output class |
| `src/mimir/persona/voice.py` | Applies address, register, one-sentence cap |

### Clients and config
| Path | Purpose |
|---|---|
| `cli/mimir.py` | Typer CLI — the Week 1 interface |
| `config/config.yaml` | Per §7 of `01-architecture.md` |
| `config/whitelist.yaml` | Whitelist roots and exclusions |
| `scripts/install_task.ps1` | Registers the Task Scheduler entry |
| `.env.example` | Empty keys, documented structure |
| `.gitignore` | Per §13 of `00-scope-lock.md` |

---

## 4. API Contract

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/chat` | Submit a request. Returns response or job id. **Matches the existing dashboard client.** |
| `GET` | `/api/status` | Mode, orb state, tier, VRAM, game mode, uptime, escalation counts |
| `POST` | `/api/mode` | Set silent / working / voice |
| `GET` | `/api/actions` | Recent actions with undo tokens |
| `POST` | `/api/undo/{token}` | Reverse a journalled action |
| `GET` | `/api/pending` | Confirmation queue |
| `POST` | `/api/pending/{id}` | Approve or deny |
| `WS` | `/ws/stream` | Live state, streamed responses, orb state changes |

Binds to `127.0.0.1` only. No external interface this phase.

---

## 5. Module Contracts

### `llm/cloud.py`
```
run(prompt, rung, allowed_tools=None, session_id=None, timeout=None) -> dict
        # {"text", "ok", "rung", "session_id", "error", "seconds"}
escalation_counts() -> dict[int, int]
reset_daily_counts() -> None
```
Builds: `claude -p --model <config.models[rung_N]> --output-format json --strict-mcp-config`, then the prompt after `--` so a prompt beginning with a dash stays text. Appends `--resume <id>` for continuity. Runs via `subprocess.run` with `shell=False` and an explicit timeout defaulting to `routing.cloud_timeout_seconds`. Parses JSON; a non-zero exit, an `is_error` body, a timeout, a missing CLI and an unparseable response are all `ok: False` with a populated `error` and an empty `text` — never a silent empty string, and never the CLI's own error prose passed off as an answer. **Increments the escalation counter for that rung before every call, failures included**, persisted to `{data_root}/data/escalations.json` so the daily budget survives a restart. Warns at `routing.daily_escalation_warn`; never blocks.

**Tool scoping, measured on Claude Code 2.1.263 (2026-09-08).** Three probe calls asking `claude-haiku-4-5` to read a file:

| flags | outcome |
|---|---|
| `--allowedTools ""` | read the file — does **not** restrict |
| `--disallowedTools "*"` | no tools offered |
| `--allowedTools "Read"` + `--disallowedTools "*"` | no tools offered — deny wins |

So `--allowedTools` is an allow-list layered on Claude Code's own defaults, not an exclusive one, and it cannot be combined with a wildcard deny. A call with no scoped tools therefore sends `--disallowedTools "*"` and gets no tools at all; a call that scopes a set accepts that Claude Code's default read-only access rides along. MIMIR's gate stays authoritative either way, which is why the default grants nothing.

### `llm/local.py`
```
generate(prompt, system=None, json_mode=False, timeout=180) -> dict
        # {"text": str, "tokens_per_sec": float, "seconds": float}
generate_json(prompt, system=None) -> dict | None
        # None on unparseable output. Never repaired, never retried.
classify(prompt) -> dict | None      # under config/classifier_prompt.txt
load() -> None
unload() -> None          # keep_alive=0, frees VRAM
is_loaded() -> bool
health() -> dict          # {"reachable", "model_present", "vram_mb"}
```
Model, host and keep-alive come from `config.yaml`; there are no literals in
the module. `unload()` verifies release twice — Ollama must drop the model from
`/api/ps`, and `pynvml` must show device VRAM fall. A clean return that freed
nothing raises `VramNotReleased`, because game mode depends on the memory
actually coming back. An unreachable Ollama is reported by `health()`, not
raised — the router escalates to rung 1 and never tries a second local model.

### `router/classify.py`
Returns:
```json
{ "intent": "...", "task_class": "...", "targets": [...], "confidence": 0.0, "destructive": false }
```
`task_class` ∈ `{chat, file_op, app_control, code, analysis, multistep, financial, unknown}`. Malformed JSON from the local model is a stage-1 failure and escalates — it is never repaired by guessing.

### `router/tiers.py`
```
select(task_class, confidence, game_mode) -> rung
```
Rung 0 unless: confidence below threshold, task class in `hard_task_classes`, a prior stage-6 failure, or explicit user request. Game mode forces a minimum of rung 1.

### `control/registry.py`
Every action declares:
```
name, handler, destructive: bool, verifier: callable, journals: bool
```
An action without a verifier cannot be registered. This is what makes stage 6 structural rather than optional.

### Tier 1 action set — Week 1
`open_app` · `close_app` · `focus_window` · `list_dir` · `find_files` · `read_file` · `write_file` · `move_file` · `copy_file` · `delete_to_recycle` · `get_system_info` · `run_powershell` (always gated, never auto-approved)

---

## 6. Whitelist

`config/whitelist.yaml`

```yaml
roots:
  - "C:\\Users\\loams"
  - "C:\\MIMIR"

exclusions:
  - "C:\\Users\\loams\\Documents\\Financial"
  - "C:\\Users\\loams\\.ssh"
  - "C:\\Users\\loams\\.aws"
  - "C:\\Users\\loams\\AppData\\Roaming\\Microsoft\\Credentials"

always_confirm:
  - run_powershell
  - delete_to_recycle
  - write_file
```

Placeholder exclusions. Replaced with the real list in Phase 3.

**Gate logic:** resolve to an absolute real path, then confirm it sits under a root and under no exclusion. Reject path traversal and symlink escapes explicitly — a whitelist checked by string prefix is not a whitelist.

---

## 7. Game Watchdog

```
poll every config.game_mode.poll_seconds (5s)
  → pynvml: processes holding > gpu_memory_threshold_mb, excluding ollama
  → cross-check psutil for fullscreen-exclusive window
  → apply always_games / never_games overrides

on trigger:
  local.unload() → router.force_min_rung(1) → state.orb = "offline"
    → queue.pause_non_urgent()

on release:
  local.load() → router.clear_min_rung() → state.orb = previous
    → queue.resume()
```

Debounce both transitions by two consecutive polls. A single spurious reading must not thrash the model in and out of VRAM.

---

## 8. Build Order

Each step ships working before the next begins.

| # | Step | Done when |
|---|---|---|
| 1 | Repo skeleton, config loader, logging | `config.load()` resolves all paths; logs write to `C:\MIMIR\logs` |
| 2 | `llm/local.py` | Round-trips a prompt through Ollama, returns valid JSON on demand |
| 3 | Benchmark | Tokens/sec and classification accuracy recorded for Qwen 7B and Llama 8B. **Winner written into config.** |
| 4 | `llm/cloud.py` | Returns parsed output from all three rungs; timeout and non-zero exit handled |
| 5 | Daemon + queue + state | Server runs, `/api/status` responds, jobs queue and complete |
| 6 | Router stages 0, 1, 2, 6 | Pre-checks chaining, classifies, selects a rung, verifies. No control layer yet. |
| 7 | `control/scripted.py` + registry + journal | All tier-1 actions work, each journalled and reversible |
| 8 | Gate + whitelist | In-whitelist acts freely, out-of-whitelist queues a confirmation |
| 9 | Game watchdog | Launching a game unloads the model; exiting restores it |
| 10 | CLI | `mimir "..."` works end to end |
| 11 | Persona layer | Character on in chat, off in deliverables, one-sentence cap enforced |
| 12 | Task Scheduler | Daemon starts at login |

---

## 9. Acceptance Tests

Week 1 is done when all of these pass by hand.

| # | Test | Expected |
|---|---|---|
| 1 | `mimir "what's my GPU doing"` | Local rung, no escalation |
| 2 | `mimir "open the orb console"` | Launches ORB, verified running |
| 3 | `mimir "find every csv in downloads from this month"` | Correct list, no invented paths |
| 4 | `mimir "move those into a folder called sorted"` | Moves, journals, `mimir undo` fully reverses |
| 5 | `mimir "delete everything in C:\Windows\Temp"` | Refuses — outside whitelist, queues confirmation |
| 6 | `mimir "write a python script that parses this csv"` | Escalates to rung 2, counter increments |
| 7 | Launch a game | Model unloads within 15s, VRAM drops, MIMIR still answers via cloud |
| 8 | Exit the game | Model reloads, state restores |
| 9 | Ask about a file that doesn't exist | Says so. Does not invent a path. |
| 10 | `mimir "summarise my week"` with no data | Admits it lacks the data. Does not fabricate. |
| 11 | Reboot | Daemon running at login without intervention |

**Tests 9 and 10 are the important ones.** Everything else is plumbing; those two are whether the anti-hallucination design actually holds.

---

## 10. Handoff to Claude Code

Suggested opening instruction:

> Read `docs/00-scope-lock.md`, `docs/01-architecture.md`, and `docs/02-build-spec.md`. Execute build order step 1 only. Do not proceed to step 2 until I confirm. All runtime paths resolve from config — never hardcode. Every registered action requires a verifier and a journal entry.

Working one step at a time is deliberate. A twelve-step build executed in one pass produces something that runs and cannot be debugged.

---

## 11. Deferred

Phase 3 opens with: the real whitelist exclusion list, tier 2 accessibility-tree control, standing orders, and vision as a gated last resort.
