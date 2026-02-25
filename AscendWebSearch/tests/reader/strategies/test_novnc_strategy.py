from unittest.mock import patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException
from src.reader.strategies.novnc_strategy import NoVNCStrategy


@pytest.mark.asyncio
async def test_novnc_strategy_extract():
    strategy = NoVNCStrategy()
    with patch("src.reader.strategies.novnc_strategy.settings") as mock_settings:
        mock_settings.SELENIUM_BROWSER_CDP_URL = ""
        mock_settings.SELENIUM_BROWSER_VNC_URL = ""
        with patch("src.reader.strategies.novnc_strategy.asyncio.create_task"):
            with pytest.raises(HumanInterventionRequiredException) as excinfo:
                await strategy.extract("http://test.com")
            assert excinfo.value.intervention_type == "captcha"


@pytest.mark.asyncio
async def test_novnc_strategy_get_html_raises_exception():
    strategy = NoVNCStrategy()

    with patch("src.reader.strategies.novnc_strategy.settings") as mock_settings:
        mock_settings.SELENIUM_BROWSER_CDP_URL = "http://remote"
        mock_settings.SELENIUM_BROWSER_VNC_URL = "http://base-vnc"
        mock_settings.PUBLIC_VNC_URL = "http://vnc"

        with patch("src.reader.strategies.novnc_strategy.asyncio.create_task") as mock_task:
            with patch("src.reader.strategies.novnc_strategy.ChallengeDetector.is_login_required",
                       return_value=True) as mock_detector:
                with pytest.raises(HumanInterventionRequiredException) as excinfo:
                    await strategy.get_html("http://test.com/login")

                assert excinfo.value.vnc_url == "http://vnc/vnc.html?autoconnect=true"
                assert excinfo.value.intervention_type == "login"
                mock_task.assert_called_once()
                mock_detector.assert_called_once_with("http://test.com/login", "")


@pytest.mark.asyncio
async def test_novnc_strategy_missing_config():
    strategy = NoVNCStrategy()

    with patch("src.reader.strategies.novnc_strategy.settings") as mock_settings:
        mock_settings.SELENIUM_BROWSER_CDP_URL = ""
        mock_settings.SELENIUM_BROWSER_VNC_URL = ""

        with patch("src.reader.strategies.novnc_strategy.asyncio.create_task"):
            with pytest.raises(HumanInterventionRequiredException) as excinfo:
                await strategy.get_html("http://test.com")
            assert excinfo.value.intervention_type == "captcha"
