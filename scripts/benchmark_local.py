r"""
MIMIR — local model benchmark.

Measures five things, in order of how much they matter:

  1. UNDER-ESCALATION   Did it route a hard task to a rung too weak for it?
                        This is the failure that breaks things. A destructive
                        chained task executed as a simple file op is the worst
                        outcome the router can produce.

  2. HALLUCINATED       Did it invent targets the user never named? Acting on
     TARGETS            an imagined file path is the second worst outcome.

  3. JSON VALIDITY      Rung 0 must emit parseable structured output. Below
                        ~98% the router cannot function.

  4. CLASS ACCURACY     Useful, but the least consequential. Mislabelling code
                        as app_control costs a rung, not data.

  5. CONFIDENCE         Is it confident when right and uncertain when wrong?
     CALIBRATION        A model confidently wrong is worse than one that flags
                        doubt, because the confidence gate trusts the number.

Over-escalation is reported but NOT penalised. It costs a rung; under-
escalation costs correctness.

Usage:
    .\.venv\Scripts\python.exe scripts\benchmark_local.py
"""

import json
import re
import statistics
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "scripts"))

from bench_cases import CASES, HALLUCINATION_PROBES  # noqa: E402
from mimir import config  # noqa: E402
from mimir.llm import local  # noqa: E402
from mimir.router.chaining import apply as apply_chaining  # noqa: E402

# The benchmark drives the same client the router does. Two code paths to the
# same service drift, and then the benchmark measures something that never
# ships. The classifier prompt comes from config for the same reason.
SYSTEM = config.classifier_prompt()


def expected_rung(task_class, confidence, cfg):
    """
    The tier the router WOULD pick. Mirrors router/tiers.py so the benchmark
    tests the real rule rather than a restatement of it.
    """
    hard = cfg["routing"]["hard_task_classes"]
    threshold = cfg["routing"]["confidence_threshold"]
    if task_class in hard:
        return 2
    if confidence < threshold or task_class == "unknown":
        return 1
    return 0


def invented_targets(prompt, targets):
    """
    Heuristic: a target is invented when most of its words never appear in the
    user's own words. Catches the damaging case — a model producing a filename
    or path the user never mentioned.
    """
    said = set(re.findall(r"[a-z0-9]+", prompt.lower()))
    bad = []
    for t in targets or []:
        words = re.findall(r"[a-z0-9]+", str(t).lower())
        if not words:
            continue
        unseen = [w for w in words if w not in said]
        if len(unseen) > len(words) / 2:
            bad.append(str(t))
    return bad


def classify(client, prompt):
    """One classification through the shipping client. Returns (text, tok/s, wall)."""
    r = client.generate(prompt, system=SYSTEM, json_mode=True)
    return r["text"], r["tokens_per_sec"], r["seconds"]


def score(model, cfg):
    print(f"\n  {model}  ({len(CASES)} cases + {len(HALLUCINATION_PROBES)} probes)")

    client = local.LocalClient(model=model)
    try:
        client.load()
    except local.LocalLLMError as e:
        print(f"  FAILED to load: {e}")
        return None

    speeds, walls = [], []
    valid = correct = under = over = 0
    conf_right, conf_wrong = [], []
    misses, invented = [], []

    for prompt, gold in CASES:
        try:
            text, tps, wall = classify(client, prompt)
        except local.LocalLLMError as e:
            misses.append((prompt, gold, f"error: {e}"))
            continue
        speeds.append(tps)
        walls.append(wall)

        # parse_json is the router's own parser — same None-on-garbage rule.
        obj = local.parse_json(text)
        if obj is None:
            misses.append((prompt, gold, "invalid json"))
            continue

        valid += 1
        obj = apply_chaining(prompt, obj)
        got = str(obj.get("task_class", "")).strip().lower()
        try:
            conf = float(obj.get("confidence", 0))
        except (TypeError, ValueError):
            conf = 0.0

        if got == gold:
            correct += 1
            conf_right.append(conf)
        else:
            conf_wrong.append(conf)
            misses.append((prompt, gold, got or "missing"))

        # Escalation correctness — the metric that matters most.
        want = expected_rung(gold, 1.0, cfg)
        have = expected_rung(got, conf, cfg)
        if have < want:
            under += 1
        elif have > want:
            over += 1

        bad = invented_targets(prompt, obj.get("targets"))
        if bad:
            invented.append((prompt, bad))

    # Probes: prompts naming nothing. Any target here is fabricated.
    probe_invented = []
    for prompt in HALLUCINATION_PROBES:
        try:
            text, _, _ = classify(client, prompt)
        except local.LocalLLMError:
            continue
        obj = local.parse_json(text)
        if obj is None:
            continue
        bad = invented_targets(prompt, obj.get("targets"))
        if bad:
            probe_invented.append((prompt, bad))

    # Free the VRAM before the next candidate loads. Two 7-8B models resident
    # at once does not fit in 8GB, and a swap mid-run would distort tok/s.
    try:
        client.unload()
    except local.LocalLLMError as e:
        print(f"  WARNING: {model} did not unload: {e}")

    n = len(CASES)
    return {
        "model": model,
        "tokens_per_sec": round(statistics.mean(speeds), 1) if speeds else 0,
        "median_latency_s": round(statistics.median(walls), 2) if walls else 0,
        "json_valid_pct": round(100 * valid / n, 1),
        "class_accuracy_pct": round(100 * correct / n, 1),
        "under_escalation_pct": round(100 * under / n, 1),
        "over_escalation_pct": round(100 * over / n, 1),
        "invented_target_cases": len(invented) + len(probe_invented),
        "mean_conf_when_right": round(statistics.mean(conf_right), 2) if conf_right else 0,
        "mean_conf_when_wrong": round(statistics.mean(conf_wrong), 2) if conf_wrong else 0,
        "misses": misses,
        "invented": invented + probe_invented,
    }


def main():
    cfg = config.load()
    candidates = [config.get("models.local"), config.get("models.benchmark_alt")]

    health = local.LocalClient().health()
    if not health["reachable"]:
        print(f"Ollama unreachable at {config.get('ollama.host')}. Is it running?")
        sys.exit(1)

    print(f"MIMIR local benchmark — {', '.join(candidates)}")
    results = [r for r in (score(m, cfg) for m in candidates) if r]
    if not results:
        print("\nNo model completed.")
        sys.exit(1)

    print("\n" + "=" * 78)
    print(f"{'MODEL':<32}{'UNDER-ESC':>11}{'INVENTED':>10}{'JSON%':>8}{'ACC%':>8}{'TOK/S':>9}")
    print("-" * 78)
    for r in results:
        print(
            f"{r['model']:<32}{r['under_escalation_pct']:>10}%"
            f"{r['invented_target_cases']:>10}{r['json_valid_pct']:>8}"
            f"{r['class_accuracy_pct']:>8}{r['tokens_per_sec']:>9}"
        )
    print("=" * 78)

    for r in results:
        gap = r["mean_conf_when_right"] - r["mean_conf_when_wrong"]
        print(
            f"\n{r['model']}"
            f"\n  confidence when right {r['mean_conf_when_right']} / "
            f"when wrong {r['mean_conf_when_wrong']}  (gap {gap:+.2f})"
            f"\n  over-escalation {r['over_escalation_pct']}% (not penalised)"
        )
        if gap <= 0.05:
            print("  WARNING: confidence does not separate right from wrong.")
            print("  The confidence gate cannot be trusted for this model.")

    # Ranking: under-escalation first, then invented targets, then accuracy.
    best = min(
        results,
        key=lambda r: (
            r["under_escalation_pct"],
            r["invented_target_cases"],
            -r["class_accuracy_pct"],
        ),
    )
    print(f"\nRECOMMENDED rung 0: {best['model']}")

    for r in results:
        if r["invented"]:
            print(f"\nInvented targets — {r['model']}:")
            for prompt, bad in r["invented"][:8]:
                print(f"  {bad} | {prompt[:46]}")
        if r["misses"]:
            print(f"\nMisses — {r['model']} ({len(r['misses'])}):")
            for prompt, gold, got in r["misses"][:14]:
                print(f"  want {gold:<12} got {got:<14} | {prompt[:42]}")

    out = config.data_root() / "logs" / f"benchmark-{date.today().isoformat()}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    main()
