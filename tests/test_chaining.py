"""Tests for deterministic chaining detection."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mimir.router.chaining import apply, looks_multistep  # noqa: E402

CHAINED = [
    "download the report, rename it, and email it to my advisor",
    "index my project folder then tell me what changed this week",
    "move those files then commit the change",
    "unzip the archive and install the package",
    "save the file, then push it",
]

SINGLE = [
    "find every csv in downloads from this month",
    "move those into a folder called sorted",
    "compare the last three quarters of revenue and tell me what changed",
    "summarise this document and pull out the key risks",
    "what's my GPU doing right now",
    "hey",
    "what's NVDA trading at",
    "show me the files and explain what they do",
]


def test_chained_detected():
    for text in CHAINED:
        assert looks_multistep(text), f"missed chaining: {text}"


def test_single_not_flagged():
    for text in SINGLE:
        assert not looks_multistep(text), f"false positive: {text}"


def test_apply_overrides_and_records_reason():
    out = apply(
        "download the report then email it",
        {"task_class": "file_op", "confidence": 0.9},
    )
    assert out["task_class"] == "multistep"
    assert out["task_class_model"] == "file_op"
    assert out["override"] == "deterministic_chaining"


def test_apply_leaves_single_tasks_alone():
    original = {"task_class": "file_op", "confidence": 0.9}
    out = apply("move those into a folder called sorted", dict(original))
    assert out["task_class"] == "file_op"
    assert "override" not in out
