"""
Deterministic multi-step detection — runs BEFORE the model classifier.

Why this exists
---------------
The Phase 2 step 3 benchmark found that both local candidates missed EVERY
multistep case, classifying chained requests as single file operations.

That is the dangerous direction. Calling "download the report, rename it, and
email it" a file_op means MIMIR under-escalates and executes a chained,
side-effecting task as one simple action.

Chaining is structural, not semantic, so it does not need a model. This check
is deterministic, free, and runs first. The model keeps the judgment calls it
is actually good at.

Bias: false positives are acceptable. Over-escalating costs a rung. Under-
escalating executes something the user did not sanction.
"""

import re

# Verbs that CHANGE something. Reporting verbs (tell, show, explain, compare,
# summarise) are deliberately excluded — "compare X and tell me" is one task,
# not two, and counting them would over-trigger on ordinary analysis requests.
SIDE_EFFECTING = {
    "download", "upload", "install", "uninstall", "rename", "move", "copy",
    "delete", "remove", "email", "send", "post", "publish", "create", "make",
    "write", "save", "export", "import", "index", "open", "close", "launch",
    "run", "execute", "schedule", "archive", "extract", "unzip", "zip",
    "commit", "push", "pull", "deploy", "backup", "restore", "convert",
    "organise", "organize", "sort", "clean", "merge", "split",
}

# Explicit sequencing language. "and" alone is NOT here — it joins single tasks
# far too often ("find X and show me") to be a reliable signal.
SEQUENCERS = (
    r"\bthen\b",
    r"\bafter that\b",
    r"\bafterwards\b",
    r"\bfollowed by\b",
    r"\bonce that\b",
    r"\bnext,",
    r"\bfinally,",
)


def side_effecting_verbs(text: str) -> set[str]:
    """Distinct side-effecting verbs present in the text."""
    words = set(re.findall(r"[a-z]+", text.lower()))
    return words & SIDE_EFFECTING


def has_sequencer(text: str) -> bool:
    low = text.lower()
    return any(re.search(p, low) for p in SEQUENCERS)


def looks_multistep(text: str) -> bool:
    """
    True when the request chains work.

    Triggers on either:
      - two or more distinct side-effecting verbs, or
      - one side-effecting verb plus explicit sequencing language.
    """
    verbs = side_effecting_verbs(text)
    if len(verbs) >= 2:
        return True
    return bool(verbs) and has_sequencer(text)


def apply(text: str, classification: dict) -> dict:
    """
    Override the model's task_class when chaining is detected.

    Records the override so the reason is visible in logs rather than being a
    silent correction.
    """
    if not looks_multistep(text):
        return classification

    if classification.get("task_class") != "multistep":
        classification["task_class_model"] = classification.get("task_class")
        classification["task_class"] = "multistep"
        classification["override"] = "deterministic_chaining"
    return classification
