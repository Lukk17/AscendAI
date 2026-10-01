"""Tests for CircuitBreaker (task 7.3)."""

import time
from unittest.mock import patch

from src.circuit_breaker.breaker import BreakerState, CircuitBreaker


def _breaker(threshold: int = 2, recovery: float = 60.0) -> CircuitBreaker:
    return CircuitBreaker("test", failure_threshold=threshold, recovery_timeout=recovery)


def test_starts_closed() -> None:
    # when
    b = _breaker()

    # then
    assert b.state is BreakerState.CLOSED
    assert not b.is_open


def test_opens_after_threshold_failures() -> None:
    # given
    b = _breaker(threshold=3)
    b.record_failure()

    # when
    b.record_failure()

    # then
    assert b.state is BreakerState.CLOSED
    b.record_failure()
    assert b.state is BreakerState.OPEN
    assert b.is_open


def test_success_resets_to_closed() -> None:
    # given
    b = _breaker(threshold=2)
    b.record_failure()

    # when
    b.record_failure()

    # then
    assert b.is_open
    b.record_success()
    assert b.state is BreakerState.CLOSED
    assert not b.is_open


def test_transitions_to_half_open_after_recovery_timeout() -> None:
    # given
    b = _breaker(threshold=1, recovery=1.0)

    # when
    b.record_failure()

    # then
    assert b.state is BreakerState.OPEN

    with patch("src.circuit_breaker.breaker.time.monotonic", return_value=time.monotonic() + 2.0):
        assert b.state is BreakerState.HALF_OPEN


def test_as_status_dict_contains_state() -> None:
    # given
    b = _breaker()

    # when
    d = b.as_status_dict()

    # then
    assert "state" in d
    assert "consecutive_failures" in d
    assert d["state"] == "closed"


def test_open_state_in_status_dict() -> None:
    # given
    b = _breaker(threshold=1)
    b.record_failure()

    # when
    d = b.as_status_dict()

    # then
    assert d["state"] == "open"
    assert d["consecutive_failures"] == 1
