from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.reader.strategies.novnc_strategy import NoVNCStrategy, _novnc_flow_lock


@pytest.fixture(autouse=True)
def _reset_novnc_flow_lock():
    """Each get_html() call in this file acquires the shared flow lock but
    (with asyncio.create_task mocked) never runs the monitor that would
    release it, so the lock must be reset around every test to keep them
    independent."""
    _novnc_flow_lock.release(_novnc_flow_lock._holder_url, _novnc_flow_lock._holder_profile)
    yield
    _novnc_flow_lock.release(_novnc_flow_lock._holder_url, _novnc_flow_lock._holder_profile)


@pytest.mark.asyncio
async def test_novnc_get_html_forwards_profile_to_monitor_task():
    """The profile passed to the constructor must reach the background monitor
    task, not be silently dropped."""
    strategy = NoVNCStrategy("work")
    assert strategy.profile == "work"
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy._monitor_for_cookies") as mock_monitor,
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task"),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await strategy.get_html("http://test.com")
    mock_monitor.assert_called_once_with("http://test.com", "captcha", "work")


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
async def test_novnc_get_html_raises_busy_when_another_flow_holds_the_lock():
    """A second flow -- whether a manual establish() or an automatic
    escalation -- must be rejected immediately rather than colliding with
    the flow already holding the shared browser/display."""
    _novnc_flow_lock.try_acquire("http://already-running.example", "default")
    strategy = NoVNCStrategy()
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task") as mock_create_task,
    ):
        with pytest.raises(NoVNCFlowBusyException) as exc:
            await strategy.get_html("http://test.com")
    assert exc.value.holder_url == "http://already-running.example"
    assert exc.value.holder_profile == "default"
    mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_novnc_get_html_releases_lock_when_vnc_url_resolution_fails():
    """If the flow never reaches task creation, the lock must not leak."""
    strategy = NoVNCStrategy()
    with (
        patch.object(
            NoVNCStrategy, "_resolve_public_vnc_url", new=AsyncMock(side_effect=RuntimeError("boom"))
        ),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task") as mock_create_task,
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await strategy.get_html("http://test.com")
    mock_create_task.assert_not_called()

    # The lock must be free again: a second flow can now acquire it.
    _novnc_flow_lock.try_acquire("http://someone-else.example", "default")


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
