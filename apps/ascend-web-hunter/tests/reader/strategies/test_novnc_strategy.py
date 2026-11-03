"""Unit tests for the registry-backed NoVNC strategy: joins, reserves and URL rules."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException
from src.reader.cloudflare.challenge_signals import ChallengeVerdict
from src.reader.novnc.flow_registry import NoVNCFlowRegistry, flow_key_for, novnc_flow_registry
from src.reader.strategies.novnc_strategy import NoVNCStrategy
from tests.reader.novnc.test_flow_registry import FakeRedis


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Each test gets a fresh fake Redis behind the module registry, and no
    local flow leaks into the next test (monitor tasks are mocked, never run)."""
    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    novnc_flow_registry._local.clear()
    yield fake
    novnc_flow_registry._local.clear()


def _discard_coro(coro: Any) -> Any:
    """Stand-in for asyncio.create_task: close the never-started coroutine so
    its finalizer stays silent, and hand back a mock task for assertions."""
    coro.close()

    return MagicMock(name="monitor-task")


@pytest.mark.asyncio
async def test_novnc_get_html_forwards_profile_to_flow_record() -> None:
    """The profile passed to the constructor must reach the flow record."""
    # given
    strategy = NoVNCStrategy("work")

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await strategy.get_html("http://test.com")

    # then
    assert strategy.profile == "work"
    assert [flow.profile for flow in novnc_flow_registry.local()] == ["work"]
    assert [flow.key for flow in novnc_flow_registry.local()] == [flow_key_for("http://test.com", "work")]


@pytest.mark.asyncio
async def test_novnc_get_html_raises_login_intervention_on_login_redirect_url() -> None:
    # given
    strategy = NoVNCStrategy()

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro),
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc:
            await strategy.get_html("http://test.com?login=1")

    # then
    assert exc.value.intervention_type == "login"
    assert exc.value.vnc_url == "http://vnc/vnc.html?autoconnect=true"
    assert exc.value.joined is False
    assert exc.value.flow_id is not None
    assert exc.value.window is not None


@pytest.mark.asyncio
async def test_novnc_get_html_raises_captcha_intervention_when_no_login_url() -> None:
    # given
    strategy = NoVNCStrategy()

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro),
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc:
            await strategy.get_html("http://test.com")

    # then
    assert exc.value.intervention_type == "captcha"


@pytest.mark.asyncio
async def test_novnc_get_html_prefers_login_verdict_over_plain_url() -> None:
    # given a plain URL with no login redirect markers and a login wall verdict
    strategy = NoVNCStrategy()
    verdict = ChallengeVerdict(
        score=130,
        threshold=100,
        signals=(),
        vendor=None,
        wall=True,
        has_content=False,
        intervention_type="login",
    )

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro),
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc:
            await strategy.get_html("http://test.com", verdict)

    # then the flow and the 428 carry the verdict type, not the URL fallback
    assert exc.value.intervention_type == "login"
    assert novnc_flow_registry.local()[0].intervention_type == "login"


@pytest.mark.asyncio
async def test_novnc_extract_calls_get_html_and_returns_empty() -> None:
    # given
    strategy = NoVNCStrategy()

    # when / then
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await strategy.extract("http://test.com")


@pytest.mark.asyncio
async def test_second_call_for_same_domain_and_profile_joins_without_launch() -> None:
    """A duplicate joins the live window: no second launch, no second monitor
    task, and the same flow_id and vnc_url as the first."""
    # given
    factory = MagicMock()
    factory.chromium.launch = AsyncMock()
    first = NoVNCStrategy("default")
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro
        ) as mock_create_task,
    ):
        with pytest.raises(HumanInterventionRequiredException) as first_exc:
            await first.get_html("https://join-site.com/page-a")

        # when
        second = NoVNCStrategy("default")
        with pytest.raises(HumanInterventionRequiredException) as second_exc:
            await second.get_html("https://join-site.com/page-b")

    # then
    assert second_exc.value.joined is True
    assert second_exc.value.flow_id == first_exc.value.flow_id
    assert second_exc.value.vnc_url == first_exc.value.vnc_url
    mock_create_task.assert_called_once()
    factory.chromium.launch.assert_not_called()


@pytest.mark.asyncio
async def test_novnc_get_html_releases_slot_when_vnc_url_resolution_fails() -> None:
    """If the flow never reaches task creation, the slot must not leak and the
    Redis record must be gone before the exception propagates."""
    # given
    strategy = NoVNCStrategy()
    fake = novnc_flow_registry._redis
    assert isinstance(fake, FakeRedis)

    # when
    with (
        patch.object(
            NoVNCStrategy, "_resolve_public_vnc_url", new=AsyncMock(side_effect=RuntimeError("boom"))
        ),
        patch(
            "src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro
        ) as mock_create_task,
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await strategy.get_html("https://fail-site.com/")

    # then
    mock_create_task.assert_not_called()
    assert novnc_flow_registry.local() == []
    assert await fake.get("novnc_flow:fail-site.com:default") is None


@pytest.mark.asyncio
async def test_lost_write_joins_existing_flow_and_launches_no_browser() -> None:
    """When the SET NX write loses to another request, the caller joins the
    existing flow: no VNC resolution, no task, no launch."""
    # given
    other = NoVNCFlowRegistry(redis_client=novnc_flow_registry._redis)
    key = flow_key_for("https://race-site.com/1", "default")
    winner = await other.reserve(
        key=key, url="https://race-site.com/1", profile="default", intervention_type="captcha"
    )
    await other.set_vnc_url(winner.flow_id, "http://vnc/vnc.html?autoconnect=true")
    factory = MagicMock()
    factory.chromium.launch = AsyncMock()

    # when
    strategy = NoVNCStrategy()
    with (
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro
        ) as mock_create_task,
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc:
            await strategy.get_html("https://race-site.com/2")

    # then
    assert exc.value.joined is True
    assert exc.value.flow_id == winner.flow_id
    assert exc.value.vnc_url == "http://vnc/vnc.html?autoconnect=true"
    mock_create_task.assert_not_called()
    factory.chromium.launch.assert_not_called()


@pytest.mark.asyncio
async def test_strategy_log_lines_carry_flow_id_and_slot(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Every strategy log line names the flow and its slot, never a secret."""
    # given
    strategy = NoVNCStrategy("default")

    # when
    with (
        caplog.at_level("INFO", logger="src.reader.strategies.novnc_strategy"),
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch(
            "src.reader.strategies.novnc_strategy.asyncio.create_task",
            side_effect=_discard_coro,
        ),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await strategy.get_html("https://log-site.com/1")
        with pytest.raises(HumanInterventionRequiredException):
            await strategy.get_html("https://log-site.com/2")

    # then
    lines = [record.getMessage() for record in caplog.records]
    assert lines, "reserve and join must log"
    flow_id = novnc_flow_registry.local()[0].flow_id
    for line in lines:
        assert flow_id in line
        assert "slot=0" in line
        assert "SECRET_COOKIE" not in line
        assert "storage_state" not in line


@pytest.mark.asyncio
async def test_novnc_resolve_public_vnc_url_direct() -> None:
    # given
    strategy = NoVNCStrategy()

    # when
    with patch("src.reader.strategies.novnc_strategy.settings.NOVNC_PUBLIC_URL", None):
        result = await strategy._resolve_public_vnc_url()

    # then
    assert result.endswith("/vnc.html?autoconnect=true")


@pytest.mark.asyncio
async def test_public_url_builds_container_address_without_ngrok() -> None:
    """With NOVNC_PUBLIC_URL set, the flow record carries the edge address
    with this container's own host name, and the Ngrok API is never called."""
    # given
    strategy = NoVNCStrategy()

    # when
    with (
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_PUBLIC_URL", "https://edge.example.com"),
        patch("socket.gethostname", return_value="host-1"),
        patch("src.reader.strategies.novnc_strategy.httpx.AsyncClient") as mock_client_factory,
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro),
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc:
            await strategy.get_html("https://edge-site.com/")

    # then
    assert exc.value.vnc_url == (
        "https://edge.example.com/novnc/host-1/vnc.html?autoconnect=true&path=novnc/host-1/websockify"
    )
    assert exc.value.joined is False
    mock_client_factory.assert_not_called()


@pytest.mark.asyncio
async def test_join_on_second_container_carries_owner_hostname() -> None:
    """Two containers share one Redis and one NOVNC_PUBLIC_URL but have
    different host names: a join on the second answers the first one's address."""
    # given
    strategy = NoVNCStrategy()
    with (
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_PUBLIC_URL", "https://edge.example.com"),
        patch("socket.gethostname", return_value="host-1"),
        patch("src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro),
    ):
        with pytest.raises(HumanInterventionRequiredException) as first_exc:
            await strategy.get_html("https://shared-site.com/")

    # when
    follower = NoVNCStrategy()
    with (
        patch("src.reader.strategies.novnc_strategy.settings.NOVNC_PUBLIC_URL", "https://edge.example.com"),
        patch("socket.gethostname", return_value="host-2"),
        patch(
            "src.reader.strategies.novnc_strategy.asyncio.create_task", side_effect=_discard_coro
        ) as mock_create_task,
    ):
        with pytest.raises(HumanInterventionRequiredException) as second_exc:
            await follower.get_html("https://shared-site.com/other")

    # then
    assert first_exc.value.vnc_url == (
        "https://edge.example.com/novnc/host-1/vnc.html?autoconnect=true&path=novnc/host-1/websockify"
    )
    assert second_exc.value.joined is True
    assert second_exc.value.vnc_url == first_exc.value.vnc_url
    assert second_exc.value.flow_id == first_exc.value.flow_id
    mock_create_task.assert_not_called()


@pytest.mark.asyncio
async def test_novnc_fetch_ngrok_url_picks_first_tunnel() -> None:
    # given
    strategy = NoVNCStrategy()
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.json = MagicMock(return_value={"tunnels": [{"public_url": "https://abc.ngrok.app"}]})
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(return_value=response)

    # when
    with (
        patch(
            "src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL",
            "http://ngrok/api/tunnels",
        ),
        patch("src.reader.strategies.novnc_strategy.httpx.AsyncClient", return_value=mock_client),
    ):
        url = await strategy._resolve_public_vnc_url()

    # then
    assert url == "https://abc.ngrok.app/vnc.html?autoconnect=true"


@pytest.mark.asyncio
async def test_novnc_fetch_ngrok_url_falls_back_on_error() -> None:
    # given
    strategy = NoVNCStrategy()
    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get = AsyncMock(side_effect=RuntimeError("nope"))

    # when
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

    # then
    assert url == "http://fallback/vnc.html?autoconnect=true"


def test_novnc_extract_url_from_ngrok_empty_tunnels_uses_fallback() -> None:
    # given
    strategy = NoVNCStrategy()

    # when
    result = strategy._extract_url_from_ngrok_response({"tunnels": []}, "http://fallback")

    # then
    assert result == "http://fallback/vnc.html?autoconnect=true"


@pytest.mark.asyncio
async def test_blind_find_then_lost_write_joins_without_launch() -> None:
    """A find that misses while another request holds the key still joins:
    the reserve loses SET NX and returns the winner without launching."""
    # given
    other = NoVNCFlowRegistry(redis_client=novnc_flow_registry._redis)
    key = flow_key_for("https://blind-site.com/1", "default")
    winner = await other.reserve(
        key=key, url="https://blind-site.com/1", profile="default", intervention_type="captcha"
    )
    await other.set_vnc_url(winner.flow_id, "http://vnc/vnc.html?autoconnect=true")
    factory = MagicMock()
    factory.chromium.launch = AsyncMock()

    # when
    strategy = NoVNCStrategy()
    with (
        patch.object(NoVNCFlowRegistry, "find", new=AsyncMock(return_value=None)),
        patch("src.reader.strategies.novnc_strategy.async_playwright", return_value=factory),
        patch(
            "src.reader.strategies.novnc_strategy.asyncio.create_task",
            side_effect=_discard_coro,
        ) as mock_create_task,
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc:
            await strategy.get_html("https://blind-site.com/2")

    # then
    assert exc.value.joined is True
    assert exc.value.flow_id == winner.flow_id
    assert exc.value.vnc_url == "http://vnc/vnc.html?autoconnect=true"
    mock_create_task.assert_not_called()
    factory.chromium.launch.assert_not_called()
