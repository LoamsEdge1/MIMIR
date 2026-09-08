# Step 2 — `src/mimir/llm/local.py`

Ollama client for rung 0. Everything above it depends on this, so it ships
first.

## Why this exists separately from the benchmark

`scripts/benchmark_local.py` calls Ollama directly with `httpx`. That was fine
for a one-off measurement, but the router needs a real client with load/unload
control — the game watchdog cannot free VRAM without it.

When this module is done, refactor the benchmark to use it. Two code paths to
the same service will drift.

## Interface

```python
generate(prompt: str, system: str | None = None,
         json_mode: bool = False, timeout: int = 180) -> dict
    # returns {"text": str, "tokens_per_sec": float, "seconds": float}

generate_json(prompt: str, system: str | None = None) -> dict | None
    # returns the parsed object, or None on unparseable output.
    # NEVER repair malformed JSON by guessing. None is the honest answer and
    # the caller escalates. See CLAUDE.md constraint 5.

load() -> None
    # pull the model into VRAM

unload() -> None
    # keep_alive=0 — frees VRAM. The game watchdog calls this.

is_loaded() -> bool
health() -> dict
    # {"reachable": bool, "model_present": bool, "vram_mb": int | None}
```

## Requirements

1. **Model name and host come from `config/config.yaml`.** No literals.
2. **`unload()` must actually free VRAM.** Verify with `pynvml` before and
   after — a call that returns cleanly without releasing memory is a silent
   failure, and game mode depends on it working.
3. **Timeouts are explicit.** A hung local call must not block the daemon.
4. **Ollama unreachable is a normal condition, not a crash.** Return a health
   failure the router can act on by escalating.
5. **No retry loop on malformed JSON.** One attempt, then `None`.
6. Use the shared `config/classifier_prompt.txt` when the caller wants the
   classifier system prompt — do not embed a copy.

## Tests — `tests/test_local_llm.py`

Ollama is running locally, so these can be real rather than mocked. Skip
cleanly with `pytest.mark.skipif` when it isn't reachable.

- `generate()` returns non-empty text and a plausible tokens/sec
- `generate_json()` returns a dict for a well-formed request
- `generate_json()` returns `None` — not an exception, not a guess — when the
  model emits unparseable output
- `unload()` measurably reduces VRAM via `pynvml`
- `load()` after `unload()` restores a working model
- `health()` reports correctly when Ollama is up

## Done when

- All tests pass
- `benchmark_local.py` refactored to use this client, and re-running it
  produces results consistent with `C:\MIMIR\logs\benchmark-2026-09-08.json`
  (qwen ~91% accuracy, ~76 tok/s, 100% valid JSON)
- VRAM release confirmed by measurement, not by assumption

## Stop here

Do not start step 4. Wait for confirmation.
