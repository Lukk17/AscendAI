"""F22 regression: two concurrent flows must never share a CDP port or a session key.

F22 recorded two flows sharing one Chromium process, one display and the fixed
`--remote-debugging-port=9222`, colliding on that port while one human-captured
session was lost in silence. Under the per-flow model each flow launches its
own browser with `--remote-debugging-port=0` (the OS assigns a distinct
ephemeral port per process, so sharing the literal `0` is exactly what makes
contention impossible) and writes only its own session key.
"""

import asyncio
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException
from src.reader.novnc.flow_registry import novnc_flow_registry
from src.reader.strategies.novnc_strategy import NoVNCStrategy
from tests.reader.novnc.test_flow_registry import FakeRedis


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch: pytest.MonkeyPatch) -> Any:
    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    monkeypatch.setattr("src.reader.cloudflare.cookie_manager.cookie_manager.redis_client", None)
    novnc_flow_registry._local.clear()
    yield fake
    novnc_flow_registry._local.clear()


def _accepted_verdict() -> Any:
    from src.reader.cloudflare.challenge_signals import ChallengeVerdict

    return ChallengeVerdict(
        score=0,
        threshold=100,
        signals=(),
        vendor=None,
        wall=False,
        has_content=True,
        intervention_type="captcha",
    )


def _factory(page_url: str, cookie_name: str) -> Any:
    page = MagicMock()
    page.url = page_url
    page.goto = AsyncMock()
    page.content = AsyncMock(return_value="<html><body>ok</body></html>")
    page.evaluate = AsyncMock(return_value="UA")
    context = MagicMock()
    context.storage_state = AsyncMock(
        return_value={"cookies": [{"name": cookie_name, "value": "TOKEN"}], "origins": []}
    )
    context.new_page = AsyncMock(return_value=page)
    browser = MagicMock()
    browser.new_context = AsyncMock(return_value=context)
    browser.close = AsyncMock()
    pw = MagicMock()
    pw.chromium.launch = AsyncMock(return_value=browser)
    factory = MagicMock()
    factory.__aenter__ = AsyncMock(return_value=pw)
    factory.__aexit__ = AsyncMock(return_value=False)

    return factory


async def _drive_two_flows_to_resolution() -> tuple[Any, Any]:
    """Open two flows for two domains through the real get_html path and wait
    for both monitors to resolve. Returns the two Playwright doubles."""
    from src.reader.cloudflare.cookie_manager import cookie_manager

    factory_a = _factory("https://regression-a.com/", "cookie-a")
    factory_b = _factory("https://regression-b.com/", "cookie-b")
    cookie_manager._memory_store.clear()
    with (
        patch("src.reader.strategies.novnc_strategy.settings.PUBLIC_VNC_URL", "http://vnc"),
        patch(
            "src.reader.strategies.novnc_strategy.async_playwright",
            side_effect=[factory_a, factory_b],
        ),
        patch("src.reader.strategies.novnc_strategy.assess", return_value=_accepted_verdict()),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await NoVNCStrategy("default").get_html("https://regression-a.com/")
        with pytest.raises(HumanInterventionRequiredException):
            await NoVNCStrategy("default").get_html("https://regression-b.com/")
        tasks = [flow.task for flow in novnc_flow_registry.local()]
        assert len(tasks) == 2
        await asyncio.gather(*cast("list[asyncio.Task[None]]", tasks))

    return factory_a, factory_b


def _launch_args(factory: Any) -> list[str]:
    launch = factory.__aenter__.return_value.chromium.launch

    assert launch.await_count == 1

    return list(launch.await_args.kwargs["args"])


@pytest.mark.asyncio
async def test_two_flows_use_two_launches_with_ephemeral_ports_and_distinct_positions() -> None:
    """Two concurrent flows produce two distinct chromium.launch calls. Both
    ask the OS for an ephemeral CDP port (`0`, never `9222`), and their window
    positions differ. Reintroducing a fixed port breaks the port assertions."""
    # when
    factory_a, factory_b = await _drive_two_flows_to_resolution()

    # then
    argv_a = _launch_args(factory_a)
    argv_b = _launch_args(factory_b)
    for argv in (argv_a, argv_b):
        assert "--remote-debugging-port=0" in argv
        assert "--remote-debugging-address=127.0.0.1" in argv
        assert not any("9222" in arg for arg in argv)
    position_a = next(arg for arg in argv_a if arg.startswith("--window-position="))
    position_b = next(arg for arg in argv_b if arg.startswith("--window-position="))
    assert position_a != position_b


@pytest.mark.asyncio
async def test_both_flows_capture_under_distinct_session_keys() -> None:
    """Both flows resolve and persist two session records under two distinct
    session:{domain}:{profile} keys, each holding its own cookies. Pointing
    both monitors at one key would leave a single record and fail this."""
    # given
    from src.reader.cloudflare.cookie_manager import cookie_manager

    # when
    await _drive_two_flows_to_resolution()

    # then
    record_a = await cookie_manager.get_storage_state("https://regression-a.com/", "default")
    record_b = await cookie_manager.get_storage_state("https://regression-b.com/", "default")
    assert record_a is not None
    assert record_b is not None
    names_a = {cookie["name"] for cookie in record_a["cookies"]}
    names_b = {cookie["name"] for cookie in record_b["cookies"]}
    assert names_a == {"cookie-a"}
    assert names_b == {"cookie-b"}
    assert await cookie_manager.get_storage_state("https://regression-a.com/", "work") is None
