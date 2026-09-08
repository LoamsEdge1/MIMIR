r"""
MIMIR — Phase 2, build order step 3: local model benchmark.

Decides which local model becomes rung 0. Measures two things that matter:

  1. Speed        — tokens/sec. Rung 0 handles every request, so latency here
                    is felt on every interaction.
  2. Reliability  — can it emit valid JSON and classify intent correctly?
                    A model that can't do this escalates constantly, and the
                    subscription becomes the bottleneck instead of the GPU.

Reliability outweighs speed. A fast model that misclassifies is worse than a
slow one that doesn't.

Usage:
    .\.venv\Scripts\python.exe scripts\benchmark_local.py
"""

import json
import statistics
import sys
import time
from datetime import date
from pathlib import Path

import httpx
import yaml

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "config.yaml"
PROMPT = REPO / "config" / "classifier_prompt.txt"

sys.path.insert(0, str(REPO / "src"))
from mimir.router.chaining import apply as apply_chaining  # noqa: E402

# Single source of truth — the classifier prompt lives in config, so the
# benchmark measures the same prompt the router will actually use.
SYSTEM = PROMPT.read_text(encoding="utf-8")

CASES = [
    ("what's my GPU doing right now", "chat"),
    ("open the orb console", "app_control"),
    ("close chrome", "app_control"),
    ("find every csv in downloads from this month", "file_op"),
    ("move those into a folder called sorted", "file_op"),
    ("delete the temp files in my documents folder", "file_op"),
    ("write a python script that parses this csv", "code"),
    ("fix the bug in my router module", "code"),
    ("compare the last three quarters of revenue and tell me what changed", "analysis"),
    ("summarise this document and pull out the key risks", "analysis"),
    ("what's NVDA trading at and should I be watching it", "financial"),
    ("screen for tickers with unusual volume today", "financial"),
    ("download the report, rename it, and email it to my advisor", "multistep"),
    ("index my project folder then tell me what changed this week", "multistep"),
    ("hey", "chat"),
    ("asdkjh qwe", "unknown"),
]


def ollama(host, model, prompt, timeout=180):
    """One generation. Returns (text, tokens_per_sec, seconds)."""
    t0 = time.perf_counter()
    r = httpx.post(
        f"{host}/api/generate",
        json={
            "model": model,
            "system": SYSTEM,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=timeout,
    )
    r.raise_for_status()
    d = r.json()
    wall = time.perf_counter() - t0
    ec, ed = d.get("eval_count", 0), d.get("eval_duration", 0)
    tps = (ec / (ed / 1e9)) if ed else 0.0
    return d.get("response", ""), tps, wall


def score(model, host):
    print(f"\n  {model}")
    print("  " + "-" * 58)

    try:
        ollama(host, model, "warmup", timeout=300)  # load into VRAM first
    except Exception as e:
        print(f"  FAILED to load: {e}")
        return None

    speeds, walls, valid, correct, misses = [], [], 0, 0, []

    for prompt, expected in CASES:
        try:
            text, tps, wall = ollama(host, model, prompt)
        except Exception as e:
            misses.append((prompt, expected, f"error: {e}"))
            continue

        speeds.append(tps)
        walls.append(wall)

        try:
            obj = json.loads(text)
        except json.JSONDecodeError:
            misses.append((prompt, expected, "invalid json"))
            continue

        valid += 1
        obj = apply_chaining(prompt, obj)  # deterministic pre-check, as in the router
        got = str(obj.get("task_class", "")).strip().lower()
        if got == expected:
            correct += 1
        else:
            misses.append((prompt, expected, got or "missing"))

        print(f"  {'ok ' if got == expected else 'MISS'}  {expected:<12} {prompt[:40]}")

    n = len(CASES)
    return {
        "model": model,
        "tokens_per_sec": round(statistics.mean(speeds), 1) if speeds else 0,
        "median_latency_s": round(statistics.median(walls), 2) if walls else 0,
        "json_valid_pct": round(100 * valid / n, 1),
        "class_accuracy_pct": round(100 * correct / n, 1),
        "misses": misses,
    }


def main():
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    host = "http://127.0.0.1:11434"
    candidates = [cfg["models"]["local"], cfg["models"]["local_alt"]]

    print(f"MIMIR local model benchmark — {len(CASES)} cases per model")
    print(f"Candidates: {', '.join(candidates)}")

    results = [r for r in (score(m, host) for m in candidates) if r]
    if not results:
        print("\nNo model completed. Is Ollama running?")
        sys.exit(1)

    print("\n" + "=" * 74)
    print(f"{'MODEL':<34}{'TOK/S':>9}{'MEDIAN':>9}{'JSON%':>10}{'ACCURACY%':>12}")
    print("-" * 74)
    for r in results:
        print(
            f"{r['model']:<34}{r['tokens_per_sec']:>9}"
            f"{r['median_latency_s']:>8}s{r['json_valid_pct']:>10}"
            f"{r['class_accuracy_pct']:>12}"
        )
    print("=" * 74)

    # Reliability first: accuracy decides, speed only breaks near-ties.
    best = max(results, key=lambda r: (r["class_accuracy_pct"], r["tokens_per_sec"]))
    print(f"\nRECOMMENDED rung 0: {best['model']}")
    print("Set this as models.local in config/config.yaml.")

    if best["class_accuracy_pct"] < 70:
        print(
            "\nWARNING: accuracy below 70%. Neither candidate classifies reliably.\n"
            "Options: tighten the classifier prompt, add few-shot examples, or\n"
            "route classification to rung 1 and accept the cost."
        )

    for r in results:
        if r["misses"]:
            print(f"\nMisses — {r['model']}:")
            for prompt, expected, got in r["misses"]:
                print(f"  expected {expected:<12} got {got:<14} | {prompt[:44]}")

    out = Path(cfg["data_root"]) / "logs" / f"benchmark-{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
