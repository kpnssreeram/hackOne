"""
Circuit breaker + hard timeout wrapper for all external calls.
On timeout or provider failure → serve cached/fixture artifact.
"""
from __future__ import annotations
import asyncio
import time
import os
from enum import Enum
from typing import Callable, Any, TypeVar, Awaitable
import logging

log = logging.getLogger("nolan.resilience")

T = TypeVar("T")

STAGE_TIMEOUTS: dict[str, float] = {
    "transcribe":    float(os.getenv("TIMEOUT_TRANSCRIBE",   "20")),
    "dna":           float(os.getenv("TIMEOUT_DNA",          "25")),
    "visions":       float(os.getenv("TIMEOUT_VISIONS",      "35")),
    "script":        float(os.getenv("TIMEOUT_SCRIPT",       "35")),
    "constitution":  float(os.getenv("TIMEOUT_CONSTITUTION", "25")),
    "revision":      float(os.getenv("TIMEOUT_REVISION",     "30")),
    "audio":         float(os.getenv("TIMEOUT_AUDIO",        "30")),
}


class BreakerState(str, Enum):
    CLOSED    = "CLOSED"     # normal
    OPEN      = "OPEN"       # failing — serve cache
    HALF_OPEN = "HALF_OPEN"  # probing recovery


class CircuitBreaker:
    """
    Per-provider simple circuit breaker.
    Opens after `failure_threshold` consecutive failures.
    Half-opens after `recovery_timeout` seconds.
    """
    def __init__(
        self,
        name: str,
        failure_threshold: int = 3,
        recovery_timeout: float = 30.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._state = BreakerState.CLOSED
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._state == BreakerState.OPEN:
            if self._opened_at and time.monotonic() - self._opened_at > self.recovery_timeout:
                self._state = BreakerState.HALF_OPEN
                log.info("[%s] circuit HALF_OPEN — probing", self.name)
                return False
            return True
        return False

    def record_success(self):
        self._failures = 0
        if self._state in (BreakerState.OPEN, BreakerState.HALF_OPEN):
            log.info("[%s] circuit CLOSED — recovered", self.name)
        self._state = BreakerState.CLOSED

    def record_failure(self):
        self._failures += 1
        if self._failures >= self.failure_threshold and self._state == BreakerState.CLOSED:
            self._state = BreakerState.OPEN
            self._opened_at = time.monotonic()
            log.warning("[%s] circuit OPEN after %d failures", self.name, self._failures)


# Global breakers — one per external provider
_breakers: dict[str, CircuitBreaker] = {
    "openai":      CircuitBreaker("openai",      failure_threshold=3, recovery_timeout=20),
    "elevenlabs":  CircuitBreaker("elevenlabs",  failure_threshold=3, recovery_timeout=20),
}


class CircuitOpenError(Exception):
    pass


async def with_resilience(
    stage: str,
    provider: str,
    fn: Callable[[], Awaitable[T]],
    fallback_fn: Callable[[], T],
    emit_fallback: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[T, bool]:
    """
    Run fn() with hard timeout and circuit breaker.
    Returns (result, is_degraded).
    On any failure, calls fallback_fn() and returns (fallback, True).
    """
    breaker = _breakers.get(provider, CircuitBreaker(provider))
    timeout = STAGE_TIMEOUTS.get(stage, 30.0)

    if breaker.is_open:
        log.warning("[%s/%s] circuit OPEN — using precomputed take", provider, stage)
        if emit_fallback:
            await emit_fallback(f"Nolan is using a prepared take for this beat ({stage}).")
        return fallback_fn(), True

    try:
        result = await asyncio.wait_for(fn(), timeout=timeout)
        breaker.record_success()
        return result, False

    except asyncio.TimeoutError:
        breaker.record_failure()
        log.warning("[%s/%s] TIMEOUT after %.0fs — fallback", provider, stage, timeout)
        if emit_fallback:
            await emit_fallback(f"Nolan timed out on {stage} — using a prepared take.")
        return fallback_fn(), True

    except Exception as exc:
        breaker.record_failure()
        log.error("[%s/%s] error: %s — fallback", provider, stage, exc)
        if emit_fallback:
            await emit_fallback(f"Nolan hit a snag on {stage} — using a prepared take.")
        return fallback_fn(), True
