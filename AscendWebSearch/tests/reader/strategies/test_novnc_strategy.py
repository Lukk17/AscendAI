from unittest.mock import patch

import pytest

from src.api.exceptions import CaptchaRequiredException
from src.reader.strategies.novnc_strategy import NoVNCStrategy


@pytest.mark.asyncio
async def test_novnc_strategy_extract():
    strategy = NoVNCStrategy()
    result = await strategy.extract("http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_novnc_strategy_get_html_raises_exception():
    strategy = NoVNCStrategy()

    with patch("src.reader.strategies.novnc_strategy.settings") as mock_settings:
        mock_settings.SELENIUM_BROWSER_CDP_URL = "http://remote"
        mock_settings.SELENIUM_BROWSER_VNC_URL = "http://vnc"

        with patch("src.reader.strategies.novnc_strategy.asyncio.create_task") as mock_task:
            with pytest.raises(CaptchaRequiredException) as excinfo:
                await strategy.get_html("http://test.com")

            assert excinfo.value.vnc_url == "http://vnc"
            mock_task.assert_called_once()


@pytest.mark.asyncio
async def test_novnc_strategy_missing_config():
    strategy = NoVNCStrategy()

    with patch("src.reader.strategies.novnc_strategy.settings") as mock_settings:
        mock_settings.SELENIUM_BROWSER_CDP_URL = ""
        mock_settings.SELENIUM_BROWSER_VNC_URL = ""

        result = await strategy.get_html("http://test.com")
        assert result == ""
