"""Lightweight circuit breaker for external dependencies.

Three states:
  CLOSED  — normal operation; failures are counted.
  OPEN    — dependency is considered failing; calls short-circuit immediately.
  HALF_OPEN — one probe call is allowed; success closes, failure re-opens.
"""

import logging
import time
from enum import Enum, auto

from src.config.config import settings

logger = logging.getLogger(__name__)


class BreakerState(Enum):
    CLOSED = auto()
    OPEN = auto()
    HALF_OPEN = auto()


class CircuitBreaker:
    """Per-dependency circuit breaker.

    Thread-safety note: this service runs on a single asyncio event loop;
    no locking is required.
    """

    def __init__(
        self,
        name: str,
        failure_threshold: int | None = None,
        recovery_timeout: float | None = None,
    ) -> None:
        self.name = name
        self._failure_threshold = (
            failure_threshold if failure_threshold is not None else settings.BREAKER_FAILURE_THRESHOLD
        )
        self._recovery_timeout = (
            recovery_timeout if recovery_timeout is not None else settings.BREAKER_RECOVERY_TIMEOUT_SECONDS
        )
        self._consecutive_failures = 0
        self._state = BreakerState.CLOSED
        self._opened_at: float | None = None

    @property
    def state(self) -> BreakerState:
        if (
            self._state is BreakerState.OPEN
            and self._opened_at is not None
            and time.monotonic() - self._opened_at >= self._recovery_timeout
        ):
            self._state = BreakerState.HALF_OPEN
            logger.info("[CircuitBreaker:%s] -> HALF_OPEN (probe allowed)", self.name)
        return self._state

    @property
    def is_open(self) -> bool:
        return self.state is BreakerState.OPEN

    def record_success(self) -> None:
        if self._state in (BreakerState.HALF_OPEN, BreakerState.OPEN):
            logger.info("[CircuitBreaker:%s] -> CLOSED (recovered)", self.name)
        self._consecutive_failures = 0
        self._state = BreakerState.CLOSED
        self._opened_at = None

    def record_failure(self) -> None:
        self._consecutive_failures += 1
        if self._consecutive_failures >= self._failure_threshold and self._state is not BreakerState.OPEN:
            self._state = BreakerState.OPEN
            self._opened_at = time.monotonic()
            logger.warning(
                "[CircuitBreaker:%s] -> OPEN after %d consecutive failures",
                self.name,
                self._consecutive_failures,
            )

    def as_status_dict(self) -> dict[str, object]:
        return {
            "state": self.state.name.lower(),
            "consecutive_failures": self._consecutive_failures,
        }


# Module-level singletons, one per guarded dependency.
flaresolverr_breaker = CircuitBreaker("flaresolverr")
searxng_breaker = CircuitBreaker("searxng")
