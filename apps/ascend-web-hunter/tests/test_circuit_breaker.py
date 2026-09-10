"""Tests for CircuitBreaker (task 7.3)."""

import time
from unittest.mock import patch

from src.circuit_breaker.breaker import BreakerState, CircuitBreaker


def _breaker(threshold: int = 2, recovery: float = 60.0) -> CircuitBreaker:
    return CircuitBreaker("test", failure_threshold=threshold, recovery_timeout=recovery)


def test_starts_closed() -> None:
    b = _breaker()
    assert b.state is BreakerState.CLOSED
    assert not b.is_open


def test_opens_after_threshold_failures() -> None:
    b = _breaker(threshold=3)
    b.record_failure()
    b.record_failure()
    assert b.state is BreakerState.CLOSED
    b.record_failure()
    assert b.state is BreakerState.OPEN
    assert b.is_open


def test_success_resets_to_closed() -> None:
    b = _breaker(threshold=2)
    b.record_failure()
    b.record_failure()
    assert b.is_open
    b.record_success()
    assert b.state is BreakerState.CLOSED
    assert not b.is_open


def test_transitions_to_half_open_after_recovery_timeout() -> None:
    b = _breaker(threshold=1, recovery=1.0)
    b.record_failure()
    assert b.state is BreakerState.OPEN

    with patch("src.circuit_breaker.breaker.time.monotonic", return_value=time.monotonic() + 2.0):
        assert b.state is BreakerState.HALF_OPEN


def test_as_status_dict_contains_state() -> None:
    b = _breaker()
    d = b.as_status_dict()
    assert "state" in d
    assert "consecutive_failures" in d
    assert d["state"] == "closed"


def test_open_state_in_status_dict() -> None:
    b = _breaker(threshold=1)
    b.record_failure()
    d = b.as_status_dict()
    assert d["state"] == "open"
    assert d["consecutive_failures"] == 1
