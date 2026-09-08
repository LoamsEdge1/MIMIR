# MIMIR — Phase 1: Architecture & Stack

**Status:** Awaiting sign-off
**Repo root:** `C:\MIMIR\MIMIR`
**Document path:** `docs/01-architecture.md`
**Prerequisite:** `docs/00-scope-lock.md` signed off

---

## 1. Runtime Language — Python

**Decision: Python 3.12 for the daemon and all core logic.**

This is not a preference call. Every hard capability MIMIR needs has a mature Python implementation and a painful or absent one elsewhere:

| Capability | Python | Node.js |
|---|---|---|
| Windows UI Automation | `uiautomation`, `pywinauto` — mature, native | Requires native addons or shelling to PowerShell |
| Windows COM (Excel, Outlook) | `pywin32` — direct | Awkward |
| Local LLM control | First-class client libraries | Workable |
| Embeddings / vector search | `chromadb`, `sentence-transformers` | Thin ecosystem |
| Speech-to-text (Phase 7) | `faster-whisper` — best-in-class | Bindings only |
| GPU telemetry | `pynvml` — official NVIDIA bindings | Shell out to `nvidia-smi` |

Tier 2 desktop control — the accessibility tree — is the single most load-bearing capability in the whole build, and it is a Python-native problem.

**Note on ORB:** ORB is Node.js. That does not matter. MIMIR drives ORB as an external application, not as a library. Different languages is correct here.

### Stack

| Layer | Choice | Why |
|---|---|---|
| Daemon / API | FastAPI + Uvicorn | Async, WebSocket support for live dashboard, minimal boilerplate |
| CLI client | Typer + Rich | Typed commands, readable terminal output |
| Local inference | Ollama | Windows installer, model management, and — critically — a programmatic unload API |
| Vector store | ChromaDB | Local-only, embedded, no server to run |
| Structured store | SQLite | Memory, history, undo journals. One file, no service. |
| Desktop control | `uiautomation` + `pywinauto` + `pywin32` | The three-tier control system |
| Telemetry | `psutil` + `pynvml` | Process and GPU monitoring for game mode |
| Config | YAML via `pydantic-settings` | Typed, validated, single source of truth |
| Dashboard | Vanilla HTML/CSS/JS served by FastAPI | No build step, no framework churn. Matches the reference design language. |

**Deliberately excluded:** no React, no bundler, no Docker, no Redis, no external database. Every added service is another thing that breaks at 11pm before an exam.

---

## 2. Local Model Selection

8GB VRAM must hold the language model, its KV cache, and an embedding model simultaneously.

| Candidate | Q4 size | Verdict |
|---|---|---|
| **Qwen 2.5 7B Instruct (Q4_K_M)** | ~4.7GB | **Primary.** Strongest instruction-following and reliable JSON output at this size — essential, because the router's job is emitting structured decisions. |
| Llama 3.1 8B Instruct (Q4_K_M) | ~4.9GB | Fallback. Benchmark against primary in Phase 2. |
| Qwen 2.5 14B (Q4) | ~9GB | Rejected. Exceeds VRAM with context; CPU offload makes it too slow to be the interactive tier. |

**Embedding model:** `nomic-embed-text` (~275MB) — runs under the same Ollama instance, leaves ample headroom.

**Budget:** ~4.7GB model + ~0.3GB embeddings + ~1.5GB KV cache ≈ 6.5GB, leaving ~1.5GB headroom on an 8GB card.

> **Phase 2 task:** benchmark tokens/sec and routing accuracy for both candidates on this hardware before locking.

---

## 3. Folder Structure

Code in the repo. Runtime state in the parent, physically outside version control.

```
C:\MIMIR\
├── MIMIR\                      ← git repo
│   ├── src\mimir\
│   │   ├── daemon\             API server, job queue, lifecycle
│   │   ├── router\             tier selection, escalation, verification
│   │   ├── control\            tier 1 scripted / tier 2 uia / tier 3 vision
│   │   ├── memory\             facts, history, index
│   │   ├── watchers\           game mode, file, threshold watchers
│   │   ├── modules\            market, research, work assist, orb, kratos
│   │   ├── notify\             telegram
│   │   └── persona\            voice rules, response shaping
│   ├── cli\
│   ├── dashboard\              static html / css / js
│   ├── config\
│   │   ├── config.yaml
│   │   ├── whitelist.yaml
│   │   └── standing_orders.yaml
│   ├── docs\
│   ├── tests\
│   ├── .env.example
│   ├── .gitignore
│   └── requirements.txt
│
├── data\                       memory.db, index\
├── logs\
└── journal\                    undo logs
```

**Not present:** a `models\` directory. Ollama manages weights in its own store (`%USERPROFILE%\.ollama`). Duplicating gigabytes to satisfy a folder diagram is waste.

**Path rule:** all runtime paths resolve from a single `MIMIR_DATA_ROOT` value in config, defaulting to `C:\MIMIR`. Never hardcoded anywhere in `src\`.

---

## 4. Daemon Design

A single long-lived Windows process, launched at login via Task Scheduler.

| Component | Responsibility |
|---|---|
| API server | HTTP + WebSocket on localhost. All clients talk to this. |
| Job queue | Async queue. Long jobs run in background; MIMIR stays responsive. |
| Session store | Conversation continuity across CLI, dashboard, and Telegram — one context regardless of client |
| Watcher pool | Game mode, file changes, threshold alerts |
| Mode controller | Silent / Working / Voice — governs whether MIMIR may interrupt |

**Client model:** CLI, dashboard, and Telegram are all thin clients of the same API. Adding voice in Phase 7 means adding a fourth client, not rewriting the core.

**Why the daemon must exist:** `claude -p` runs one turn and exits. It is not a daemon. Persistent state, background jobs, and watchers all require a supervisor, and MIMIR is that supervisor.

---

## 5. Router Design

Every request runs the same six-stage pipeline:

| Stage | Action |
|---|---|
| 0. Pre-check | **Deterministic chaining detection.** Structural, no model. Forces `multistep` when the request chains side-effecting work. |
| 1. Classify | Local model tags intent and task class, emits structured JSON |
| 2. Select tier | Task class + confidence + game-mode state → rung 0–3 |
| 3. Resolve targets | Files, apps, tickers verified to exist. **Never assumed.** |
| 4. Gate | Whitelist check, standing-orders check, destructive-action check → execute or ask |
| 5. Execute | Run at the chosen tier; control actions escalate 1 → 2 → 3 independently |
| 6. Verify | Confirm the intended change actually happened. On failure: escalate or report — never blind-retry. |

**Stages 3 and 6 are the anti-hallucination system.** Stage 3 prevents acting on invented targets. Stage 6 prevents reporting success that didn't occur.

### Escalation triggers
1. Local model self-reports low confidence
2. Task pre-classified hard (multi-step reasoning, code generation, financial analysis, vision)
3. Local attempt failed stage 6 verification
4. Explicit user request

### Cloud invocation
```
claude -p "<prompt>" --model <tier_model> --output-format json --allowedTools "<scoped>"
```

`--allowedTools` is scoped per call. Claude Code gets the narrowest tool set that can complete the task — MIMIR's own permission system stays authoritative rather than delegating trust.

---

## 6. Game Watchdog

**Detection:** poll every 5 seconds via `pynvml` for any non-Ollama process holding significant GPU memory, cross-checked against `psutil` for fullscreen-exclusive windows. Config carries a manual override list for false positives and misses.

**On trigger**
1. Set Ollama `keep_alive: 0` and unload the model → VRAM released
2. Router state → `cloud_only`
3. Dashboard orb reflects game mode
4. Pause non-urgent background jobs

**On game exit:** restore local model, resume queue, restore previous mode.

**User-facing effect:** none. MIMIR stays fully functional on the cloud ladder and uses effectively zero GPU.

---

## 7. Config Shape

`config/config.yaml`

```yaml
data_root: "C:\\MIMIR"

models:
  local:  "qwen2.5:7b-instruct-q4_K_M"
  embed:  "nomic-embed-text"
  rung_1: "claude-haiku-4-5"
  rung_2: "claude-sonnet-5"
  rung_3: "claude-opus-5"

routing:
  confidence_threshold: 0.75
  hard_task_classes: [code, analysis, vision, multistep, financial]
  daily_escalation_warn: 25

control:
  tier_order: [scripted, uia, vision]
  vision_enabled: false        # Phase 3

game_mode:
  poll_seconds: 5
  gpu_memory_threshold_mb: 1500
  always_games: []
  never_games: []

persona:
  address: "brother"
  address_frequency: sparing
  max_character_sentences: 1
  disabled_for: [deliverable, code, analysis, document]

modes:
  default: silent
```

Model identifiers are strings in config. A newer model means one edited line.

> **Blocking check before Phase 2:** confirm the `claude` CLI accepts these model strings on this account.

---

## 8. Dashboard Specification

Reviewed as a rendered mockup, not described. Confirmed elements:

| Element | Behaviour |
|---|---|
| Top strip | `M.I.M.I.R.` · mode · active tier · daily escalation count · clock |
| Centre orb | State indicator. Ring count = active model tier. Centre colour = mode. Motion = thinking. |
| System panel | VRAM, loaded model, game-mode state, index size, uptime |
| Pending panel | Confirmation queue — review or deny without blocking the canvas |
| Recent panel | Action log, per-action undo |
| Bottom-left controls | Power, sleep, voice (voice inactive until Phase 7) |
| Command bar | Hidden until summoned. **F1 toggles**, Enter submits, Escape or backdrop click dismisses. |
| Panels | Draggable, resizable, scale-open on summon, scale-close on dismiss |

**Command bar binding** ports from source unchanged: a document-level `keydown` listener on `F1` with `preventDefault`, toggling on the element's display state. The input POSTs to `/api/chat`, which matches the daemon contract in §4 — client wiring carries over as-is.

**State parameter swap.** `idle` and `listening` exchange parameter sets from the source values:

| State | emergence | scale | speed | detail | bloom |
|---|---|---|---|---|---|
| `idle` | 0.5 | 13 | 1.5 | 3.0 | 0.5 |
| `listening` | 0.3 | 22 | 2.7 | 4.4 | 0.4 |

A smaller, slower resting form; a larger, livelier form when listening.

> **Consequence to confirm:** in the source, `offline` duplicated the old `idle` values. After the swap it no longer matches, so game mode now renders as the large slow form. That reads as usefully distinct — recommend keeping it, with a desaturated ramp so it registers as dormant rather than active.

**Palette:** background `#050810` · panel `rgba(10,10,14,0.85)` · text `#e0e6ed` / dim `#6b7d99` · identity accent amber `#EF9F27` · status `#ef4444` / `#f59e0b` / `#00e676`. One identity accent plus status colours. Nothing else.

### Orb and grid — ported, not rebuilt

The centre pulse uses the **golden-ratio point distribution and pulse animation from the reference dashboard, ported intact.** The background grid keeps its **radial cutout around the orb**.

**Import boundary:** this is a self-contained renderer — pure geometry and drawing, no dependency on the source project's state, config, or services. That makes it a safe copy. Nothing else crosses.

**Colour is parameterised.** The geometry and motion are unchanged; the colour ramp becomes a driven input — amber at idle, status colours on state change. The reference gradient is not carried over, because a second identity colour would break both the palette discipline and the orb's job as a state indicator.

**Grid cutout is new work.** The source clips the grid to a rectangle via four `THREE.Plane` clipping planes plus a brighter border line. It has no radial cutout around the orb. That is added, not ported.

### Orb state machine → MIMIR states

The source state machine ports directly. Each state carries its own `emergence`, `scale`, `speed`, `detail`, and `bloom`.

| Source state | MIMIR meaning |
|---|---|
| `idle` | Silent mode, local model loaded |
| `listening` | Voice mode active |
| `processing` | Working a request — hue shifts by escalation rung |
| `speaking` | Voice output, driven by `speakingAmplitude` |
| `error` | Failed verification or denied action |
| `offline` | **Game mode** — local unloaded, cloud-only |

**Panel set beyond the three shown is decided during build,** not inherited.

---

## 9. Phase 2 Preview — Week 1 Vertical Slice

**Build order**
1. Repo skeleton, config loader, logging
2. Ollama install, both candidate models pulled, benchmarked
3. Daemon with API and job queue
4. Router stages 1–2, 6
5. Tier 1 scripted control
6. Basic whitelist enforcement
7. Game watchdog
8. CLI client
9. Persona layer

**Definition of done:** MIMIR launches at login, answers from the CLI, escalates to cloud when warranted, opens applications and manipulates files inside the whitelist, and unloads itself when a game starts.

**Explicitly out:** vision control, file indexing, market module, dashboard, Telegram, voice.

---

## 10. Open Items

1. ~~Confirm accepted `claude` CLI model strings~~ — **resolved.** `claude-haiku-4-5`, `claude-sonnet-5`, and `claude-opus-5` all verified working.
2. ~~Obtain the canvas renderer JS~~ — **resolved.** Golden-angle geometry, noise bands, tendril term, rotation, breath, and state machine all captured.
3. Confirm the radial cutout radius around the orb
4. Benchmark Qwen 2.5 7B vs Llama 3.1 8B on this GPU
5. Draft whitelist exclusion list (Phase 3, but start collecting now)
6. Register the MIMIR Telegram bot (Phase 6)

---

**Sign-off required before Phase 2 begins.**
