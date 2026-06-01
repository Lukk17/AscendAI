from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import ChallengeDetectedException
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
async def test_flaresolverr_skipped_when_url_unset():
    strategy = FlareSolverrStrategy()
    with patch("src.reader.strategies.flaresolverr_strategy.settings.FLARESOLVERR_URL", ""):
        result = await strategy.extract("http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_flaresolverr_success_saves_cf_clearance_and_returns_html():
    session = _make_session(
        {
            "status": "ok",
            "solution": {
                "response": "<html><body>Cleared</body></html>",
                "cookies": [{"name": "cf_clearance", "value": "abc"}],
                "userAgent": "UA",
            },
        }
    )
    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.cookie_manager.save_session_data",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.reader.strategies.flaresolverr_strategy.trafilatura.extract",
            return_value="Cleared",
        ),
    ):
        result = await FlareSolverrStrategy().extract("http://test.com")
    assert result == "Cleared"
    mock_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_flaresolverr_skips_cookie_save_when_cf_clearance_missing():
    session = _make_session(
        {
            "status": "ok",
            "solution": {
                "response": "<html><body>X</body></html>",
                "cookies": [{"name": "other", "value": "x"}],
                "userAgent": "UA",
            },
        }
    )
    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.cookie_manager.save_session_data",
            new=AsyncMock(),
        ) as mock_save,
        patch("src.reader.strategies.flaresolverr_strategy.trafilatura.extract", return_value="x"),
    ):
        await FlareSolverrStrategy().extract("http://test.com")
    mock_save.assert_not_called()


@pytest.mark.asyncio
async def test_flaresolverr_login_wall_raises_challenge():
    session = _make_session(
        {
            "status": "ok",
            "solution": {
                "response": "<html><head><title>Sign In</title></head></html>",
                "cookies": [],
                "userAgent": "UA",
            },
        }
    )
    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.ChallengeDetector.is_login_required",
            return_value=True,
        ),
    ):
        with pytest.raises(ChallengeDetectedException) as exc:
            await FlareSolverrStrategy().get_html("http://test.com")
    assert exc.value.intervention_type == "login"


@pytest.mark.asyncio
async def test_flaresolverr_blocked_raises_challenge_for_consistent_escalation():
    session = _make_session(
        {
            "status": "ok",
            "solution": {
                "response": "<html><body>blocked</body></html>",
                "cookies": [],
                "userAgent": "UA",
            },
        }
    )
    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch(
            "src.reader.strategies.flaresolverr_strategy.ChallengeDetector.is_login_required",
            return_value=False,
        ),
        patch(
            "src.reader.strategies.flaresolverr_strategy.ChallengeDetector.is_blocked",
            return_value=True,
        ),
    ):
        with pytest.raises(ChallengeDetectedException) as exc:
            await FlareSolverrStrategy().get_html("http://test.com")
    assert exc.value.intervention_type == "captcha"


@pytest.mark.asyncio
async def test_flaresolverr_status_not_ok_returns_empty():
    session = _make_session({"status": "error", "message": "fail"})
    with patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session):
        result = await FlareSolverrStrategy().get_html("http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_flaresolverr_transport_error_returns_empty():
    with patch(
        "src.reader.strategies.flaresolverr_strategy.requests.AsyncSession",
        side_effect=RuntimeError("net"),
    ):
        result = await FlareSolverrStrategy().get_html("http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_flaresolverr_extract_returns_empty_when_trafilatura_none():
    session = _make_session(
        {
            "status": "ok",
            "solution": {
                "response": "<html><body>x</body></html>",
                "cookies": [],
                "userAgent": "UA",
            },
        }
    )
    with (
        patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession", return_value=session),
        patch("src.reader.strategies.flaresolverr_strategy.trafilatura.extract", return_value=None),
    ):
        result = await FlareSolverrStrategy().extract("http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_flaresolverr_extract_empty_when_html_blank():
    with patch(
        "src.reader.strategies.flaresolverr_strategy.settings.FLARESOLVERR_URL",
        "",
    ):
        result = await FlareSolverrStrategy().extract("http://test.com")
    assert result == ""
