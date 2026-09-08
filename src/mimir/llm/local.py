r"""
Ollama client — rung 0.

Why this is not just an HTTP call
---------------------------------
The router needs three things the benchmark's one-off `httpx.post` never had:

  1. **Load/unload control.** The game watchdog frees VRAM by unloading the
     model. Without a client that can do that — and prove it did — game mode
     is a claim, not a feature.
  2. **Honest failure.** Unparseable JSON returns None so the caller escalates.
     Nothing here repairs, retries, or guesses at malformed output; a plausible
     reconstruction of what the model meant is exactly the hallucination the
     router exists to prevent (CLAUDE.md constraint 5).
  3. **Explicit timeouts.** A hung local call must never block the daemon.

Ollama being unreachable is a normal condition, not a crash: `health()` reports
it and the router escalates to rung 1. It is never a reason to try a second
local model (CLAUDE.md constraint 4).

Model name, host and keep-alive all come from `config/config.yaml`. There are
no literals here.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import httpx

from mimir import config

try:  # pynvml is how unload() proves it freed VRAM rather than assuming it.
    import pynvml
except ImportError:  # pragma: no cover - environment without NVIDIA bindings
    pynvml = None  # type: ignore[assignment]

log = logging.getLogger(__name__)

# Below this, a resident model is small enough that driver-level noise could
# swamp the measurement, so unload() warns instead of failing the check.
_VRAM_CHECK_FLOOR_MB = 256


class LocalLLMError(RuntimeError):
    """Any local-inference failure. The router escalates; it never retries."""


class OllamaUnreachable(LocalLLMError):
    """The Ollama service did not answer. Expected condition, not a bug."""


class VramNotReleased(LocalLLMError):
    """unload() returned but VRAM is still held. Game mode depends on this."""


def gpu_used_mb(index: int = 0) -> int | None:
    """
    Device-wide VRAM in use, in MB. None when there is no NVIDIA GPU or the
    bindings are unavailable — callers must treat the measurement as optional
    rather than assuming a number.
    """
    if pynvml is None:
        return None
    try:
        pynvml.nvmlInit()
        try:
            handle = pynvml.nvmlDeviceGetHandleByIndex(index)
            return int(pynvml.nvmlDeviceGetMemoryInfo(handle).used // (1024 * 1024))
        finally:
            pynvml.nvmlShutdown()
    except Exception as exc:  # pragma: no cover - driver-dependent
        log.debug("pynvml unavailable: %s", exc)
        return None


def _strip_tag(name: str) -> str:
    """Ollama reports an implicit ':latest' tag; compare without it."""
    return str(name).removesuffix(":latest").strip()


def _same_model(a: str, b: str) -> bool:
    return _strip_tag(a) == _strip_tag(b)


def parse_json(text: str) -> dict | None:
    """
    Parse structured output. Returns None on anything that is not a JSON
    object.

    One attempt. No repair, no retry, no fishing the first {...} out of prose.
    None is the honest answer and the caller escalates.
    """
    try:
        obj = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        log.warning("local model emitted unparseable JSON (%d chars)", len(text or ""))
        return None
    if not isinstance(obj, dict):
        log.warning("local model emitted JSON that is not an object: %s", type(obj).__name__)
        return None
    return obj


class LocalClient:
    """Ollama HTTP client for a single model."""

    def __init__(
        self,
        model: str | None = None,
        host: str | None = None,
        keep_alive: str | int | None = None,
    ) -> None:
        self.model = model or config.get("models.local")
        self.host = str(host or config.get("ollama.host")).rstrip("/")
        self.keep_alive = (
            keep_alive if keep_alive is not None else config.get("ollama.keep_alive")
        )
        self.last_unload: dict[str, Any] = {}

    # ------------------------------------------------------------------ HTTP

    def _request(self, method: str, path: str, timeout: float, **kwargs: Any) -> dict:
        try:
            response = httpx.request(method, f"{self.host}{path}", timeout=timeout, **kwargs)
            response.raise_for_status()
            return response.json()
        except httpx.TimeoutException as exc:
            raise LocalLLMError(f"ollama timed out after {timeout}s on {path}") from exc
        except httpx.RequestError as exc:
            raise OllamaUnreachable(f"ollama unreachable at {self.host}: {exc}") from exc
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:200]
            raise LocalLLMError(
                f"ollama returned {exc.response.status_code} on {path}: {body}"
            ) from exc
        except ValueError as exc:  # body was not JSON
            raise LocalLLMError(f"ollama returned a non-JSON body on {path}") from exc

    # ------------------------------------------------------------ generation

    def generate(
        self,
        prompt: str,
        system: str | None = None,
        json_mode: bool = False,
        timeout: int = 180,
    ) -> dict:
        """
        One completion:

            {"text": str, "tokens_per_sec": float, "seconds": float}

        `tokens_per_sec` is Ollama's own eval timing, not wall clock — wall
        clock includes queueing and model load, which would understate
        throughput and make benchmark runs incomparable.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "keep_alive": self.keep_alive,
            "options": {"temperature": 0},
        }
        if system is not None:
            payload["system"] = system
        if json_mode:
            payload["format"] = "json"

        started = time.perf_counter()
        data = self._request("POST", "/api/generate", timeout, json=payload)
        seconds = time.perf_counter() - started

        eval_count = data.get("eval_count") or 0
        eval_ns = data.get("eval_duration") or 0
        return {
            "text": data.get("response", ""),
            "tokens_per_sec": round(eval_count / (eval_ns / 1e9), 1) if eval_ns else 0.0,
            "seconds": round(seconds, 3),
        }

    def generate_json(
        self,
        prompt: str,
        system: str | None = None,
        timeout: int = 180,
    ) -> dict | None:
        """
        Structured output, or None when the answer is not a JSON object.

        Transport failures still raise. An unreachable service and a model that
        answered badly are different problems, and collapsing them would hide a
        dead Ollama behind a classification failure.
        """
        result = self.generate(prompt, system=system, json_mode=True, timeout=timeout)
        return parse_json(result["text"])

    def classify(self, prompt: str, timeout: int = 180) -> dict | None:
        """
        Structured output under the shared classifier system prompt.

        Reads `config/classifier_prompt.txt` through the config loader. The
        benchmark and the router must classify with identical words, so there is
        exactly one copy of them and it is not in this file.
        """
        return self.generate_json(prompt, system=config.classifier_prompt(), timeout=timeout)

    # ------------------------------------------------------------- residency

    def running(self) -> list[dict]:
        """Models Ollama currently holds in memory."""
        return self._request("GET", "/api/ps", 30).get("models") or []

    def resident_vram_mb(self) -> int | None:
        """
        VRAM this model occupies per Ollama, or None when it is not loaded.
        This is the model's own footprint, not the device total.
        """
        for entry in self.running():
            if _same_model(entry.get("model", ""), self.model) or _same_model(
                entry.get("name", ""), self.model
            ):
                size = entry.get("size_vram") or 0
                return int(size // (1024 * 1024))
        return None

    def is_loaded(self) -> bool:
        return self.resident_vram_mb() is not None

    def load(self, timeout: int | None = None) -> None:
        """
        Pull the model into VRAM. An empty prompt loads without generating.

        Residency is verified afterwards: a 200 response that left nothing
        loaded is the same silent failure as an unload that frees nothing.
        """
        timeout = timeout or config.get("ollama.load_timeout_seconds", 300)
        self._request(
            "POST",
            "/api/generate",
            timeout,
            json={
                "model": self.model,
                "prompt": "",
                "stream": False,
                "keep_alive": self.keep_alive,
            },
        )
        if not self.is_loaded():
            raise LocalLLMError(f"{self.model} reported loaded but is not resident")
        log.info("loaded %s (%s MB)", self.model, self.resident_vram_mb())

    def unload(self, timeout: int | None = None) -> None:
        """
        Free VRAM with keep_alive=0. The game watchdog calls this.

        Verified two ways, because a clean return that freed nothing is the
        exact silent failure this module exists to prevent:

          - Ollama must stop reporting the model as resident. Authoritative,
            and raises on failure.
          - pynvml must show device memory actually fall. Raises when the model
            held a meaningful amount and none of it came back. Device memory is
            shared with every other process on the GPU, so a partial drop warns
            rather than fails — the alternative is a watchdog that errors
            because a game allocated while MIMIR was letting go.

        The measurement is kept on `last_unload` so game mode can log what it
        actually recovered instead of asserting that it worked.
        """
        timeout = timeout or config.get("ollama.unload_timeout_seconds", 30)
        settle = config.get("ollama.unload_settle_seconds", 8)

        before_mb = gpu_used_mb()
        held_mb = self.resident_vram_mb()

        self._request(
            "POST",
            "/api/generate",
            timeout,
            json={"model": self.model, "prompt": "", "stream": False, "keep_alive": 0},
        )

        # Ollama drops the runner asynchronously; wait for it to leave /api/ps.
        deadline = time.monotonic() + timeout
        while self.is_loaded():
            if time.monotonic() >= deadline:
                raise VramNotReleased(
                    f"{self.model} still resident {timeout}s after keep_alive=0"
                )
            time.sleep(0.25)

        # The driver reports the release a moment after the runner exits.
        after_mb = gpu_used_mb()
        if before_mb is not None and after_mb is not None:
            settle_deadline = time.monotonic() + settle
            while after_mb >= before_mb and time.monotonic() < settle_deadline:
                time.sleep(0.25)
                after_mb = gpu_used_mb()
                if after_mb is None:
                    break

        freed_mb = None if (before_mb is None or after_mb is None) else before_mb - after_mb
        self.last_unload = {
            "before_mb": before_mb,
            "after_mb": after_mb,
            "freed_mb": freed_mb,
            "model_vram_mb": held_mb,
        }
        log.info("unloaded %s: %s", self.model, self.last_unload)

        if freed_mb is None:
            log.warning("unload of %s could not be measured — no GPU telemetry", self.model)
        elif held_mb and held_mb >= _VRAM_CHECK_FLOOR_MB and freed_mb <= 0:
            raise VramNotReleased(
                f"{self.model} left /api/ps holding {held_mb} MB but device VRAM did not "
                f"fall ({before_mb} -> {after_mb} MB)"
            )
        elif held_mb and freed_mb < held_mb / 2:
            log.warning(
                "unload of %s freed %s MB of the %s MB it held — another process may have "
                "allocated during the call",
                self.model,
                freed_mb,
                held_mb,
            )

    # ---------------------------------------------------------------- health

    def health(self) -> dict:
        """
        Never raises. An unreachable Ollama is a routing input, not an
        exception — the router reads this and escalates to rung 1.

        `vram_mb` is what this model currently holds per Ollama, None when it is
        not loaded.
        """
        status: dict[str, Any] = {"reachable": False, "model_present": False, "vram_mb": None}
        try:
            data = self._request("GET", "/api/tags", 10)
        except LocalLLMError as exc:
            log.info("ollama health check failed: %s", exc)
            return status

        status["reachable"] = True
        status["model_present"] = any(
            _same_model(m.get("name", ""), self.model) or _same_model(m.get("model", ""), self.model)
            for m in data.get("models") or []
        )
        try:
            status["vram_mb"] = self.resident_vram_mb()
        except LocalLLMError as exc:  # reachable a moment ago, gone now
            log.info("ollama residency check failed: %s", exc)
        return status


# --------------------------------------------------------- module-level API
# The router talks to the one configured model. The benchmark and the tests
# build their own LocalClient when they need a different one.

_default: LocalClient | None = None


def client() -> LocalClient:
    global _default
    if _default is None:
        _default = LocalClient()
    return _default


def reset_client() -> None:
    """Drop the cached client so a config change takes effect."""
    global _default
    _default = None


def generate(
    prompt: str, system: str | None = None, json_mode: bool = False, timeout: int = 180
) -> dict:
    return client().generate(prompt, system=system, json_mode=json_mode, timeout=timeout)


def generate_json(prompt: str, system: str | None = None, timeout: int = 180) -> dict | None:
    return client().generate_json(prompt, system=system, timeout=timeout)


def classify(prompt: str, timeout: int = 180) -> dict | None:
    return client().classify(prompt, timeout=timeout)


def load() -> None:
    client().load()


def unload() -> None:
    client().unload()


def is_loaded() -> bool:
    return client().is_loaded()


def health() -> dict:
    return client().health()
