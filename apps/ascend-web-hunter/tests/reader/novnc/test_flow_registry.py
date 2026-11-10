"""Unit tests for the per-container slot registry with Redis flow records."""

import asyncio
import fnmatch
import json
import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import patch

import pytest

from src.api.exceptions import NoVNCFlowBusyException
from src.config.config import settings
from src.reader.cloudflare.cookie_manager import CookieManager, cookie_manager
from src.reader.novnc.flow_registry import (
    NoVNCFlow,
    NoVNCFlowRegistry,
    flow_key_for,
)
from src.reader.novnc.window_layout import WindowRect


class FakeRedis:
    """Minimal async Redis double with NX/PX/XX writes, expiry and compare-delete."""

    def __init__(self) -> None:
        self._data: dict[str, tuple[str, float | None]] = {}
        self.fail_on: set[str] = set()
        self.yield_on_set = False

    def _purge(self, name: str) -> None:
        entry = self._data.get(name)
        if entry is not None and entry[1] is not None and entry[1] <= time.monotonic():
            del self._data[name]

    def _alive(self, name: str) -> bool:
        self._purge(name)

        return name in self._data

    async def set(
        self,
        name: str,
        value: str,
        *,
        nx: bool = False,
        xx: bool = False,
        px: int | None = None,
    ) -> bool | None:
        if "set" in self.fail_on:
            raise RuntimeError("boom-set")
        if self.yield_on_set:
            await asyncio.sleep(0)
        if nx and self._alive(name):
            return None
        if xx and not self._alive(name):
            return None
        expire_at = time.monotonic() + px / 1000.0 if px else None
        self._data[name] = (value, expire_at)

        return True

    async def get(self, name: str) -> str | None:
        if "get" in self.fail_on:
            raise RuntimeError("boom-get")
        self._purge(name)
        entry = self._data.get(name)

        return entry[0] if entry is not None else None

    async def eval(self, script: str, numkeys: int, *keys_and_args: str) -> int:
        if "eval" in self.fail_on:
            raise RuntimeError("boom-eval")
        if len(keys_and_args) == 4:
            return await self._takeover(*keys_and_args)
        key = keys_and_args[0]
        flow_id = keys_and_args[1]
        raw = await self.get(key)
        if raw is not None and json.loads(raw)["flow_id"] == flow_id:
            del self._data[key]

            return 1

        return 0

    async def _takeover(self, key: str, expected: str, value: str, px: str | int) -> int:
        if await self.get(key) != expected:
            return 0
        self._data[key] = (value, time.monotonic() + int(px) / 1000.0)

        return 1

    async def scan_iter(self, match: str | None = None) -> AsyncIterator[str]:
        if "scan" in self.fail_on:
            raise RuntimeError("boom-scan")
        for name in list(self._data):
            if not self._alive(name):
                continue
            if match is None or fnmatch.fnmatchcase(name, match):
                yield name


def _registry(fake: FakeRedis | None = None) -> NoVNCFlowRegistry:
    return NoVNCFlowRegistry(redis_client=fake)


async def _reserve(
    registry: NoVNCFlowRegistry,
    url: str,
    profile: str = "default",
    intervention_type: str = "captcha",
    vnc_url: str = "http://vnc/vnc.html",
) -> NoVNCFlow:
    key = flow_key_for(url, profile)

    async def resolve(_flow: NoVNCFlow) -> str:
        return vnc_url

    return await registry.reserve(
        key=key, url=url, profile=profile, intervention_type=intervention_type, resolve_vnc_url=resolve
    )


async def _cancel(task: asyncio.Task[Any]) -> None:
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


# ---------------------------------------------------------------------------
# 3.1 The flow key
# ---------------------------------------------------------------------------


def test_flow_key_uses_registrable_domain_plus_profile() -> None:
    # given
    cases = {
        "https://deep.sub.example.co.uk/a": "example.co.uk",
        "example.com": "example.com",
        "http://example.com:8080/path": "example.com",
        "https://app.example.com/x": "example.com",
        "::::": "",
    }

    # when / then
    for url, domain in cases.items():
        assert CookieManager.registrable_domain(url) == domain
        assert flow_key_for(url, "default") == f"{domain}:default"
        assert flow_key_for(url, "work") == f"{CookieManager.registrable_domain(url)}:work"


# ---------------------------------------------------------------------------
# 3.2 reserve / find / release
# ---------------------------------------------------------------------------


async def test_reserve_takes_lowest_free_slot_and_writes_record_with_lease() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)

    # when
    first = await _reserve(registry, "https://site-a.com/1")
    second = await _reserve(registry, "https://site-b.com/2")

    # then
    assert first.window.slot == 0
    assert second.window.slot == 1
    assert len(first.flow_id) == 12
    assert first.request_id != ""
    raw = await fake.get("novnc_flow:site-a.com:default")
    assert raw is not None
    record = json.loads(raw)
    assert record["flow_id"] == first.flow_id
    assert record["window"]["slot"] == 0
    assert "task" not in record
    remaining = fake._data["novnc_flow:site-a.com:default"][1]
    assert remaining is not None
    expected_lease = settings.NOVNC_TIMEOUT_SECONDS + settings.NOVNC_FLOW_LEASE_GRACE_SECONDS
    assert expected_lease - 5.0 < remaining - time.monotonic() <= expected_lease

    # when
    await registry.release(first.flow_id)
    third = await _reserve(registry, "https://site-c.com/3")

    # then
    assert third.window.slot == 0


async def test_reserve_past_cap_raises_busy_with_oldest_holder() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    with patch.object(settings, "NOVNC_MAX_CONCURRENT_FLOWS", 2):
        await _reserve(registry, "https://site-a.com/1")
        await _reserve(registry, "https://site-b.com/2")

        # when / then
        with pytest.raises(NoVNCFlowBusyException) as exc:
            await _reserve(registry, "https://site-c.com/3")

    # then
    assert exc.value.holder_url == "https://site-a.com/1"
    assert exc.value.holder_profile == "default"


async def test_release_frees_slot_and_deletes_record() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")

    # when
    await registry.release(flow.flow_id)

    # then
    assert registry.local() == []
    assert await fake.get("novnc_flow:site-a.com:default") is None


async def test_release_of_unknown_identifier_is_noop() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)

    # when / then
    await registry.release("deadbeefcafe")  # must not raise


async def test_find_returns_live_flow_and_none_otherwise() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")

    # when
    found = await registry.find(flow.key)
    missing = await registry.find("other-site.com:work")

    # then
    assert found is not None
    assert found.flow_id == flow.flow_id
    assert missing is None


async def test_find_ignores_unreadable_record() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    await fake.set("novnc_flow:a.example.com:default", "{not json", px=60_000)

    # when
    found = await registry.find("a.example.com:default")

    # then
    assert found is None


async def test_find_ignores_record_missing_fields() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    await fake.set("novnc_flow:a.example.com:default", '{"flow_id": "abc"}', px=60_000)

    # when
    found = await registry.find("a.example.com:default")

    # then
    assert found is None


async def test_redis_write_error_is_one_warning_and_flow_stays_process_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    fake = FakeRedis()
    fake.fail_on.add("set")
    registry = _registry(fake)

    # when
    with caplog.at_level("WARNING", logger="src.reader.novnc.flow_registry"):
        flow = await _reserve(registry, "https://site-a.com/1")

    # then
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1
    assert [local.flow_id for local in registry.local()] == [flow.flow_id]
    found = await registry.find(flow.key)
    assert found is not None
    assert found.flow_id == flow.flow_id


async def test_redis_read_error_falls_back_to_local_flow() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")
    fake.fail_on.add("get")

    # when
    found = await registry.find(flow.key)

    # then
    assert found is not None
    assert found.flow_id == flow.flow_id


async def test_release_redis_error_frees_slot_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")
    fake.fail_on.add("eval")

    # when
    with caplog.at_level("WARNING", logger="src.reader.novnc.flow_registry"):
        await registry.release(flow.flow_id)

    # then
    assert registry.local() == []
    assert [record for record in caplog.records if record.levelname == "WARNING"] != []


async def test_process_only_registry_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    monkeypatch.setattr(cookie_manager, "redis_client", None)
    registry = _registry()
    flow = await _reserve(registry, "https://site-a.com/1")

    # when
    found = await registry.find(flow.key)
    listed = await registry.active()
    await registry.release(flow.flow_id)

    # then
    assert found is not None
    assert found.flow_id == flow.flow_id
    assert found.vnc_url == "http://vnc/vnc.html"
    assert registry.owns(found) is False
    assert [local.flow_id for local in listed] == [flow.flow_id]
    assert registry.local() == []


async def test_active_and_local_are_ordered_by_start_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    clock = {"now": 1000.0}

    def tick() -> float:
        clock["now"] += 1.0

        return clock["now"]

    monkeypatch.setattr(time, "time", tick)
    fake = FakeRedis()
    registry = _registry(fake)
    first = await _reserve(registry, "https://site-a.com/1")
    second = await _reserve(registry, "https://site-b.com/2")
    third = await _reserve(registry, "https://site-c.com/3")

    # when
    listed = await registry.active()

    # then
    assert [flow.flow_id for flow in listed] == [first.flow_id, second.flow_id, third.flow_id]
    assert [flow.flow_id for flow in registry.local()] == [first.flow_id, second.flow_id, third.flow_id]


async def test_active_is_empty_for_empty_registry() -> None:
    # given
    registry = _registry(FakeRedis())

    # when
    listed = await registry.active()

    # then
    assert listed == []


async def test_active_skips_unreadable_record(caplog: pytest.LogCaptureFixture) -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")
    await fake.set("novnc_flow:site-b.com:default", "{not json", px=60_000)

    # when
    with caplog.at_level("WARNING", logger="src.reader.novnc.flow_registry"):
        listed = await registry.active()

    # then
    assert [entry.flow_id for entry in listed] == [flow.flow_id]
    assert [record for record in caplog.records if record.levelname == "WARNING"] != []


async def test_active_redis_error_falls_back_to_local() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")
    fake.fail_on.add("scan")

    # when
    listed = await registry.active()

    # then
    assert [entry.flow_id for entry in listed] == [flow.flow_id]


async def test_reserve_retries_when_winner_record_vanished(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    other = await _reserve(_registry(fake), "https://site-a.com/1")
    calls = {"count": 0}
    original_get = fake.get

    async def flaky_get(name: str) -> str | None:
        calls["count"] += 1
        if calls["count"] == 1:
            return None

        return await original_get(name)

    monkeypatch.setattr(fake, "get", flaky_get)

    # when
    joined = await _reserve(registry, "https://site-a.com/1")

    # then
    assert joined.flow_id == other.flow_id
    assert calls["count"] == 2


async def test_reserve_read_error_after_lost_write_keeps_process_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    blocker = await _reserve(registry, "https://site-b.com/1")
    await registry.release(blocker.flow_id)
    await fake.set(
        "novnc_flow:site-b.com:default",
        json.dumps(blocker.to_record()),
        px=60_000,
    )
    fake.fail_on.add("get")

    # when
    with caplog.at_level("WARNING", logger="src.reader.novnc.flow_registry"):
        kept = await _reserve(registry, "https://site-b.com/1")

    # then
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 1
    assert [flow.flow_id for flow in registry.local()] == [kept.flow_id]


async def test_active_read_error_on_one_key_falls_back_to_local() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")
    fake.fail_on.add("get")

    # when
    listed = await registry.active()

    # then
    assert [entry.flow_id for entry in listed] == [flow.flow_id]


async def test_active_skips_key_vanished_between_scan_and_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")
    original_get = fake.get
    calls = {"count": 0}

    async def once_vanished(name: str) -> str | None:
        calls["count"] += 1
        if calls["count"] == 1:
            return None

        return await original_get(name)

    monkeypatch.setattr(fake, "get", once_vanished)

    # when
    listed = await registry.active()

    # then
    assert calls["count"] == 1
    assert [entry.flow_id for entry in listed] == []
    assert [local.flow_id for local in registry.local()] == [flow.flow_id]


# ---------------------------------------------------------------------------
# 3.3 sweep
# ---------------------------------------------------------------------------


async def test_sweep_cancels_only_expired_flow() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    old = await _reserve(registry, "https://old-site.com/1")
    young = await _reserve(registry, "https://young-site.com/2")

    async def block() -> None:
        await asyncio.sleep(3600)

    old_task = asyncio.create_task(block())
    young_task = asyncio.create_task(block())
    registry.attach_task(old.flow_id, old_task)
    registry.attach_task(young.flow_id, young_task)
    await asyncio.sleep(0.1)
    lease = settings.NOVNC_TIMEOUT_SECONDS + settings.NOVNC_FLOW_LEASE_GRACE_SECONDS
    old.lease_started -= lease + 5.0

    # when
    expired = await registry.sweep()
    await asyncio.sleep(0)

    # then
    assert [flow.flow_id for flow in expired] == [old.flow_id]
    assert old_task.cancelled()
    assert not young_task.cancelled()
    assert [flow.flow_id for flow in registry.local()] == [young.flow_id]
    assert await fake.get("novnc_flow:old-site.com:default") is None
    assert await fake.get("novnc_flow:young-site.com:default") is not None

    # cleanup
    await _cancel(old_task)
    await _cancel(young_task)


async def test_sweep_releases_expired_flows_without_tasks() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    taskless = await _reserve(registry, "https://site-a.com/1")
    lease = settings.NOVNC_TIMEOUT_SECONDS + settings.NOVNC_FLOW_LEASE_GRACE_SECONDS
    taskless.lease_started -= lease + 5.0

    async def block() -> None:
        await asyncio.sleep(3600)

    done_task = asyncio.create_task(block())
    await _cancel(done_task)
    with_task = await _reserve(registry, "https://site-b.com/2")
    with_task.lease_started -= lease + 5.0
    registry.attach_task(with_task.flow_id, done_task)

    # when
    expired = await registry.sweep()

    # then
    assert {flow.flow_id for flow in expired} == {taskless.flow_id, with_task.flow_id}
    assert registry.local() == []
    assert await fake.get("novnc_flow:site-a.com:default") is None
    assert await fake.get("novnc_flow:site-b.com:default") is None


async def test_sweep_with_no_flows_returns_empty() -> None:
    # given
    registry = _registry(FakeRedis())

    # when
    expired = await registry.sweep()

    # then
    assert expired == []


# ---------------------------------------------------------------------------
# 3.4 shutdown
# ---------------------------------------------------------------------------


async def test_shutdown_cancels_every_flow_inside_cancel_grace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    other = NoVNCFlowRegistry(redis_client=fake)
    other_flow = await _reserve(other, "https://other-site.com/9")
    first = await _reserve(registry, "https://site-a.com/1")
    second = await _reserve(registry, "https://site-b.com/2")

    async def finishing() -> None:
        await asyncio.sleep(3600)

    async def stubborn() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(3600)

    finishing_task = asyncio.create_task(finishing())
    stubborn_task = asyncio.create_task(stubborn())
    registry.attach_task(first.flow_id, finishing_task)
    registry.attach_task(second.flow_id, stubborn_task)
    await asyncio.sleep(0.1)
    monkeypatch.setattr(settings, "NOVNC_FLOW_CANCEL_GRACE_SECONDS", 0.2)

    # when
    started = time.monotonic()
    await registry.shutdown()
    elapsed = time.monotonic() - started

    # then
    assert elapsed < 5.0
    assert registry.local() == []
    assert await fake.get("novnc_flow:site-a.com:default") is None
    assert await fake.get("novnc_flow:site-b.com:default") is None
    assert await fake.get("novnc_flow:other-site.com:default") is not None
    assert [flow.flow_id for flow in other.local()] == [other_flow.flow_id]

    # cleanup
    await _cancel(finishing_task)
    await _cancel(stubborn_task)
    other_task = other_flow.task
    if other_task is not None:
        await _cancel(other_task)


async def test_shutdown_without_tasks_releases_flows() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")

    # when
    await registry.shutdown()

    # then
    assert registry.local() == []
    assert await fake.get("novnc_flow:site-a.com:default") is None
    assert flow.task is None


# ---------------------------------------------------------------------------
# 3.6 several containers on one Redis
# ---------------------------------------------------------------------------


async def test_flow_reserved_on_first_is_found_and_joined_from_second() -> None:
    # given
    fake = FakeRedis()
    first = _registry(fake)
    second = _registry(fake)
    flow = await _reserve(first, "https://site-a.com/1", vnc_url="http://edge/novnc/host-1/vnc.html")

    # when
    found = await second.find(flow.key)
    joined = await _reserve(second, "https://site-a.com/1")

    # then
    assert found is not None
    assert found.flow_id == flow.flow_id
    assert found.vnc_url == "http://edge/novnc/host-1/vnc.html"
    assert found.window == flow.window
    assert joined.flow_id == flow.flow_id
    assert second.local() == []


async def test_each_instance_fills_its_own_slots_to_the_cap() -> None:
    # given
    fake = FakeRedis()
    first = _registry(fake)
    second = _registry(fake)

    # when
    for index in range(settings.NOVNC_MAX_CONCURRENT_FLOWS):
        await _reserve(first, f"https://a-pool-{index}.com/1")
        await _reserve(second, f"https://b-pool-{index}.com/2")

    # then
    assert {flow.window.slot for flow in first.local()} == set(range(settings.NOVNC_MAX_CONCURRENT_FLOWS))
    assert {flow.window.slot for flow in second.local()} == set(range(settings.NOVNC_MAX_CONCURRENT_FLOWS))
    assert len(await first.active()) == 2 * settings.NOVNC_MAX_CONCURRENT_FLOWS
    assert len(await second.active()) == 2 * settings.NOVNC_MAX_CONCURRENT_FLOWS


async def test_expired_record_is_not_found() -> None:
    # given
    fake = FakeRedis()
    owner = _registry(fake)
    reader = _registry(fake)
    flow = await _reserve(owner, "https://site-a.com/1")
    await fake.set(
        "novnc_flow:site-a.com:default",
        json.dumps(flow.to_record()),
        px=50,
    )
    await asyncio.sleep(0.06)

    # when
    found = await reader.find(flow.key)

    # then
    assert found is None


async def test_release_of_older_flow_keeps_newer_record() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    old = await _reserve(registry, "https://site-a.com/1")
    new_record = NoVNCFlow(
        flow_id="ffffffffffff",
        key=old.key,
        url=old.url,
        profile=old.profile,
        intervention_type=old.intervention_type,
        window=old.window,
        vnc_url="http://edge/novnc/host-2/vnc.html",
        started_at=old.started_at + 1.0,
        request_id="new",
    )
    await fake.set("novnc_flow:site-a.com:default", json.dumps(new_record.to_record()), px=60_000)

    # when
    await registry.release(old.flow_id)

    # then
    raw = await fake.get("novnc_flow:site-a.com:default")
    assert raw is not None
    assert json.loads(raw)["flow_id"] == "ffffffffffff"
    assert registry.local() == []


async def test_attach_task_binds_monitor_to_local_flow() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    flow = await _reserve(registry, "https://site-a.com/1")

    async def block() -> None:
        await asyncio.sleep(3600)

    # when
    task = asyncio.create_task(block())
    registry.attach_task(flow.flow_id, task)

    # then
    assert flow.task is task

    # cleanup
    await _cancel(task)


def test_module_registry_instance_exists() -> None:
    # given / when
    from src.reader.novnc.flow_registry import novnc_flow_registry

    # then
    assert isinstance(novnc_flow_registry, NoVNCFlowRegistry)


async def test_registry_log_lines_carry_flow_id_slot_and_request_id(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)

    # when
    with caplog.at_level("INFO", logger="src.reader.novnc.flow_registry"):
        flow = await _reserve(registry, "https://log-site.com/1")
        await registry.release(flow.flow_id)

    # then
    assert caplog.records, "reserve and release must log"
    for record in caplog.records:
        line = record.getMessage()
        assert flow.flow_id in line
        assert f"slot={flow.window.slot}" in line
        assert "SECRET_COOKIE" not in line
        assert "storage_state" not in line
    reserve_lines = [record for record in caplog.records if "reserved flow_id" in record.getMessage()]
    assert reserve_lines
    assert all(flow.request_id in record.getMessage() for record in reserve_lines)


async def test_owns_distinguishes_won_and_joined_flows() -> None:
    # given
    fake = FakeRedis()
    first = _registry(fake)
    second = _registry(fake)
    flow = await _reserve(first, "https://site-a.com/1")
    joined = await _reserve(second, "https://site-a.com/1")
    joined_here = await _reserve(first, "https://site-a.com/2")

    # when / then
    assert first.owns(flow) is True
    assert second.owns(joined) is False
    assert first.owns(joined_here) is False
    assert joined_here.flow_id == flow.flow_id


def test_flow_shape_carries_decision_9_fields() -> None:
    # given
    from src.reader.novnc.flow_registry import flow_shape

    flow = NoVNCFlow(
        flow_id="9f2c41ab77de",
        key="nowsecure.nl:default",
        url="https://nowsecure.nl/page",
        profile="default",
        intervention_type="captcha",
        window=WindowRect(slot=0, x=0, y=0, width=1280, height=800),
        vnc_url="http://vnc/vnc.html",
        started_at=1000.0,
        request_id="test-request",
    )
    lease = settings.NOVNC_TIMEOUT_SECONDS + settings.NOVNC_FLOW_LEASE_GRACE_SECONDS

    # when
    shape = flow_shape(flow, now=1010.0)
    live = flow_shape(flow)

    # then
    assert shape == {
        "flow_id": "9f2c41ab77de",
        "url": "https://nowsecure.nl/page",
        "domain": "nowsecure.nl",
        "profile": "default",
        "intervention_type": "captcha",
        "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
        "age_seconds": 10.0,
        "expires_in_seconds": round(lease - 10.0, 1),
        "vnc_url": "http://vnc/vnc.html",
    }
    assert set(live) == set(shape)


async def test_busy_carries_oldest_holder_and_all_flows_in_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """At a cap of 3, the refusal names the oldest flow and lists all three
    in the flow shape with a positive remaining lease each."""
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    monkeypatch.setattr(settings, "NOVNC_MAX_CONCURRENT_FLOWS", 3)
    oldest = await _reserve(registry, "https://old-a.com/1")
    await _reserve(registry, "https://old-b.com/2")
    await _reserve(registry, "https://old-c.com/3")

    # when
    with pytest.raises(NoVNCFlowBusyException) as exc:
        await _reserve(registry, "https://new-d.com/4")

    # then
    assert exc.value.holder_url == oldest.url
    assert exc.value.holder_profile == oldest.profile
    assert exc.value.active_flows == 3
    assert exc.value.max_concurrent_flows == 3
    assert len(exc.value.flows) == 3
    assert exc.value.flows[0]["flow_id"] == oldest.flow_id
    for entry in exc.value.flows:
        assert set(entry) == {
            "flow_id",
            "url",
            "domain",
            "profile",
            "intervention_type",
            "window",
            "age_seconds",
            "expires_in_seconds",
            "vnc_url",
        }
        expires_in_seconds = entry["expires_in_seconds"]
        assert isinstance(expires_in_seconds, float)
        assert expires_in_seconds > 0


# ---------------------------------------------------------------------------
# Concurrent reservations, teardown grace, publication and stale records
# ---------------------------------------------------------------------------


def _reclaimed(reason: str) -> float:
    from prometheus_client import REGISTRY

    return REGISTRY.get_sample_value("novnc_flows_reclaimed_total", {"reason": reason}) or 0.0


async def test_concurrent_reserves_for_distinct_keys_never_share_a_slot_or_pass_the_cap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Three reads for three sites reserve at the same moment under a cap of 2:
    two flows on two different slots, and the third is refused."""
    # given
    fake = FakeRedis()
    fake.yield_on_set = True
    registry = _registry(fake)
    monkeypatch.setattr(settings, "NOVNC_MAX_CONCURRENT_FLOWS", 2)

    # when
    results = await asyncio.gather(
        _reserve(registry, "https://race-a.com/1"),
        _reserve(registry, "https://race-b.com/1"),
        _reserve(registry, "https://race-c.com/1"),
        return_exceptions=True,
    )

    # then
    flows = [result for result in results if isinstance(result, NoVNCFlow)]
    refusals = [result for result in results if isinstance(result, NoVNCFlowBusyException)]
    assert len(flows) == 2
    assert len(refusals) == 1
    assert {flow.window.slot for flow in flows} == {0, 1}
    assert len(registry.local()) == 2


async def test_cancelled_reservation_frees_its_slot() -> None:
    """A reservation cancelled while it waits on Redis holds no slot afterwards."""
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    gate = asyncio.Event()

    async def blocked_resolver(_flow: NoVNCFlow) -> str:
        await gate.wait()

        return "http://vnc/vnc.html"

    pending = asyncio.create_task(
        registry.reserve(
            key=flow_key_for("https://cancel-site.com/1", "default"),
            url="https://cancel-site.com/1",
            profile="default",
            intervention_type="captcha",
            resolve_vnc_url=blocked_resolver,
        )
    )
    await asyncio.sleep(0.01)
    assert len(registry.local()) == 1

    # when
    await _cancel(pending)

    # then
    assert registry.local() == []
    assert await fake.get("novnc_flow:cancel-site.com:default") is None


async def test_record_is_published_only_with_its_vnc_url() -> None:
    """While the owner resolves its address, no other container sees a record
    with an empty vnc_url: it sees nothing, then the complete record."""
    # given
    fake = FakeRedis()
    owner = _registry(fake)
    other = _registry(fake)
    gate = asyncio.Event()

    async def slow_resolver(_flow: NoVNCFlow) -> str:
        await gate.wait()

        return "http://edge/novnc/host-1/vnc.html"

    key = flow_key_for("https://slow-site.com/1", "default")
    reserving = asyncio.create_task(
        owner.reserve(
            key=key,
            url="https://slow-site.com/1",
            profile="default",
            intervention_type="captcha",
            resolve_vnc_url=slow_resolver,
        )
    )
    await asyncio.sleep(0.01)

    # when
    during = await other.find(key)
    gate.set()
    flow = await reserving
    after = await other.find(key)

    # then
    assert during is None
    assert after is not None
    assert after.flow_id == flow.flow_id
    assert after.vnc_url == "http://edge/novnc/host-1/vnc.html"


async def test_same_process_duplicate_waits_for_the_address_and_joins() -> None:
    """A second request for the same key in the same process, arriving while
    the owner resolves its address, takes no slot and joins with the address."""
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    gate = asyncio.Event()

    async def slow_resolver(_flow: NoVNCFlow) -> str:
        await gate.wait()

        return "http://vnc/vnc.html?autoconnect=true"

    key = flow_key_for("https://dup-site.com/1", "default")

    async def reserve_one() -> NoVNCFlow:
        return await registry.reserve(
            key=key,
            url="https://dup-site.com/1",
            profile="default",
            intervention_type="captcha",
            resolve_vnc_url=slow_resolver,
        )

    first = asyncio.create_task(reserve_one())
    await asyncio.sleep(0.01)
    second = asyncio.create_task(reserve_one())
    await asyncio.sleep(0.01)
    slots_while_pending = {flow.window.slot for flow in registry.local()}

    # when
    gate.set()
    owner, joiner = await asyncio.gather(first, second)

    # then
    assert slots_while_pending == {0}
    assert registry.owns(owner) is True
    assert registry.owns(joiner) is False
    assert joiner.flow_id == owner.flow_id
    assert joiner.vnc_url == "http://vnc/vnc.html?autoconnect=true"
    assert len(registry.local()) == 1


async def test_find_waits_for_a_local_reservation_still_resolving() -> None:
    """With Redis unreachable, find answers a local reservation only once it
    carries its address."""
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    gate = asyncio.Event()

    async def slow_resolver(_flow: NoVNCFlow) -> str:
        await gate.wait()

        return "http://vnc/vnc.html"

    key = flow_key_for("https://local-site.com/1", "default")
    reserving = asyncio.create_task(
        registry.reserve(
            key=key,
            url="https://local-site.com/1",
            profile="default",
            intervention_type="captcha",
            resolve_vnc_url=slow_resolver,
        )
    )
    await asyncio.sleep(0.01)
    finding = asyncio.create_task(registry.find(key))
    await asyncio.sleep(0.01)
    assert not finding.done()

    # when
    gate.set()
    owner = await reserving
    found = await finding

    # then
    assert found is not None
    assert found.flow_id == owner.flow_id
    assert found.vnc_url == "http://vnc/vnc.html"


async def test_waiter_on_a_failed_local_reservation_reserves_its_own() -> None:
    """When the owner's address resolution fails, a waiting duplicate does not
    join a flow that never existed: it reserves a flow of its own."""
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    gate = asyncio.Event()

    async def failing_resolver(_flow: NoVNCFlow) -> str:
        await gate.wait()

        raise RuntimeError("tunnel down")

    async def working_resolver(_flow: NoVNCFlow) -> str:
        return "http://vnc/vnc.html"

    key = flow_key_for("https://retry-site.com/1", "default")
    first = asyncio.create_task(
        registry.reserve(
            key=key,
            url="https://retry-site.com/1",
            profile="default",
            intervention_type="captcha",
            resolve_vnc_url=failing_resolver,
        )
    )
    await asyncio.sleep(0.01)
    second = asyncio.create_task(
        registry.reserve(
            key=key,
            url="https://retry-site.com/1",
            profile="default",
            intervention_type="captcha",
            resolve_vnc_url=working_resolver,
        )
    )
    await asyncio.sleep(0.01)

    # when
    gate.set()
    first_result, second_result = await asyncio.gather(first, second, return_exceptions=True)

    # then
    assert isinstance(first_result, RuntimeError)
    assert isinstance(second_result, NoVNCFlow)
    assert registry.owns(second_result) is True
    assert second_result.vnc_url == "http://vnc/vnc.html"


async def test_find_answers_none_for_a_local_reservation_that_failed() -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    gate = asyncio.Event()

    async def failing_resolver(_flow: NoVNCFlow) -> str:
        await gate.wait()

        raise RuntimeError("tunnel down")

    key = flow_key_for("https://gone-site.com/1", "default")
    reserving = asyncio.create_task(
        registry.reserve(
            key=key,
            url="https://gone-site.com/1",
            profile="default",
            intervention_type="captcha",
            resolve_vnc_url=failing_resolver,
        )
    )
    await asyncio.sleep(0.01)
    finding = asyncio.create_task(registry.find(key))
    await asyncio.sleep(0.01)

    # when
    gate.set()
    await asyncio.gather(reserving, return_exceptions=True)
    found = await finding

    # then
    assert found is None
    assert registry.local() == []


async def test_a_failed_reservation_released_meanwhile_leaves_the_registry_alone() -> None:
    """A release that lands while the address is resolved frees the slot at
    once, and the resolver failing afterwards surfaces its own error."""
    # given
    fake = FakeRedis()
    registry = _registry(fake)

    async def released_then_failing(flow: NoVNCFlow) -> str:
        await registry.release(flow.flow_id)

        raise RuntimeError("tunnel down")

    # when
    with pytest.raises(RuntimeError, match="tunnel down"):
        await registry.reserve(
            key=flow_key_for("https://released-site.com/1", "default"),
            url="https://released-site.com/1",
            profile="default",
            intervention_type="captcha",
            resolve_vnc_url=released_then_failing,
        )

    # then
    assert registry.local() == []
    assert await fake.get("novnc_flow:released-site.com:default") is None


async def test_record_lease_is_measured_from_the_flow_start() -> None:
    """The record expires one lease after the flow's own start, so it outlives
    the monitor's deadline by the grace however long the address took."""
    # given
    fake = FakeRedis()
    registry = _registry(fake)

    async def slow_resolver(_flow: NoVNCFlow) -> str:
        await asyncio.sleep(0.2)

        return "http://vnc/vnc.html"

    # when
    flow = await registry.reserve(
        key=flow_key_for("https://lease-site.com/1", "default"),
        url="https://lease-site.com/1",
        profile="default",
        intervention_type="captcha",
        resolve_vnc_url=slow_resolver,
    )

    # then
    expire_at = fake._data["novnc_flow:lease-site.com:default"][1]
    assert expire_at is not None
    lease = settings.NOVNC_TIMEOUT_SECONDS + settings.NOVNC_FLOW_LEASE_GRACE_SECONDS
    assert abs(expire_at - (flow.lease_started + lease)) < 0.1
    monitor_deadline = flow.lease_started + settings.NOVNC_TIMEOUT_SECONDS
    assert expire_at - monitor_deadline >= settings.NOVNC_FLOW_LEASE_GRACE_SECONDS - 0.1


async def test_reserve_takes_over_an_unreadable_record(caplog: pytest.LogCaptureFixture) -> None:
    """A record nobody can read is stale: the reservation replaces it and owns
    the flow instead of refusing below the cap."""
    # given
    fake = FakeRedis()
    await fake.set("novnc_flow:site-a.com:default", "{not json", px=60_000)
    registry = _registry(fake)

    # when
    with caplog.at_level("WARNING", logger="src.reader.novnc.flow_registry"):
        flow = await _reserve(registry, "https://site-a.com/1")

    # then
    assert registry.owns(flow) is True
    raw = await fake.get("novnc_flow:site-a.com:default")
    assert raw is not None
    assert json.loads(raw)["flow_id"] == flow.flow_id
    warnings = [record.getMessage() for record in caplog.records if record.levelname == "WARNING"]
    assert warnings
    for line in warnings:
        assert flow.flow_id in line
        assert f"slot={flow.window.slot}" in line


async def test_takeover_that_loses_its_compare_rereads_and_joins(monkeypatch: pytest.MonkeyPatch) -> None:
    """When the unreadable record changes before the takeover lands, the
    reservation reads again and joins the flow that replaced it."""
    # given
    fake = FakeRedis()
    await fake.set("novnc_flow:site-a.com:default", "{not json", px=60_000)
    other = _registry(fake)
    winner = NoVNCFlow(
        flow_id="0123456789ab",
        key="site-a.com:default",
        url="https://site-a.com/1",
        profile="default",
        intervention_type="captcha",
        window=WindowRect(slot=0, x=0, y=0, width=1280, height=800),
        vnc_url="http://edge/novnc/host-9/vnc.html",
        started_at=time.time(),
        request_id="winner",
    )
    original_takeover = fake._takeover

    async def overtaken(key: str, expected: str, value: str, px: str | int) -> int:
        await fake.set(key, json.dumps(winner.to_record()), px=60_000)

        return await original_takeover(key, expected, value, px)

    monkeypatch.setattr(fake, "_takeover", overtaken)

    # when
    joined = await _reserve(other, "https://site-a.com/1")

    # then
    assert joined.flow_id == "0123456789ab"
    assert other.owns(joined) is False
    assert other.local() == []


async def test_reserve_whose_winner_keeps_vanishing_keeps_the_flow_process_only(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A lost write whose winner vanishes on every read never refuses below the
    cap: the flow is kept in the process, like any other Redis trouble."""
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    await fake.set("novnc_flow:site-a.com:default", '{"flow_id": "someone"}', px=60_000)

    async def vanished(_name: str) -> str | None:
        return None

    monkeypatch.setattr(fake, "get", vanished)

    # when
    with caplog.at_level("WARNING", logger="src.reader.novnc.flow_registry"):
        flow = await _reserve(registry, "https://site-a.com/1")

    # then
    assert registry.owns(flow) is True
    warnings = [record.getMessage() for record in caplog.records if record.levelname == "WARNING"]
    assert warnings
    assert all(flow.flow_id in line and f"slot={flow.window.slot}" in line for line in warnings)


async def test_takeover_redis_error_keeps_the_flow_process_only() -> None:
    # given
    fake = FakeRedis()
    await fake.set("novnc_flow:site-a.com:default", "{not json", px=60_000)
    fake.fail_on.add("eval")
    registry = _registry(fake)

    # when
    flow = await _reserve(registry, "https://site-a.com/1")

    # then
    assert registry.owns(flow) is True


async def test_sweep_waits_for_a_cancelled_teardown_before_freeing_the_slot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep frees an expired flow's slot only once its monitor finished
    tearing down, so the window is gone before the slot is reused."""
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    monkeypatch.setattr(settings, "NOVNC_FLOW_CANCEL_GRACE_SECONDS", 2.0)
    flow = await _reserve(registry, "https://slow-close.com/1")
    torn_down = {"done": False}

    async def monitor() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(0.05)
            torn_down["done"] = True
            raise

    task = asyncio.create_task(monitor())
    registry.attach_task(flow.flow_id, task)
    await asyncio.sleep(0.01)
    flow.lease_started -= settings.NOVNC_TIMEOUT_SECONDS + settings.NOVNC_FLOW_LEASE_GRACE_SECONDS + 5.0
    before = _reclaimed("lease_expired")

    # when
    expired = await registry.sweep()

    # then
    assert torn_down["done"] is True
    assert [entry.flow_id for entry in expired] == [flow.flow_id]
    assert registry.local() == []
    assert _reclaimed("lease_expired") - before == 1.0


async def test_sweep_frees_a_stubborn_flow_after_the_grace_and_records_cancel_timeout(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    fake = FakeRedis()
    registry = _registry(fake)
    monkeypatch.setattr(settings, "NOVNC_FLOW_CANCEL_GRACE_SECONDS", 0.1)
    flow = await _reserve(registry, "https://stubborn.com/1")

    async def stubborn() -> None:
        try:
            await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await asyncio.sleep(3600)

    task = asyncio.create_task(stubborn())
    registry.attach_task(flow.flow_id, task)
    await asyncio.sleep(0.01)
    flow.lease_started -= settings.NOVNC_TIMEOUT_SECONDS + settings.NOVNC_FLOW_LEASE_GRACE_SECONDS + 5.0
    before = _reclaimed("cancel_timeout")

    # when
    started = time.monotonic()
    with caplog.at_level("WARNING", logger="src.reader.novnc.flow_registry"):
        await registry.sweep()
    elapsed = time.monotonic() - started

    # then
    assert 0.1 <= elapsed < 2.0
    assert registry.local() == []
    assert await fake.get("novnc_flow:stubborn.com:default") is None
    assert _reclaimed("cancel_timeout") - before == 1.0
    orphan_lines = [
        record.getMessage() for record in caplog.records if "did not finish" in record.getMessage()
    ]
    assert len(orphan_lines) == 1
    assert flow.flow_id in orphan_lines[0]
    assert f"slot={flow.window.slot}" in orphan_lines[0]

    # cleanup
    await _cancel(task)


async def test_busy_and_flow_shape_never_show_another_callers_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from src.reader.novnc.flow_registry import flow_shape

    registry = _registry(FakeRedis())
    monkeypatch.setattr(settings, "NOVNC_MAX_CONCURRENT_FLOWS", 1)
    holder = await _reserve(registry, "https://user:pw@holder.com/inbox?token=SECRET#frag=SECRET")

    # when
    with pytest.raises(NoVNCFlowBusyException) as exc:
        await _reserve(registry, "https://new-d.com/4")
    listed = flow_shape(holder)

    # then
    assert exc.value.holder_url == "https://holder.com/inbox"
    assert [entry["url"] for entry in exc.value.flows] == ["https://holder.com/inbox"]
    assert listed["url"] == "https://holder.com/inbox"
    assert "SECRET" not in exc.value.message
    assert "pw@" not in exc.value.message
