import time
from unittest.mock import patch

import pytest

from src.api.exceptions import NoVNCFlowBusyException
from src.reader.strategies.novnc_strategy import _NoVNCFlowLock


def test_try_acquire_succeeds_when_lock_is_free():
    lock = _NoVNCFlowLock()

    lock.try_acquire("http://a.example", "default")  # must not raise


def test_second_try_acquire_raises_busy_with_holder_identity():
    lock = _NoVNCFlowLock()
    lock.try_acquire("http://a.example", "default")

    with pytest.raises(NoVNCFlowBusyException) as exc:
        lock.try_acquire("http://b.example", "work")

    assert exc.value.holder_url == "http://a.example"
    assert exc.value.holder_profile == "default"


def test_release_frees_the_lock_for_a_new_flow():
    lock = _NoVNCFlowLock()
    lock.try_acquire("http://a.example", "default")

    lock.release("http://a.example", "default")

    lock.try_acquire("http://b.example", "work")  # must not raise


def test_release_is_a_no_op_when_it_does_not_match_the_current_holder():
    """A stray release() call (e.g. from a test calling _monitor_for_cookies
    directly without going through get_html) must not clear someone else's
    lock."""
    lock = _NoVNCFlowLock()
    lock.try_acquire("http://a.example", "default")

    lock.release("http://different.example", "default")

    with pytest.raises(NoVNCFlowBusyException):
        lock.try_acquire("http://b.example", "work")


def test_release_when_lock_was_never_held_is_a_no_op():
    lock = _NoVNCFlowLock()

    lock.release("http://never-acquired.example", "default")  # must not raise

    lock.try_acquire("http://a.example", "default")  # still free


def test_stale_lock_past_its_lease_is_reclaimed():
    """A flow that dies without releasing (a wedged browser subprocess, a
    hang with no exception) must not wedge the endpoint forever: once the
    lease has elapsed, a new caller can acquire the lock."""
    lock = _NoVNCFlowLock()
    lock.try_acquire("http://dead-flow.example", "default")

    with (
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 0),
        patch("src.reader.strategies.novnc_strategy._NOVNC_LOCK_LEASE_GRACE_SECONDS", 0),
    ):
        lock._acquired_at = time.monotonic() - 1

        lock.try_acquire("http://new-flow.example", "default")  # must not raise

    assert lock._holder_url == "http://new-flow.example"


def test_lock_within_its_lease_is_not_reclaimed():
    lock = _NoVNCFlowLock()
    lock.try_acquire("http://in-flight.example", "default")

    with (
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_TIMEOUT_SECONDS", 600),
        patch("src.reader.strategies.novnc_strategy._NOVNC_LOCK_LEASE_GRACE_SECONDS", 30),
    ):
        with pytest.raises(NoVNCFlowBusyException):
            lock.try_acquire("http://new-flow.example", "default")
