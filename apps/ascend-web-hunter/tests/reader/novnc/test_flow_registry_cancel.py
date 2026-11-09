"""Closing an open intervention window by flow_id, and the last window result per site and profile."""

import asyncio
import json
import time
from typing import Any
from unittest.mock import patch

import pytest

from src.api.exceptions import NoVNCFlowNotFoundError
from src.config.config import settings
from src.reader.novnc.flow_registry import (
    CANCELLED_OUTCOME,
    NoVNCFlow,
    NoVNCFlowRegistry,
    WindowResult,
    flow_key_for,
)
from tests.reader.novnc.test_flow_registry import FakeRedis

_URL = "https://site-a.com/login"
_KEY = flow_key_for(_URL, "default")


def _registry(fake: FakeRedis | None = None) -> NoVNCFlowRegistry:
    return NoVNCFlowRegistry(redis_client=fake)


async def _reserve(
    registry: NoVNCFlowRegistry, url: str = _URL, intervention_type: str = "login"
) -> NoVNCFlow:
    async def resolve(_flow: NoVNCFlow) -> str:
        return "http://vnc/vnc.html"

    return await registry.reserve(
        key=flow_key_for(url, "default"),
        url=url,
        profile="default",
        intervention_type=intervention_type,
        resolve_vnc_url=resolve,
    )


def _remote_flow(flow_id: str = "0123456789ab") -> NoVNCFlow:
    return NoVNCFlow.from_record(
        {
            "flow_id": flow_id,
            "key": _KEY,
            "url": _URL,
            "profile": "default",
            "intervention_type": "login",
            "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
            "vnc_url": "http://other-copy/vnc.html",
            "started_at": time.time(),
            "request_id": "other",
        }
    )


async def _monitor_that_records(registry: NoVNCFlowRegistry, flow: NoVNCFlow, started: asyncio.Event) -> None:
    outcome = "timeout"
    try:
        started.set()
        await asyncio.sleep(3600)
    except asyncio.CancelledError:
        outcome = CANCELLED_OUTCOME
        raise
    finally:
        await registry.finish(flow, outcome)


async def test_cancel_of_a_local_flow_stops_its_monitor_frees_the_slot_and_records_cancelled() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry)
    started = asyncio.Event()
    task = asyncio.create_task(_monitor_that_records(registry, flow, started))
    registry.attach_task(flow.flow_id, task)
    await started.wait()

    # when
    await registry.cancel(flow.flow_id)

    # then
    assert task.cancelled()
    assert registry.local() == []
    assert await fake.get(f"novnc_flow:{_KEY}") is None
    result = await registry.last_result(_KEY)
    assert result is not None
    assert (result.flow_id, result.outcome, result.intervention_type) == (flow.flow_id, "cancelled", "login")


async def test_cancel_frees_the_slot_even_when_the_monitor_outlives_the_grace() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry)
    release_gate = asyncio.Event()

    async def stubborn() -> None:
        while not release_gate.is_set():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                await release_gate.wait()

    task = asyncio.create_task(stubborn())
    registry.attach_task(flow.flow_id, task)
    await asyncio.sleep(0)

    # when
    with patch.object(settings, "NOVNC_FLOW_CANCEL_GRACE_SECONDS", 0.01):
        await registry.cancel(flow.flow_id)

    # then
    assert registry.local() == []
    result = await registry.last_result(_KEY)
    assert result is not None
    assert result.outcome == "cancelled"
    release_gate.set()
    await asyncio.gather(task, return_exceptions=True)


async def test_cancel_of_a_flow_still_publishing_waits_for_it_then_closes_it() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    resolving = asyncio.Event()
    finish_resolving = asyncio.Event()

    async def slow_resolve(_flow: NoVNCFlow) -> str:
        resolving.set()
        await finish_resolving.wait()

        return "http://vnc/vnc.html"

    reservation = asyncio.create_task(
        registry.reserve(
            key=_KEY, url=_URL, profile="default", intervention_type="login", resolve_vnc_url=slow_resolve
        )
    )
    await resolving.wait()
    pending_flow_id = registry.local()[0].flow_id

    # when
    cancelling = asyncio.create_task(registry.cancel(pending_flow_id))
    await asyncio.sleep(0)
    finish_resolving.set()
    await reservation
    await cancelling

    # then
    assert registry.local() == []
    assert await fake.get(f"novnc_flow:{_KEY}") is None


async def test_cancel_of_an_unknown_or_finished_flow_raises_not_found() -> None:
    # given
    registry = _registry(FakeRedis())
    flow = await _reserve(registry)
    await registry.release(flow.flow_id)

    # when / then
    with pytest.raises(NoVNCFlowNotFoundError, match=flow.flow_id):
        await registry.cancel(flow.flow_id)
    with pytest.raises(NoVNCFlowNotFoundError):
        await registry.cancel("not-a-flow")


async def test_cancel_without_redis_raises_not_found_for_a_flow_this_process_does_not_run() -> None:
    # given
    registry = _registry(None)

    # when / then
    with (
        patch("src.reader.novnc.flow_registry.cookie_manager.redis_client", None),
        pytest.raises(NoVNCFlowNotFoundError),
    ):
        await registry.cancel("0123456789ab")


async def test_cancel_of_another_copys_flow_drops_its_record_and_asks_the_owner_to_close() -> None:
    # given
    fake = FakeRedis()
    remote = _remote_flow()
    await fake.set(f"novnc_flow:{_KEY}", json.dumps(remote.to_record()), px=60_000)
    requester = _registry(fake)
    owner = _registry(fake)

    # when
    await requester.cancel(remote.flow_id)

    # then
    assert await fake.get(f"novnc_flow:{_KEY}") is None
    assert await owner.cancel_requested(remote.flow_id) is True
    assert await owner.cancel_requested("ffffffffffff") is False
    result = await owner.last_result(_KEY)
    assert result is not None
    assert (result.flow_id, result.outcome) == (remote.flow_id, "cancelled")


async def test_cancel_requested_is_false_without_redis_and_on_a_redis_error() -> None:
    # given
    fake = FakeRedis()
    fake.fail_on.add("get")

    # when / then
    with patch("src.reader.novnc.flow_registry.cookie_manager.redis_client", None):
        assert await _registry(None).cancel_requested("0123456789ab") is False
    assert await _registry(fake).cancel_requested("0123456789ab") is False


async def test_the_last_result_is_shared_through_redis_and_replaced_by_the_next_window() -> None:
    # given
    fake = FakeRedis()
    writer = _registry(fake)
    reader = _registry(fake)
    first = await _reserve(writer)
    await writer.finish(first, "already_authenticated")
    second = await _reserve(writer)

    # when
    await writer.finish(second, "resolved")
    result = await reader.last_result(_KEY)

    # then
    assert result is not None
    assert (result.flow_id, result.outcome) == (second.flow_id, "resolved")
    assert result.to_dict() == {
        "flow_id": second.flow_id,
        "intervention_type": "login",
        "outcome": "resolved",
        "finished_at": result.finished_at,
    }
    assert writer.local() == []


async def test_the_last_result_falls_back_to_the_process_when_redis_fails() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry)
    fake.fail_on.update({"set", "get"})

    # when
    await registry.finish(flow, "already_authenticated")
    result = await registry.last_result(_KEY)

    # then
    assert result is not None
    assert result.outcome == "already_authenticated"
    assert await registry.last_result(flow_key_for("https://never-opened.com", "default")) is None


async def test_the_last_result_uses_the_process_copy_when_only_the_redis_read_fails() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry)
    await registry.finish(flow, "resolved")
    fake.fail_on.add("get")

    # when
    result = await registry.last_result(_KEY)

    # then
    assert result is not None
    assert (result.flow_id, result.outcome) == (flow.flow_id, "resolved")


async def test_the_last_result_is_none_once_its_redis_record_is_deleted() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry)
    await registry.finish(flow, "resolved")
    del fake._data[f"novnc_window_result:{_KEY}"]

    # when
    result = await registry.last_result(_KEY)

    # then
    assert result is None


async def test_the_last_result_is_none_once_its_lifetime_passed_or_its_record_is_unreadable() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(None)
    stale = WindowResult(
        flow_id="0123456789ab",
        intervention_type="login",
        outcome="timeout",
        finished_at=time.time() - settings.SESSION_AUTH_TTL_SECONDS - 1,
    )
    registry._local_results[_KEY] = stale
    await fake.set(f"novnc_window_result:{_KEY}", "{not json")

    # when / then
    with patch("src.reader.novnc.flow_registry.cookie_manager.redis_client", None):
        assert await registry.last_result(_KEY) is None
    assert _KEY not in registry._local_results
    assert await _registry(fake).last_result(_KEY) is None


async def test_the_result_record_lives_as_long_as_a_saved_login() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry)

    # when
    await registry.finish(flow, "timeout")

    # then
    expires_at: Any = fake._data[f"novnc_window_result:{_KEY}"][1]
    lifetime = settings.SESSION_AUTH_TTL_SECONDS
    assert lifetime - 5 < expires_at - time.monotonic() <= lifetime


async def test_without_redis_the_last_result_stays_in_the_process() -> None:
    # given
    registry = _registry(None)

    # when
    with patch("src.reader.novnc.flow_registry.cookie_manager.redis_client", None):
        flow = await _reserve(registry)
        await registry.finish(flow, "browser_closed")
        result = await registry.last_result(_KEY)

    # then
    assert result is not None
    assert (result.flow_id, result.outcome) == (flow.flow_id, "browser_closed")


async def test_a_result_whose_redis_write_failed_is_served_from_the_process_once_redis_answers() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry)
    fake.fail_on.add("set")
    await registry.finish(flow, "resolved")
    fake.fail_on.clear()

    # when
    first = await registry.last_result(_KEY)
    second = await registry.last_result(_KEY)

    # then
    assert first is not None
    assert (first.flow_id, first.outcome) == (flow.flow_id, "resolved")
    assert second == first


async def test_a_successful_redis_write_makes_redis_the_record_again() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    failed = await _reserve(registry)
    fake.fail_on.add("set")
    await registry.finish(failed, "timeout")
    fake.fail_on.clear()
    written = await _reserve(registry)
    await registry.finish(written, "resolved")
    del fake._data[f"novnc_window_result:{_KEY}"]

    # when
    result = await registry.last_result(_KEY)

    # then
    assert result is None


async def test_an_unwritten_result_past_its_lifetime_reads_redis_again() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry)
    fake.fail_on.add("set")
    await registry.finish(flow, "timeout")
    fake.fail_on.clear()
    stale = registry._local_results[_KEY]
    registry._local_results[_KEY] = WindowResult(
        flow_id=stale.flow_id,
        intervention_type=stale.intervention_type,
        outcome=stale.outcome,
        finished_at=time.time() - settings.SESSION_AUTH_TTL_SECONDS - 1,
    )

    # when
    result = await registry.last_result(_KEY)

    # then
    assert result is None
    assert _KEY not in registry._results_missing_from_redis
