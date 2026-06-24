"""Tests for FlareSolverr circuit breaker integration (task 7.3)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.circuit_breaker.breaker import flaresolverr_breaker
from src.reader.strategies.flaresolverr_strategy import FlareSolverrStrategy


@pytest.fixture(autouse=True)
def reset_flaresolverr_breaker() -> None:
    """Reset the module-level breaker singleton before each test."""
    flaresolverr_breaker.record_success()
    yield
    flaresolverr_breaker.record_success()


def _make_session(json_payload: dict) -> MagicMock:
    response = MagicMock()
    response.json = MagicMock(return_value=json_payload)
    response.raise_for_status = MagicMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.post = AsyncMock(return_value=response)
    return session


@pytest.mark.asyncio
async def test_open_breaker_skips_flaresolverr() -> None:
    """When the FlareSolverr breaker is open, the strategy returns '' without making an HTTP call."""
    session = _make_session(
        {"status": "ok", "solution": {"response": "html", "cookies": [], "userAgent": ""}}
    )
    for _ in range(100):
        flaresolverr_breaker.record_failure()

    with patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session):
        result = await FlareSolverrStrategy().get_html("https://example.com")

    assert result == ""
    session.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_response_closes_breaker() -> None:
    """A successful FlareSolverr call must call record_success (closes the breaker)."""
    payload = {
        "status": "ok",
        "solution": {
            "response": "<html><body>content</body></html>",
            "cookies": [],
            "userAgent": "UA",
        },
    }
    session = _make_session(payload)

    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.ChallengeDetector.is_login_required",
            return_value=False,
        ),
        patch("src.reader.strategies.flaresolverr_strategy.ChallengeDetector.is_blocked", return_value=False),
    ):
        result = await FlareSolverrStrategy().get_html("https://example.com")

    assert flaresolverr_breaker.state.name == "CLOSED"
    assert result != ""


@pytest.mark.asyncio
async def test_failed_response_records_failure() -> None:
    """A non-ok FlareSolverr status must call record_failure on the breaker."""
    session = _make_session({"status": "error", "message": "timeout"})
    initial_failures = flaresolverr_breaker._consecutive_failures

    with patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session):
        await FlareSolverrStrategy().get_html("https://example.com")

    assert flaresolverr_breaker._consecutive_failures == initial_failures + 1
