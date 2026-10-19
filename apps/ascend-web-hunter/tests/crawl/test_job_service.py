from typing import Any
from unittest.mock import AsyncMock

import pytest
from ascend_python_common.uri_guard import UnsafeUriError

from src.config.config import settings
from src.crawl.job_service import (
    CrawlJobService,
    job_key,
    job_key_pattern,
    resolve_tenant,
)
from src.crawl.models import CrawlRequest, InvalidTenantError, JobRecord
from tests.crawl.fakes import FakeRedis


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis()


@pytest.fixture
def service(monkeypatch: pytest.MonkeyPatch, fake_redis: FakeRedis) -> CrawlJobService:
    svc = CrawlJobService()
    monkeypatch.setattr(svc, "_client", fake_redis)
    return svc


@pytest.fixture
def stub_guard(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    check = AsyncMock()
    monkeypatch.setattr("src.crawl.job_service.check_fetch_uri", check)
    return check


def _request(**kwargs: Any) -> CrawlRequest:
    fields: dict[str, Any] = {"seeds": ["https://example.com/"]}
    fields.update(kwargs)
    return CrawlRequest(**fields)


async def test_submit_stores_record_with_retention(
    service: CrawlJobService, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # when
    record = await service.submit_job("acme", _request())

    # then
    assert record.tenant_id == "acme"
    assert record.state == "waiting"
    assert len(record.job_id) == 32
    key = job_key("acme", record.job_id)
    assert fake_redis.store[key] == record.model_dump_json()
    assert fake_redis.ttls[key] == settings.CRAWL_JOB_RETENTION_SECONDS


async def test_submit_checks_every_seed(
    service: CrawlJobService, stub_guard: AsyncMock
) -> None:
    # given
    fields: dict[str, Any] = {"seeds": ["https://one.example/", "https://two.example/"]}
    request = CrawlRequest(**fields)

    # when
    await service.submit_job("acme", request)

    # then
    assert stub_guard.await_count == 2
    assert [call.args[0] for call in stub_guard.await_args_list] == [
        "https://one.example/",
        "https://two.example/",
    ]


async def test_submit_refuses_unsafe_seed_and_creates_no_job(
    service: CrawlJobService, stub_guard: AsyncMock
) -> None:
    # given
    stub_guard.side_effect = UnsafeUriError("non-public")

    # when / then
    with pytest.raises(UnsafeUriError):
        await service.submit_job("acme", _request())
    assert await service.list_jobs("acme") == []


async def test_get_missing_returns_none(service: CrawlJobService) -> None:
    # when
    record = await service.get_job("acme", "nope")

    # then
    assert record is None


async def test_get_corrupt_returns_none(
    service: CrawlJobService, fake_redis: FakeRedis
) -> None:
    # given
    await fake_redis.setex(job_key("acme", "bad"), 60, "not-json{{{")
    # when
    record = await service.get_job("acme", "bad")

    # then
    assert record is None


async def test_list_returns_only_own_tenant(
    service: CrawlJobService, stub_guard: AsyncMock
) -> None:
    # given
    first = await service.submit_job("acme", _request())
    second = await service.submit_job("acme", _request())
    other = await service.submit_job("globex", _request())

    # when
    records = await service.list_jobs("acme")

    # then
    assert {record.job_id for record in records} == {first.job_id, second.job_id}
    assert other.job_id not in {record.job_id for record in records}
    assert [record.job_id for record in await service.list_jobs("globex")] == [other.job_id]


async def test_list_skips_corrupt(
    service: CrawlJobService, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    record = await service.submit_job("acme", _request())
    await fake_redis.setex(job_key("acme", "bad"), 60, "not-json{{{")
    # when
    records = await service.list_jobs("acme")

    # then
    assert [item.job_id for item in records] == [record.job_id]


async def test_list_skips_key_vanished_between_scan_and_get(
    service: CrawlJobService,
    fake_redis: FakeRedis,
    stub_guard: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a key that disappears after the scan lists it
    await service.submit_job("acme", _request())
    monkeypatch.setattr(fake_redis, "get", AsyncMock(return_value=None))

    # when
    records = await service.list_jobs("acme")

    # then
    assert records == []


async def test_list_empty_returns_empty(service: CrawlJobService) -> None:
    # when
    records = await service.list_jobs("acme")

    # then
    assert records == []


async def test_cancel_waiting_moves_to_cancelled(
    service: CrawlJobService, stub_guard: AsyncMock
) -> None:
    # given
    submitted = await service.submit_job("acme", _request())

    # when
    record = await service.cancel_job("acme", submitted.job_id)

    # then
    assert record is not None
    assert record.state == "cancelled"
    assert record.updated_at >= record.created_at
    stored = await service.get_job("acme", submitted.job_id)
    assert stored is not None
    assert stored.state == "cancelled"


async def test_cancel_terminal_returns_unchanged(
    service: CrawlJobService, fake_redis: FakeRedis
) -> None:
    # given
    record = JobRecord(
        job_id="done1",
        tenant_id="acme",
        state="succeeded",
        request=_request(),
    )
    await fake_redis.setex(job_key("acme", "done1"), 60, record.model_dump_json())

    # when
    cancelled = await service.cancel_job("acme", "done1")

    # then
    assert cancelled is not None
    assert cancelled.state == "succeeded"


async def test_cancel_missing_returns_none(service: CrawlJobService) -> None:
    # when
    record = await service.cancel_job("acme", "nope")

    # then
    assert record is None


def test_job_key_helpers() -> None:
    # then
    assert job_key("acme", "abc") == "crawl_job:acme:abc"
    assert job_key_pattern("acme") == "crawl_job:acme:*"


def test_client_connects_lazily_to_configured_redis() -> None:
    # given a service with no injected client
    svc = CrawlJobService()

    # when
    client = svc.client

    # then a real client is built from REDIS_URL without connecting
    import redis.asyncio as async_redis

    assert isinstance(client, async_redis.Redis)
    assert svc.client is client


@pytest.mark.parametrize("header", [None, "", "default"])
def test_resolve_tenant_defaults(header: str | None) -> None:
    # when
    tenant = resolve_tenant(header)

    # then
    assert tenant == "default"


def test_resolve_tenant_keeps_named_tenant() -> None:
    # when
    tenant = resolve_tenant("acme")

    # then
    assert tenant == "acme"


@pytest.mark.parametrize("header", ["../acme", "ACME", "a" * 65, "a/b"])
def test_resolve_tenant_refuses_outside_format(header: str) -> None:
    # when / then
    with pytest.raises(InvalidTenantError):
        resolve_tenant(header)
