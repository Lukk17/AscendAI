from unittest.mock import AsyncMock, patch

import pytest

from src.reader.strategies.flaresolverr_strategy import FlareSolverrStrategy


@pytest.mark.asyncio
async def test_flaresolverr_strategy_extract_skipped():
    strategy = FlareSolverrStrategy()

    with patch("src.reader.strategies.flaresolverr_strategy.settings") as mock_settings:
        mock_settings.FLARESOLVERR_URL = ""
        result = await strategy.extract("http://test.com")
        assert result == ""


@pytest.mark.asyncio
async def test_flaresolverr_strategy_success():
    strategy = FlareSolverrStrategy()
    mock_html = "<html><body>Cleared</body></html>"

    from unittest.mock import MagicMock
    mock_response = MagicMock()
    mock_response.json.return_value = {
        "status": "ok",
        "solution": {
            "response": mock_html,
            "cookies": [{"name": "cf_clearance", "value": "123"}],
            "userAgent": "TestUA"
        }
    }

    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session
    mock_session.post.return_value = mock_response

    with patch("src.reader.strategies.flaresolverr_strategy.settings") as mock_settings:
        mock_settings.FLARESOLVERR_URL = "http://flaresolverr:8191/v1"
        mock_settings.EXTRACT_TIMEOUT = 10
        with patch("src.reader.strategies.flaresolverr_strategy.requests.AsyncSession") as mock_session_cls:
            mock_session_cls.return_value = mock_session
            with patch("src.reader.strategies.flaresolverr_strategy.cookie_manager") as mock_cookie_mgr:
                mock_cookie_mgr.save_clearance_data = AsyncMock()

                # Mock trafilatura as well
                with patch("src.reader.strategies.flaresolverr_strategy.trafilatura.extract", return_value="Cleared"):
                    result = await strategy.extract("http://test.com")

                    assert result == "Cleared"
                    mock_cookie_mgr.save_clearance_data.assert_called_once()
