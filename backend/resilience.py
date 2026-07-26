"""
Circuit breaker + hard timeout.
Key fix: OpenAI SDK auto-retries 2x internally before we even see the error.
All agents must use max_retries=0 so OUR breaker controls retry logic.
"""
from __future__ import annotations
import asyncio, time, os
from enum import Enum
from typing import Callable, Awaitable, TypeVar
import logging

log = logging.getLogger("nolan.resilience")
T = TypeVar("T")

STAGE_TIMEOUTS: dict[str, float] = {
    "transcribe":   float(os.getenv("TIMEOUT_TRANSCRIBE",   "20")),
    # The first interaction must stay demo-fast; use the input-aware fallback.
    "dna":          float(os.getenv("TIMEOUT_DNA",          "10")),
    "visions":      float(os.getenv("TIMEOUT_VISIONS",      "40")),
    "script":       float(os.getenv("TIMEOUT_SCRIPT",       "40")),
    "constitution": float(os.getenv("TIMEOUT_CONSTITUTION", "30")),
    "revision":     float(os.getenv("TIMEOUT_REVISION",     "35")),
    "audio":        float(os.getenv("TIMEOUT_AUDIO",        "180")),
}


class BreakerState(str, Enum):
    CLOSED    = "CLOSED"
    OPEN      = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5, recovery_timeout: float = 45.0):
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
        self._state = BreakerState.CLOSED

    def record_failure(self):
        self._failures += 1
        # A failed half-open probe must start a new cooldown. Otherwise the
        # breaker remains HALF_OPEN indefinitely and every request keeps
        # reaching the unhealthy provider.
        if self._failures >= self.failure_threshold and self._state in (BreakerState.CLOSED, BreakerState.HALF_OPEN):
            self._state = BreakerState.OPEN
            self._opened_at = time.monotonic()
            log.warning("[%s] circuit OPEN after %d failures", self.name, self._failures)


_breakers: dict[str, CircuitBreaker] = {
    "openai":     CircuitBreaker("openai",     failure_threshold=5, recovery_timeout=45),
    "elevenlabs": CircuitBreaker("elevenlabs", failure_threshold=5, recovery_timeout=45),
}


async def with_resilience(
    stage: str,
    provider: str,
    fn: Callable[[], Awaitable[T]],
    fallback_fn: Callable[[], T],
    emit_fallback: Callable[[str], Awaitable[None]] | None = None,
) -> tuple[T, bool]:
    breaker = _breakers.get(provider, CircuitBreaker(provider))
    timeout = STAGE_TIMEOUTS.get(stage, 35.0)

    if breaker.is_open:
        log.warning("[%s/%s] circuit OPEN — using prepared take", provider, stage)
        if emit_fallback:
            await emit_fallback("Using a prepared take for this stage.")
        return fallback_fn(), True

    try:
        result = await asyncio.wait_for(fn(), timeout=timeout)
        breaker.record_success()
        return result, False
    except asyncio.TimeoutError:
        breaker.record_failure()
        log.warning("[%s/%s] TIMEOUT after %.0fs — fallback", provider, stage, timeout)
        if emit_fallback:
            await emit_fallback(f"Stage timed out — using a prepared take.")
        return fallback_fn(), True
    except Exception as exc:
        breaker.record_failure()
        log.error("[%s/%s] error: %s — fallback", provider, stage, exc)
        if emit_fallback:
            await emit_fallback(f"API hiccup on {stage} — using a prepared take.")
        return fallback_fn(), True
