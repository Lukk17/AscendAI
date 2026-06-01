from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException
from src.reader.strategies.novnc_strategy import NoVNCStrategy


@pytest.mark.asyncio
async def test_novnc_get_html_raises_login_intervention_on_login_redirect_url():
    strategy = NoVNCStrategy()
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task"),
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc:
            await strategy.get_html("http://test.com?login=1")
    assert exc.value.intervention_type == "login"
    assert exc.value.vnc_url == "http://vnc/vnc.html?autoconnect=true"


@pytest.mark.asyncio
async def test_novnc_get_html_raises_captcha_intervention_when_no_login_url():
    strategy = NoVNCStrategy()
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task"),
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc:
            await strategy.get_html("http://test.com")
    assert exc.value.intervention_type == "captcha"


@pytest.mark.asyncio
async def test_novnc_extract_calls_get_html_and_returns_empty():
    strategy = NoVNCStrategy()
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task"),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await strategy.extract("http://test.com")


@pytest.mark.asyncio
async def test_novnc_resolve_public_vnc_url_direct():
    strategy = NoVNCStrategy()
    result = await strategy._resolve_public_vnc_url()
    assert result.endswith("/vnc.html?autoconnect=true")


@pytest.mark.asyncio
async def test_novnc_fetch_ngrok_url_picks_first_tunnel():
    strategy = NoVNCStrategy()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"tunnels": [{"public_url": "https://abc.ngrok.app"}]})
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=response)
    with (
        patch(
            "src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL",
            "http://ngrok/api/tunnels",
        ),
        patch("src.reader.strategies.novnc_strategy.httpx.AsyncClient", return_value=mock_client),
    ):
        url = await strategy._resolve_public_vnc_url()
    assert url == "https://abc.ngrok.app/vnc.html?autoconnect=true"


@pytest.mark.asyncio
async def test_novnc_fetch_ngrok_url_falls_back_on_error():
    strategy = NoVNCStrategy()
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(side_effect=RuntimeError("nope"))
    with (
        patch(
            "src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL",
            "http://ngrok/api/tunnels",
        ),
        patch(
            "src.reader.strategies.novnc_strategy.settings.SELENIUM_BROWSER_VNC_URL",
            "http://fallback",
        ),
        patch("src.reader.strategies.novnc_strategy.httpx.AsyncClient", return_value=mock_client),
    ):
        url = await strategy._resolve_public_vnc_url()
    assert url == "http://fallback/vnc.html?autoconnect=true"


def test_novnc_extract_url_from_ngrok_empty_tunnels_uses_fallback():
    strategy = NoVNCStrategy()
    result = strategy._extract_url_from_ngrok_response({"tunnels": []}, "http://fallback")
    assert result == "http://fallback/vnc.html?autoconnect=true"
