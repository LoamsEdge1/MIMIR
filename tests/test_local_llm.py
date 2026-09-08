"""
Tests for the Ollama client.

Ollama runs on this machine, so these are real calls rather than mocks. A
mocked HTTP client would pass while the actual VRAM stayed allocated, which is
precisely the failure the module is written to catch. Anything that genuinely
cannot be produced against a live service — a model emitting unparseable
output while `format: json` is set — is faked at the seam, not below it.

Every test skips cleanly when Ollama is unreachable so the suite still runs on
a machine without it.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mimir import config  # noqa: E402
from mimir.llm import local  # noqa: E402

HEALTH = local.LocalClient().health()
ollama_up = pytest.mark.skipif(
    not HEALTH["reachable"] or not HEALTH["model_present"],
    reason=f"ollama not reachable or model missing: {HEALTH}",
)
gpu_present = pytest.mark.skipif(
    local.gpu_used_mb() is None, reason="no NVIDIA GPU telemetry available"
)


@pytest.fixture
def client():
    return local.LocalClient()


# --------------------------------------------------------------- config only


def test_model_and_host_come_from_config(client):
    """No literals in src/. A model swap is a config edit, nothing more."""
    assert client.model == config.get("models.local")
    assert client.host == config.get("ollama.host").rstrip("/")


# ------------------------------------------------------------------ parsing


def test_parse_json_returns_none_on_prose():
    assert local.parse_json("Sure! Here is the classification you asked for.") is None


def test_parse_json_returns_none_on_truncated_object():
    assert local.parse_json('{"task_class": "file_op", "targets": [') is None


def test_parse_json_returns_none_on_non_object():
    """Valid JSON that is not an object is still unusable to the router."""
    assert local.parse_json("[1, 2, 3]") is None


def test_generate_json_returns_none_not_an_exception(client, monkeypatch):
    """
    The contract the router depends on: unparseable output is None, never a
    raise and never a repaired guess. Faked at the generate() seam because
    Ollama's `format: json` will not emit prose on demand.
    """
    monkeypatch.setattr(
        client,
        "generate",
        lambda *a, **kw: {"text": "I think this is a file operation.", "tokens_per_sec": 70.0, "seconds": 0.1},
    )
    assert client.generate_json("anything") is None


def test_generate_json_does_not_repair_malformed_output(client, monkeypatch):
    """A JSON object embedded in prose is still a failure. Do not fish it out."""
    monkeypatch.setattr(
        client,
        "generate",
        lambda *a, **kw: {
            "text": 'Here you go: {"task_class": "file_op"} — hope that helps!',
            "tokens_per_sec": 70.0,
            "seconds": 0.1,
        },
    )
    assert client.generate_json("anything") is None


# --------------------------------------------------------------- generation


@ollama_up
def test_generate_returns_text_and_plausible_speed(client):
    result = client.generate("Reply with the single word: ready", timeout=60)
    assert result["text"].strip()
    assert 5 < result["tokens_per_sec"] < 1000, result["tokens_per_sec"]
    assert 0 < result["seconds"] < 60


@ollama_up
def test_generate_json_returns_a_dict(client):
    obj = client.generate_json(
        'Return {"ok": true} and nothing else.',
        system="Reply with JSON only.",
        timeout=60,
    )
    assert isinstance(obj, dict)


@ollama_up
def test_classify_uses_the_shared_prompt_and_returns_the_schema(client):
    obj = client.classify("what's NVDA trading at", timeout=60)
    assert isinstance(obj, dict)
    assert obj.get("task_class") == "financial"


# ----------------------------------------------------------- load and unload


@ollama_up
@gpu_present
def test_unload_measurably_frees_vram(client):
    """
    The one that matters for game mode. Measured with pynvml, not assumed from
    a clean return.
    """
    client.load()
    assert client.is_loaded()
    held = client.resident_vram_mb()
    assert held and held > local._VRAM_CHECK_FLOOR_MB

    before = local.gpu_used_mb()
    client.unload()
    after = local.gpu_used_mb()

    assert not client.is_loaded()
    assert after < before, f"VRAM did not fall: {before} -> {after} MB"
    assert client.last_unload["freed_mb"] > 0


@ollama_up
def test_load_after_unload_restores_a_working_model(client):
    client.unload()
    assert not client.is_loaded()

    client.load()
    assert client.is_loaded()
    assert client.generate("Reply with the single word: ready", timeout=60)["text"].strip()


# ------------------------------------------------------------------- health


@ollama_up
def test_health_reports_real_vram_when_loaded(client):
    """
    The dashboard's system panel renders this number. A field that is always
    None is a dead field, so assert an actual integer footprint rather than
    'int or None'.
    """
    client.load()
    status = client.health()
    assert status["reachable"] is True
    assert status["model_present"] is True
    assert isinstance(status["vram_mb"], int)
    assert status["vram_mb"] > local._VRAM_CHECK_FLOOR_MB


@ollama_up
def test_health_reports_no_vram_when_unloaded(client):
    """The other state: reachable and installed, but holding nothing."""
    client.unload()
    status = client.health()
    assert status["reachable"] is True
    assert status["model_present"] is True
    assert status["vram_mb"] is None


def test_health_reports_unreachable_without_raising():
    """
    Ollama being down is a routing input, not a crash. Port 1 is reserved and
    never listening.
    """
    status = local.LocalClient(host="http://127.0.0.1:1").health()
    assert status == {"reachable": False, "model_present": False, "vram_mb": None}


def test_generate_raises_typed_error_when_unreachable():
    """
    generate() raises where health() reports, so the router can tell a dead
    service apart from a bad answer. Both escalate; only one is worth alerting on.
    """
    dead = local.LocalClient(host="http://127.0.0.1:1")
    with pytest.raises(local.OllamaUnreachable):
        dead.generate("hello", timeout=5)
