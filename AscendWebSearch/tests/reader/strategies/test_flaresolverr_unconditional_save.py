"""Tests for FlareSolverrStrategy unconditional cookie persistence (task 2.2).

Previously, cookies were only saved when cf_clearance was present, which silently
discarded all LinkedIn auth cookies.  After the fix, any non-empty cookie set
is persisted regardless of which names are present.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader.strategies.flaresolverr_strategy import FlareSolverrStrategy


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
async def test_flaresolverr_saves_cookies_without_cf_clearance():
    """Auth cookies like li_at (no cf_clearance) must now be persisted."""
    session = _make_session(
        {
            "status": "ok",
            "solution": {
                "response": "<html><body>LinkedIn feed content</body></html>",
                "cookies": [
                    {"name": "li_at", "value": "AQEDABCD"},
                    {"name": "JSESSIONID", "value": "ajax:1234"},
                ],
                "userAgent": "Mozilla/5.0",
            },
        }
    )
    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.cookie_manager.save_flat_cookies",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.flaresolverr_strategy.trafilatura.extract", return_value="content"),
    ):
        await FlareSolverrStrategy().extract("https://linkedin.com/feed")

    mock_save.assert_awaited_once()
    call_args = mock_save.call_args
    cookies_arg: dict = call_args.args[1]
    assert "li_at" in cookies_arg
    assert "JSESSIONID" in cookies_arg


@pytest.mark.asyncio
async def test_flaresolverr_saves_cookies_with_cf_clearance():
    """Cloudflare cookies must still be saved (regression guard)."""
    session = _make_session(
        {
            "status": "ok",
            "solution": {
                "response": "<html><body>Cleared!</body></html>",
                "cookies": [{"name": "cf_clearance", "value": "abc"}],
                "userAgent": "UA",
            },
        }
    )
    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.cookie_manager.save_flat_cookies",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.flaresolverr_strategy.trafilatura.extract", return_value="Cleared!"),
    ):
        await FlareSolverrStrategy().extract("https://example.com")

    mock_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_flaresolverr_does_not_save_when_cookies_empty():
    """When FlareSolverr returns an empty cookie list, no save should happen."""
    session = _make_session(
        {
            "status": "ok",
            "solution": {
                "response": "<html><body>Content</body></html>",
                "cookies": [],
                "userAgent": "UA",
            },
        }
    )
    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.cookie_manager.save_flat_cookies",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.flaresolverr_strategy.trafilatura.extract", return_value="Content"),
    ):
        await FlareSolverrStrategy().extract("https://example.com")

    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_flaresolverr_injects_stored_cookies_into_payload():
    """Stored auth cookies must be injected into the FlareSolverr request payload."""
    session = _make_session(
        {
            "status": "ok",
            "solution": {
                "response": "<html><body>ok</body></html>",
                "cookies": [],
                "userAgent": "UA",
            },
        }
    )
    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={"li_at": "TOKEN"}),
        ),
        patch(
            "src.reader.strategies.flaresolverr_strategy.cookie_manager.save_flat_cookies", new=AsyncMock()
        ),
        patch("src.reader.strategies.flaresolverr_strategy.trafilatura.extract", return_value="ok"),
    ):
        await FlareSolverrStrategy().extract("https://linkedin.com")

    # Verify the payload sent to FlareSolverr contains the cookie array
    posted_payload = session.post.call_args.kwargs.get("json") or session.post.call_args.args[1]
    assert "cookies" in posted_payload
    assert any(c["name"] == "li_at" for c in posted_payload["cookies"])
