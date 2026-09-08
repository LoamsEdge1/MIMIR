"""
Tests for the cloud ladder wrapper.

Real calls are slow and spend subscription budget, so there is exactly one —
the cheapest rung — and everything else asserts against a faked subprocess.
The fake sits at `subprocess.run`, which keeps argv construction, exit-code
handling and the counters all under test.

Counters are redirected to a tmp directory. A test suite that decrements the
real daily budget is a test suite that changes the thing it measures.
"""

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mimir import config  # noqa: E402
from mimir.llm import cloud  # noqa: E402

needs_cli = pytest.mark.skipif(not cloud.available(), reason="claude CLI not on PATH")


@pytest.fixture(autouse=True)
def isolated_counters(tmp_path, monkeypatch):
    """Point {data_root}/data at a tmp dir for every test in this file."""
    monkeypatch.setattr(config, "data_root", lambda: tmp_path)


def completed(returncode=0, payload=None, stdout=None, stderr=""):
    """A CompletedProcess shaped like the real CLI's JSON output."""
    if stdout is None:
        body = {"type": "result", "subtype": "success", "is_error": returncode != 0}
        body.update(payload or {})
        stdout = json.dumps(body)
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout=stdout, stderr=stderr)


@pytest.fixture
def fake_cli(monkeypatch):
    """
    Replaces the subprocess call and records how it was invoked.

    `calls` holds (argv, kwargs) per invocation; set `.result` to change what
    comes back, or `.raises` to make the call blow up.
    """

    class Recorder:
        def __init__(self):
            self.calls = []
            self.result = completed(payload={"result": "hello", "session_id": "abc-123"})
            self.raises = None

        def __call__(self, argv, **kwargs):
            self.calls.append((argv, kwargs))
            if self.raises is not None:
                raise self.raises
            return self.result

        @property
        def argv(self):
            return self.calls[-1][0]

        @property
        def kwargs(self):
            return self.calls[-1][1]

    recorder = Recorder()
    monkeypatch.setattr(cloud.subprocess, "run", recorder)
    return recorder


# ------------------------------------------------------- command construction


@pytest.mark.parametrize("rung", [1, 2, 3])
def test_argv_is_correct_for_each_rung(rung):
    argv = cloud.build_argv("summarise this", rung)
    assert argv == [
        cloud._executable(),
        "-p",
        "--model",
        config.get(f"models.rung_{rung}"),
        "--output-format",
        "json",
        "--strict-mcp-config",
        "--disallowedTools",
        "*",
        "--",
        "summarise this",
    ]


def test_default_grants_no_tools():
    """
    MIMIR's gate stays authoritative. Verified on the CLI 2026-09-08:
    --allowedTools does not restrict, a wildcard deny does.
    """
    argv = cloud.build_argv("hello", 1)
    assert "--disallowedTools" in argv
    assert argv[argv.index("--disallowedTools") + 1] == "*"
    assert "--allowedTools" not in argv


def test_scoped_tools_replace_the_blanket_deny():
    argv = cloud.build_argv("read it", 2, allowed_tools=["Read", "Grep"])
    assert argv[argv.index("--allowedTools") + 1] == "Read,Grep"
    # The two cannot be combined: a wildcard deny wins over an explicit allow.
    assert "--disallowedTools" not in argv


def test_resume_is_appended_for_continuity():
    argv = cloud.build_argv("and then?", 1, session_id="sess-9")
    assert argv[argv.index("--resume") + 1] == "sess-9"


def test_prompt_is_positional_after_a_double_dash():
    """A prompt starting with a dash is text, not a flag."""
    argv = cloud.build_argv("--version is what I want to know", 1)
    assert argv[-2:] == ["--", "--version is what I want to know"]


@pytest.mark.parametrize("rung", [0, 4, -1])
def test_bad_rung_raises(rung):
    """A caller bug, not a runtime condition — and it must not spend budget."""
    with pytest.raises(ValueError):
        cloud.build_argv("hello", rung)
    with pytest.raises(ValueError):
        cloud.run("hello", rung)
    assert cloud.escalation_counts() == {1: 0, 2: 0, 3: 0}


def test_shell_is_false(fake_cli):
    """Prompts carry user text. A shell string is never built."""
    cloud.run("rm -rf / ; echo $(whoami)", 1)
    assert fake_cli.kwargs["shell"] is False
    assert isinstance(fake_cli.argv, list)
    assert fake_cli.argv[-1] == "rm -rf / ; echo $(whoami)"


def test_timeout_is_always_explicit(fake_cli):
    cloud.run("hello", 1)
    assert fake_cli.kwargs["timeout"] == config.get("routing.cloud_timeout_seconds")

    cloud.run("hello", 1, timeout=7)
    assert fake_cli.kwargs["timeout"] == 7


# -------------------------------------------------------------------- results


def test_success_returns_text_and_session(fake_cli):
    result = cloud.run("hello", 2)
    assert result == {
        "text": "hello",
        "ok": True,
        "rung": 2,
        "session_id": "abc-123",
        "error": None,
        "seconds": result["seconds"],
    }
    assert result["seconds"] >= 0


def test_timeout_returns_not_ok_without_raising(fake_cli):
    fake_cli.raises = subprocess.TimeoutExpired(cmd="claude", timeout=120)
    result = cloud.run("hello", 1, timeout=120)
    assert result["ok"] is False
    assert "timed out" in result["error"]
    assert result["text"] == ""


def test_missing_cli_returns_not_ok(fake_cli):
    fake_cli.raises = FileNotFoundError("claude")
    result = cloud.run("hello", 1)
    assert result["ok"] is False
    assert "not found on PATH" in result["error"]


def test_nonzero_exit_captures_stderr(fake_cli):
    """
    Modelled on the real failure shape: exit 1, stderr tagged, and a body that
    still says subtype "success". Both signals are read.
    """
    fake_cli.result = completed(
        returncode=1,
        payload={"is_error": True, "api_error_status": 404, "result": "model does not exist"},
        stderr="[claude-code:unrecognized_model] {}",
    )
    result = cloud.run("hello", 3)
    assert result["ok"] is False
    assert "unrecognized_model" in result["error"]
    assert "404" in result["error"]
    # Never a silently empty string presented as an answer.
    assert result["text"] == ""


def test_error_flag_without_nonzero_exit_still_fails(fake_cli):
    fake_cli.result = completed(payload={"is_error": True, "result": "something went wrong"})
    result = cloud.run("hello", 1)
    assert result["ok"] is False
    assert "something went wrong" in result["error"]


def test_unparseable_output_is_an_error_not_an_answer(fake_cli):
    fake_cli.result = completed(returncode=0, stdout="<html>proxy error</html>")
    result = cloud.run("hello", 1)
    assert result["ok"] is False
    assert result["text"] == ""
    assert "unparseable" in result["error"]


# ------------------------------------------------------------------- counters


def test_counters_increment_on_success(fake_cli):
    cloud.run("hello", 1)
    cloud.run("hello", 3)
    cloud.run("hello", 3)
    assert cloud.escalation_counts() == {1: 1, 2: 0, 3: 2}


def test_counters_increment_on_failure(fake_cli):
    """A failed call still spent budget."""
    fake_cli.result = completed(returncode=1, stderr="boom")
    cloud.run("hello", 2)

    fake_cli.raises = subprocess.TimeoutExpired(cmd="claude", timeout=1)
    cloud.run("hello", 2)

    assert cloud.escalation_counts()[2] == 2


def test_counters_survive_a_restart(fake_cli, tmp_path, monkeypatch):
    """
    Reloading the module is the simulated restart: anything held only in
    memory disappears, and a counter that resets on restart cannot enforce a
    daily budget.
    """
    cloud.run("hello", 1)
    cloud.run("hello", 2)
    assert (tmp_path / "data" / "escalations.json").exists()

    restarted = importlib.reload(cloud)
    monkeypatch.setattr(config, "data_root", lambda: tmp_path)
    assert restarted.escalation_counts() == {1: 1, 2: 1, 3: 0}


def test_counters_ignore_a_previous_day(tmp_path):
    """The budget is daily. Yesterday's spend is not this morning's problem."""
    store = tmp_path / "data" / "escalations.json"
    store.parent.mkdir(parents=True)
    store.write_text(json.dumps({"date": "2000-01-01", "counts": {"1": 9, "2": 9, "3": 9}}))
    assert cloud.escalation_counts() == {1: 0, 2: 0, 3: 0}


def test_corrupt_counter_file_does_not_crash_the_call(fake_cli, tmp_path):
    store = tmp_path / "data" / "escalations.json"
    store.parent.mkdir(parents=True)
    store.write_text("{not json")
    assert cloud.run("hello", 1)["ok"] is True
    assert cloud.escalation_counts()[1] == 1


def test_reset_daily_counts(fake_cli):
    cloud.run("hello", 1)
    cloud.reset_daily_counts()
    assert cloud.escalation_counts() == {1: 0, 2: 0, 3: 0}


def test_warns_at_the_configured_threshold_and_does_not_block(fake_cli, caplog):
    threshold = config.get("routing.daily_escalation_warn")

    with caplog.at_level("WARNING", logger="mimir.llm.cloud"):
        for _ in range(threshold - 1):
            cloud.run("hello", 1)
        assert not caplog.records, "warned before the threshold"

        result = cloud.run("hello", 1)

    assert any("escalations today" in r.message for r in caplog.records)
    assert result["ok"] is True, "the warning must not block the call"
    assert cloud.escalation_counts()[1] == threshold


# ----------------------------------------------------------------- real call


@needs_cli
def test_one_real_call_to_the_cheapest_rung():
    """The only call here that spends budget. Rung 1, minimal prompt."""
    result = cloud.run("Reply with exactly: ready", rung=1)
    assert result["ok"] is True, result["error"]
    assert result["text"].strip()
    assert result["error"] is None
    assert result["rung"] == 1
    assert isinstance(result["session_id"], str) and result["session_id"]
    assert cloud.escalation_counts()[1] == 1
