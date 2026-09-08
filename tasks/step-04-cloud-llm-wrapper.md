# Step 4 — `src/mimir/llm/cloud.py`

The `claude -p` subprocess wrapper. Rungs 1-3.

**Prerequisite:** step 2 complete and confirmed.

## Interface

```python
run(prompt: str, rung: int, allowed_tools: list[str] | None = None,
    session_id: str | None = None, timeout: int | None = None) -> dict
    # returns {"text": str, "ok": bool, "rung": int,
    #          "session_id": str | None, "error": str | None,
    #          "seconds": float}

escalation_counts() -> dict[int, int]   # per-rung count for today
reset_daily_counts() -> None
```

## Command construction

```
claude -p <prompt> --model <config.models[f"rung_{rung}"]> --output-format json
```

Append `--allowedTools` when scoped, `--resume <id>` for continuity.

Verified working on this account: `claude-haiku-4-5`, `claude-sonnet-5`,
`claude-opus-5`.

## Requirements

1. **`subprocess.run` with `shell=False`.** Prompts contain user text —
   never build a shell string.
2. **Explicit timeout**, default from `config.routing.cloud_timeout_seconds`.
   Timeout returns `ok: False`, never hangs the daemon.
3. **Non-zero exit is an error result**, never a silently empty string. The
   caller must be able to tell failure from an empty answer.
4. **Increment the per-rung escalation counter on every call**, including
   failures — a failed call still consumed subscription budget.
5. **Warn at `config.routing.daily_escalation_warn`.** Warn, don't block.
6. **Scope `--allowedTools` to the narrowest set that can complete the task.**
   MIMIR's own permission system stays authoritative; do not delegate trust to
   Claude Code's tool access.
7. **Counters persist across daemon restarts** — store under
   `{data_root}/data`. A counter that resets on restart cannot enforce a
   daily budget.

## Tests — `tests/test_cloud_llm.py`

Real calls are slow and consume budget. Keep them to one, mock the rest.

- Command construction is correct per rung (mocked, assert on argv)
- `shell=False` is used — assert it explicitly
- Timeout produces `ok: False` with an error, no exception escaping
- Non-zero exit produces `ok: False` with the stderr captured
- Counters increment on success AND failure
- Counters survive a simulated restart
- **One real call** to `claude-haiku-4-5` — cheapest rung — asserting
  `ok: True` and non-empty text. Skip if `claude` is not on PATH.

## Done when

- All tests pass
- A real haiku call returns text
- Counters persist across restart, verified by test not inspection

## Stop here

Do not start step 5. Wait for confirmation.
