# MIMIR — Phase 0: Scope Lock

**Status:** Awaiting sign-off
**Owner:** DJ
**Repo root:** `C:\MIMIR\MIMIR`
**Document path:** `docs/00-scope-lock.md`

---

## 1. What MIMIR Is

MIMIR is a locally-hosted AI orchestrator for a Windows 11 desktop. It is **not** a single model. It is a routing daemon that receives natural-language requests, decides which model tier and which control method should handle them, executes, verifies, and reports.

**Design analogy:** JARVIS from Iron Man, minus the fiction. What transfers is natural-language command of everything, persistent contextual memory, background multitasking, threshold-triggered alerts, confirmation before consequential action, and the ability to drive external systems. What does not transfer is physical-world sensor fusion, holographic interfaces, and autonomous hardware control.

**Character reference:** Mimir from *God of War* (2018) — advisor, wry, encyclopedic, and canonically **not prescient**. Admitting the limits of knowledge is in character, which aligns the persona with the anti-hallucination policy rather than fighting it.

### Non-goals
- Not a replacement for the existing Jarvis/n8n/Telegram/ngrok pipeline — that stays untouched
- Not an absorption of ORB or KRATOS — those remain independent applications
- Not a cloud service, SaaS, or anything with a hosted component

---

## 2. Hardware Baseline

| Component | Spec |
|---|---|
| GPU | NVIDIA RTX 3060 Ti, **8GB VRAM** |
| System RAM | 32GB |
| CPU | AMD Ryzen 5 5600X, 6 cores |
| OS | Windows 11 |
| User | `loams` |

**Implications:** 7–8B models at Q4 run comfortably and form the local tier. 14B Q4 is possible with partial CPU offload but too slow for interactive use. Anything 30B+ is cloud-tier only. Whisper (speech-to-text) and an embedding model fit alongside a 7–8B without contention.

---

## 3. Locked Architecture Decisions

| Dimension | Decision |
|---|---|
| Identity | Local orchestrator / router, not a monolithic model |
| Brain | Hybrid — local model + cloud escalation ladder |
| Cloud auth | Claude Code headless (`claude -p`) via existing subscription. **No API key at v1.** |
| Cloud spend | $0 target. Optional $5–10 credits later, failover only. |
| Form factor | Always-on background daemon exposing a local API |
| First client | CLI |
| Second client | Spatial-canvas dashboard |
| Third client | Telegram (also covers mobile) |
| Voice | Designed for now, built last |
| Reach | Desktop, laptop, phone |
| External apps | MIMIR launches and drives ORB and KRATOS; does not absorb their code |

### Game mode
A watchdog detects GPU-heavy application launches, unloads the local model from VRAM, and flips MIMIR to cloud-only routing. MIMIR stays fully functional while gaming at approximately zero GPU cost. State restores automatically on game exit.

---

## 4. Model Routing Ladder

| Rung | Model | Handles |
|---|---|---|
| 0 | Local (7–8B Q4) | Routing, classification, simple queries, summarization |
| 1 | Haiku 4.5 | Easy tasks local can't finish — reformatting, extraction, short synthesis |
| 2 | Sonnet 5 | Real work — code, analysis, multi-step reasoning |
| 3 | Opus 5 | Hard reasoning, vision/GUI, anything that failed verification at rung 2 |

All model identifiers live in `config.yaml`. Never hardcoded. Model upgrades are a one-line change.

> **Verify before Phase 2:** confirm which model strings the `claude` CLI accepts on this account.

### Escalation triggers
Escalation happens **only** on:
1. Local model self-reports low confidence
2. Task pre-classified as hard (multi-step reasoning, code generation, financial analysis, vision)
3. A local attempt failed post-action verification
4. Explicit user request

Everything else stays local. The dashboard displays a running daily escalation counter per rung.

### When MIMIR asks instead of acting
- Ambiguous target (which file? which ticker?)
- Irreversible action
- Anything outside the whitelist
- Standing orders in conflict
- A job that will consume significant escalations

---

## 5. Desktop Control

Three tiers, tried in order. MIMIR escalates only when the cheaper tier fails.

| Tier | Method | Cost | Est. share | Covers |
|---|---|---|---|---|
| 1 | Scripted | Free, fast | ~80% | App launch/close, file CRUD, PowerShell, window management, clipboard, process control, scheduled tasks, system telemetry |
| 2 | Windows UI Automation tree | Free, fast | ~15% | Reads real control names — click named buttons, fill fields, read values, navigate menus. Covers Excel, Outlook, browsers, most desktop software. |
| 3 | Vision (screenshot + reasoning) | Expensive, slow | ~5% | Canvas apps, games, Electron UIs with no accessibility tree |

**Why this order matters:** vision-first GUI control would be slow, costly against subscription limits, and unreliable. The accessibility-tree tier is what makes daily use affordable.

### Hard "never" list — all tiers, no exceptions
- Type passwords, card numbers, or credentials
- Make purchases
- Send messages as the user without explicit confirmation
- Modify system or security settings
- Permanently delete anything (recycle bin only)
- Act outside the whitelist without an explicit yes

---

## 6. Permissions

**Whitelist:**
1. `C:\Users\loams\` — entire user folder, minus financial and sensitive directories
2. `C:\MIMIR\` — MIMIR's own project tree

Free rein inside. Confirmation required outside.

> **Why entry 2 exists:** the repo sits at `C:\MIMIR\MIMIR`, outside the user folder. Without an explicit whitelist entry, MIMIR would need confirmation to write its own logs, memory DB, and undo journals — every single time.

**Required Phase 3 deliverable:** an explicit exclusion list. Vague exclusions are how accidents happen.

### Cloud tool scoping — measured, not assumed

Measured on Claude Code 2.1.263, 2026-09-08, via three probe calls:

| Flags | Result |
|---|---|
| `--allowedTools ""` | **Still read the file — does NOT restrict** |
| `--disallowedTools "*"` | No tools offered |
| `--allowedTools "Read"` + deny `"*"` | No tools offered (deny wins) |

`--allowedTools` is an allow-list layered **on top of** Claude Code's defaults,
not an exclusive one, and it cannot be combined with a wildcard deny.

**Consequences:**
1. Cloud calls deny all tools by default. Granting none is the only way to grant nothing.
2. Granting *any* tool means Claude Code's default read-only access rides along. That residual is the price of granting one tool at all.
3. **MIMIR's gate is authoritative.** Cloud-side tool scoping is not a security boundary and must never be treated as one.

### Standing orders
A persistent policy system. The user sets a directive once and it silently governs MIMIR's behavior thereafter (e.g. "never touch anything in this folder," "always confirm before touching tax documents"). Active standing orders are visible on the dashboard.

*Origin: in* God of War *source material terms — the equivalent of Tony instructing JARVIS to keep a project off Stark systems, with the instruction persisting without restatement.*

---

## 7. Memory & Indexing

- Persistent facts and preferences
- Searchable conversation history
- Local semantic index of user files

**Privacy rule, non-negotiable:** the index stays local. Embeddings generated locally, stored in a local vector DB, searched locally. Only a *retrieved snippet* relevant to the immediate question is ever sent to the cloud tier. Never the index, never bulk file contents.

**Memory integrity:** every stored item tagged `stated` vs `inferred`, with timestamp and origin, so MIMIR cannot present its own inference as a user instruction.

---

## 8. Operating Modes

| Mode | Can interrupt? | Channels |
|---|---|---|
| **Silent** (default) | No | — |
| **Working** | Yes — briefs + alerts | Desktop + Telegram |
| **Voice** | Yes — speaks aloud | Voice + Telegram |

**Notifications:** Telegram bot. Free, no carrier, works on desktop and phone, and provides a two-way channel — MIMIR can be commanded from the phone without a separate mobile client.

**Security:** the bot token is a password. A leak lets anyone message as MIMIR. `.env` only, never committed.

---

## 9. Persona

| Element | Rule |
|---|---|
| Address | "brother" — used **sparingly**, not every message |
| Register | Warm, wry, plainspoken. Light Scots inflection in word choice. |
| Humor | Present but brief. Serious topics get a serious voice. |
| Context | Volunteers relevant background unprompted |
| Uncertainty | Admits limits openly and in character |
| Pushback | States disagreement directly. Does not simply agree. |

### Persona scope — the critical rule

- **ON** in conversation, greetings, status, alerts — capped at **one sentence** of character per response
- **OFF** in deliverables — financial analysis, code, homework, documents, and anything destined to be pasted elsewhere comes out clean and professional

A wry line framing an analysis is good. A wry line inside the analysis makes it unusable.

---

## 10. Interface Design Language

**Paradigm: spatial canvas.** A full-screen visualization with a live coordinate grid. Draggable, resizable panels scale-open on summon and scale-close on dismiss. The command input is hidden until called. This suits a silent-by-default assistant far better than permanent fixed rails.

| Element | Value |
|---|---|
| Background | `#050810` |
| Panel | `rgba(10,10,14,0.85)`, 8px radius, 1px border |
| Text / dim | `#e0e6ed` / `#6b7d99` |
| **Identity accent** | **Amber/gold** |
| Status | danger `#ef4444` · warning `#f59e0b` · success `#00e676` |
| Type | Courier New, uppercase headers, wide letter-spacing |
| Top bar | 36px, title left, tabular-nums clock right |
| Controls | Circular icon buttons, bottom-left, pulse when active |

**Palette discipline:** one identity accent plus status colors. Nothing else. The reference dashboard had drifted to five competing accents through feature accretion, which flattened visual hierarchy. Not inherited.

**Centered orb = state indicator.** Color and motion encode current mode, active model tier, and thinking state. One glance conveys what MIMIR is doing without reading text.

**Panels:** none inherited. MIMIR's panel set is designed from scratch, decided during build.

**Source note:** design language extracted from a reference stylesheet and screenshot as *visual reference only*. No code imported — a clean-slate build cannot inherit another project's bugs, dependencies, and assumptions.

---

## 11. File Naming Convention

```
YYYY-MM-DD_domain_descriptor_v01.ext

2026-09-05_finance_orb-journal-export_v03.csv
2026-09-05_lsu_acct301-ch7-notes_v01.md
```

**Rules**
- ISO dates only — sorts chronologically by default
- Lowercase throughout
- Hyphens *within* a field, underscores *between* fields
- Zero-padded version numbers
- No spaces, ampersands, or apostrophes
- Full path under 200 characters (Windows breaks near 260)

**Safety rule — non-negotiable:** no bulk rename or move executes without (a) a **dry-run manifest** listing every old path → new path for approval, and (b) an **undo journal** that reverses the entire batch with one command. A file organizer without an undo log is a shredder.

---

## 12. Anti-Hallucination Countermeasures

Derived from six failure modes: slow response, forgetting prior instructions, fabricating information, confident errors, insufficient proactivity, and constant deferral.

| Risk | Countermeasure |
|---|---|
| Invents file paths | Every path verified (`Test-Path`) before action. Acts on tool output, never recall. |
| Invents tickers, prices, financials | **No unsourced numbers rule** — any figure carries a source and retrieval timestamp, or is not stated |
| Fabricates click targets in vision mode | Act-then-verify: screen state must change as predicted, or abort. Never blind-retry. |
| Fake citations in research | URL required and fetched. Unfetchable source is dropped, not cited. |
| Treats own inference as user instruction | Memory tagged `stated` vs `inferred` with origin and timestamp |
| Confident and wrong | Confidence gate — escalate or say "I don't know" rather than fill the gap |

**General pattern:** verify before acting, verify after acting, never assert a fact not retrieved this session.

---

## 13. Repository

- **Name:** `MIMIR`
- **Visibility:** **Private, non-negotiable.** Contains username paths, whitelist structure, and standing orders. Not a portfolio piece.
- **Repo root:** `C:\MIMIR\MIMIR` (cloned inside the `C:\MIMIR` parent folder)
- **Code lives in the repo. Runtime data lives in the parent.** All generated state — memory DB, file index, logs, undo journals, model weights — sits in `C:\MIMIR\`, physically outside the repo. A broken `.gitignore` or a mistaken `git add -f` cannot leak them.
- **Branching:** `main` always working. One branch per phase. Tag on merge (`v0.1-skeleton`, `v0.2-control`) for per-phase rollback.

### `.gitignore` — mandatory
```
.env                  # Telegram bot token, any keys
/models/              # GGUF weights — gigabytes, re-downloadable
/data/memory.db       # conversation history
/data/index/          # vector index of user files
/logs/
/journal/             # undo logs
/sessions/
*.log
```

Commit `.env.example` with empty keys to document structure without secrets.

**Decision:** memory DB and file index are **never committed.** Committing them would push a searchable map of personal files to GitHub. Multi-machine sync, if ever needed, happens by direct transfer.

### Current state
Repo cloned. Next step:
```bash
cd C:\MIMIR\MIMIR
git checkout -b phase-1-architecture
```

---

## 14. Isolation Rules

MIMIR has **zero contact** with the existing Jarvis project: no shared files, no shared code, no shared configuration, no n8n, no ngrok, no reuse of the existing Telegram bot. A new bot is registered for MIMIR.

The only exception granted: the reference dashboard stylesheet and screenshot, used as *visual design reference only*, with no code imported.

---

## 15. Phase Map

| # | Phase | Output |
|---|---|---|
| **0** | **Scope lock** | **This document** |
| 1 | Architecture & stack | Tech selections, folder structure, daemon design, model selection, router logic, dashboard mockup |
| 2 | Core skeleton | Build spec: daemon, CLI, router, game watchdog — **Week 1 target** |
| 3 | Control layer | Escalation engine, whitelist system, exclusion list, standing orders |
| 4 | Memory & index | Vector DB, embeddings, history, file indexing |
| 5 | Modules | Market analysis, ORB/KRATOS drivers, research, work assist |
| 6 | Reach & modes | Laptop/phone access, mode switching, Telegram integration |
| 7 | Voice & hardening | Speech layer, logging, failure recovery, maintenance |

### Week 1 vertical slice — Phases 1–2 plus partial 3

**In scope:** daemon boots with Windows · CLI client · local model running · escalation to cloud ladder · game watchdog · scripted file and app control · basic whitelist enforcement

**Out of scope:** vision control, file indexing, market module, remote access, Telegram, voice, dashboard

**Rationale:** the full scope is a months-long build. A vertical slice produces something usable daily by next weekend, with every later capability slotting into it rather than forcing a rewrite.

---

## 16. Open Items for Phase 1

1. Confirm model strings accepted by the `claude` CLI on this account
2. Select the specific local model and quantization — requires latency benchmarking on the 3060 Ti
3. Choose the daemon runtime and language
4. Dashboard mockup for review before any UI is built
5. Draft the whitelist exclusion list

---

**Sign-off required before Phase 1 begins.**
