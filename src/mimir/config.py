"""
Configuration access — the single origin for every path, model name and host.

Nothing in `src/` may carry a literal model name, host, or path. Modules ask
this loader instead, so a model swap or a host change is a one-line edit in
`config/config.yaml` rather than a search across the tree.

A missing key raises rather than defaulting silently. A router that quietly
falls back to a built-in default is a router running on a configuration nobody
wrote down.
"""

from __future__ import annotations

import functools
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = REPO_ROOT / "config"
CONFIG_FILE = CONFIG_DIR / "config.yaml"
CLASSIFIER_PROMPT_FILE = CONFIG_DIR / "classifier_prompt.txt"

_MISSING = object()


@functools.cache
def load() -> dict[str, Any]:
    """The parsed config, read once per process."""
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"config not found: {CONFIG_FILE}")
    data = yaml.safe_load(CONFIG_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"config is not a mapping: {CONFIG_FILE}")
    return data


def reload() -> dict[str, Any]:
    """Drop the cache and re-read from disk. For tests and config edits."""
    load.cache_clear()
    return load()


def get(dotted: str, default: Any = _MISSING) -> Any:
    """
    Look up a nested key by dotted path, e.g. ``get("models.local")``.

    Raises KeyError naming the full path when the key is absent and no default
    was given — a typo in a config key should fail loudly at the call site, not
    surface later as a request routed to the wrong model.
    """
    node: Any = load()
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            if default is not _MISSING:
                return default
            raise KeyError(f"missing config key '{dotted}' in {CONFIG_FILE}")
        node = node[part]
    return node


def data_root() -> Path:
    """Runtime state root. Lives outside the repo by design."""
    return Path(get("data_root"))


@functools.cache
def classifier_prompt() -> str:
    """
    The shared classifier system prompt.

    One copy, read from disk. The benchmark and the router must classify with
    the same words or the benchmark measures a prompt that never ships.
    """
    return CLASSIFIER_PROMPT_FILE.read_text(encoding="utf-8")
