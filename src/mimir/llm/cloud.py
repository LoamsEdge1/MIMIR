r"""
Cloud ladder — rungs 1-3, driven through the `claude -p` CLI.

Auth is the Claude Code subscription, not an API key, which is why this shells
out to a CLI instead of speaking HTTP to an endpoint.

What this module refuses to do
------------------------------
**Build a shell string.** Prompts carry user text. `subprocess.run` runs with
`shell=False` and the prompt goes after `--` as a positional argument, so a
prompt beginning with a dash is text rather than a flag.

**Return an empty string on failure.** A non-zero exit, a timeout, a missing
CLI and an unparseable response all come back as `ok: False` with a populated
`error`. The caller must be able to tell a failed call from an empty answer.
On failure `text` is deliberately empty: the CLI writes its own error prose
into the `result` field, and handing that back as MIMIR's answer would put a
tool's complaint in the persona's mouth.

**Delegate trust to Claude Code's permissions.** MIMIR's gate is authoritative.
By default a cloud call gets no tools at all.

Tool scoping, measured on Claude Code 2.1.263 (2026-09-08)
----------------------------------------------------------
Three probe calls against `claude-haiku-4-5`, asking it to read a file:

  --allowedTools ""                     read the file       (does NOT restrict)
  --disallowedTools "*"                 no tools offered    (restricts)
  --allowedTools "Read" + deny "*"      no tools offered    (deny wins)

So `--allowedTools` is an allow-list layered on top of Claude Code's own
defaults, not an exclusive one, and it cannot be combined with a wildcard deny.
The default path here therefore denies everything; a caller that scopes a tool
set gets exactly the flag the build spec asks for, and accepts that Claude
Code's default read-only access rides along with it. That residual is the price
of granting any tool at all, which is why the default grants none.

Counters
--------
Every call increments its rung's counter before the subprocess starts —
including calls that fail, because a failed call still spent subscription
budget, and counting after the fact loses the ones that crash the process. The
file lives under `{data_root}/data` so the budget survives a daemon restart.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import threading
import time
from datetime import date
from pathlib import Path
from typing import Any

from mimir import config

log = logging.getLogger(__name__)

RUNGS = (1, 2, 3)

# Denies every tool, including the read-only ones Claude Code permits itself in
# print mode. Verified above; see the module docstring.
_DENY_ALL_TOOLS = "*"

_lock = threading.Lock()


# --------------------------------------------------------------- daily counts


def _store_path() -> Path:
    return config.data_root() / "data" / "escalations.json"


def _empty_store() -> dict[str, Any]:
    return {"date": date.today().isoformat(), "counts": {str(r): 0 for r in RUNGS}}


def _read_store() -> dict[str, Any]:
    """
    Today's counts. A file from an earlier day is not carried forward — the
    budget is daily, and yesterday's spend is not this morning's problem.
    """
    path = _store_path()
    if not path.exists():
        return _empty_store()
    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("escalation counter unreadable (%s) — starting today at zero", exc)
        return _empty_store()

    if not isinstance(stored, dict) or stored.get("date") != date.today().isoformat():
        return _empty_store()

    counts = stored.get("counts")
    fresh = _empty_store()
    if isinstance(counts, dict):
        for rung in RUNGS:
            try:
                fresh["counts"][str(rung)] = int(counts.get(str(rung), 0))
            except (TypeError, ValueError):
                fresh["counts"][str(rung)] = 0
    return fresh


def _write_store(store: dict[str, Any]) -> None:
    """Atomic replace — a half-written counter file is a lost daily budget."""
    path = _store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def escalation_counts() -> dict[int, int]:
    """Per-rung cloud calls made today. Every rung is present, zero included."""
    with _lock:
        store = _read_store()
    return {rung: store["counts"][str(rung)] for rung in RUNGS}


def reset_daily_counts() -> None:
    with _lock:
        _write_store(_empty_store())
    log.info("escalation counters reset")


def _record_escalation(rung: int) -> int:
    """
    Count the call and return today's running total across all rungs.

    Warns at `routing.daily_escalation_warn` and keeps warning past it. It does
    not block: a budget that silently refuses to answer is worse than one that
    complains while working.
    """
    with _lock:
        store = _read_store()
        store["counts"][str(rung)] += 1
        total = sum(store["counts"].values())
        _write_store(store)

    threshold = config.get("routing.daily_escalation_warn", 25)
    if total >= threshold:
        log.warning(
            "cloud escalations today: %d (warn at %d) — %s",
            total, threshold, {r: c for r, c in escalation_counts().items()},
        )
    return total


# ------------------------------------------------------------------- the call


def _executable() -> str:
    """
    Absolute path to the CLI, or the bare name when PATH lookup fails so the
    error surfaces as a normal `ok: False` result rather than a stack trace.
    """
    name = config.get("cloud.executable")
    return shutil.which(name) or name


def available() -> bool:
    """Whether the CLI is on PATH. Tests skip the real call when it is not."""
    return shutil.which(config.get("cloud.executable")) is not None


def build_argv(
    prompt: str,
    rung: int,
    allowed_tools: list[str] | None = None,
    session_id: str | None = None,
) -> list[str]:
    """
    The exact argv handed to the CLI. Separate from `run` so the command can be
    asserted in a test without spending budget.

    `--strict-mcp-config` keeps the user's own MCP servers out of MIMIR's cloud
    calls: they are tools nobody scoped for this task.
    """
    if rung not in RUNGS:
        raise ValueError(f"rung must be one of {RUNGS}, got {rung!r}")

    argv = [
        _executable(),
        "-p",
        "--model",
        config.get(f"models.rung_{rung}"),
        "--output-format",
        "json",
        "--strict-mcp-config",
    ]
    if allowed_tools:
        # The CLI takes a comma- or space-separated list. One argument rather
        # than a variadic spread, so nothing after it can be swallowed.
        argv += ["--allowedTools", ",".join(allowed_tools)]
    else:
        argv += ["--disallowedTools", _DENY_ALL_TOOLS]
    if session_id:
        argv += ["--resume", session_id]

    # Everything after `--` is the prompt, even when it starts with a dash.
    argv += ["--", prompt]
    return argv


def _result(
    rung: int,
    seconds: float,
    text: str = "",
    ok: bool = False,
    session_id: str | None = None,
    error: str | None = None,
) -> dict:
    return {
        "text": text,
        "ok": ok,
        "rung": rung,
        "session_id": session_id,
        "error": error,
        "seconds": round(seconds, 3),
    }


def run(
    prompt: str,
    rung: int,
    allowed_tools: list[str] | None = None,
    session_id: str | None = None,
    timeout: int | None = None,
) -> dict:
    """
    One cloud call.

        {"text": str, "ok": bool, "rung": int,
         "session_id": str | None, "error": str | None, "seconds": float}

    Never raises on a call that reached the subprocess — a timeout, a crash, a
    missing CLI and a malformed response are all results the router can act on.
    An out-of-range rung does raise: that is a bug in the caller, not a runtime
    condition, and it must not silently spend budget.

    `session_id` comes back on success and can be passed to the next call to
    continue the same conversation.
    """
    if rung not in RUNGS:
        raise ValueError(f"rung must be one of {RUNGS}, got {rung!r}")

    if timeout is None:
        timeout = config.get("routing.cloud_timeout_seconds", 120)

    argv = build_argv(prompt, rung, allowed_tools, session_id)

    # Before the call, not after: a call that dies still spent budget.
    _record_escalation(rung)

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            argv,
            shell=False,
            capture_output=True,
            timeout=timeout,
            encoding="utf-8",  # the console default would mangle non-ASCII
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        seconds = time.perf_counter() - started
        log.warning("rung %d timed out after %ss", rung, timeout)
        return _result(rung, seconds, error=f"claude timed out after {timeout}s")
    except FileNotFoundError:
        seconds = time.perf_counter() - started
        return _result(rung, seconds, error=f"{config.get('cloud.executable')} not found on PATH")
    except OSError as exc:
        seconds = time.perf_counter() - started
        return _result(rung, seconds, error=f"could not start claude: {exc}")

    seconds = time.perf_counter() - started
    stderr = (proc.stderr or "").strip()

    try:
        payload = json.loads(proc.stdout or "")
    except json.JSONDecodeError:
        payload = None
    if not isinstance(payload, dict):
        detail = stderr or (proc.stdout or "").strip()[:200] or "no output"
        return _result(
            rung, seconds, error=f"claude exited {proc.returncode} with unparseable output: {detail}"
        )

    returned_session = payload.get("session_id")

    # The CLI reports failure two ways and they do not always agree: a bad
    # model exits 1 while still writing subtype "success". Trust both signals.
    if proc.returncode != 0 or payload.get("is_error"):
        detail = stderr or str(payload.get("result") or "").strip() or "no detail"
        status = payload.get("api_error_status")
        error = f"claude exited {proc.returncode}" + (f" (api {status})" if status else "") + f": {detail}"
        log.warning("rung %d failed: %s", rung, error)
        return _result(rung, seconds, session_id=returned_session, error=error)

    text = payload.get("result")
    if not isinstance(text, str):
        text = "" if text is None else str(text)

    log.info("rung %d ok in %.1fs (%d chars)", rung, seconds, len(text))
    return _result(rung, seconds, text=text, ok=True, session_id=returned_session)
