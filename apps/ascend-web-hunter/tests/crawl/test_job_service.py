import json
from typing import Any
from unittest.mock import AsyncMock

import pytest
from ascend_python_common.uri_guard import UnsafeUriError
from fakeredis.aioredis import FakeRedis

from src.config.config import settings
from src.crawl.job_service import (
    CrawlJobService,
    resolve_tenant,
)
from src.crawl.keys import (
    RUNNABLE_KEY,
    job_key,
    job_key_pattern,
    queue_key,
    runnable_member,
    seen_key,
)
from src.crawl.models import CrawlRequest, InvalidTenantError, JobRecord
from src.reader.schema_extraction import canonical_schema


@pytest.fixture
def fake_redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


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


@pytest.fixture
def public_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    async def allow(url: str, policy: Any) -> Any:
        from ascend_python_common.uri_guard import FetchTarget

        return FetchTarget(url=url, host=None, port=None)

    monkeypatch.setattr("src.crawl.job_service.check_fetch_uri", allow)


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
    stored = await fake_redis.get(key)
    assert stored is not None
    # The submit script round-trips the record through cjson like every
    # other script, so the stored bytes may differ while the record is equal.
    assert JobRecord.model_validate_json(stored) == record
    ttl = await fake_redis.ttl(key)
    assert settings.CRAWL_JOB_RETENTION_SECONDS - 2 <= ttl <= settings.CRAWL_JOB_RETENTION_SECONDS


async def test_submit_writes_queues_seen_and_runnable_together(
    service: CrawlJobService, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # when
    record = await service.submit_job("acme", _request())

    # then
    assert await fake_redis.lrange(queue_key("acme", record.job_id, "example.com"), 0, -1) == [
        "0\thttps://example.com/"
    ]
    assert await fake_redis.sismember(seen_key("acme", record.job_id), "https://example.com/")
    assert await fake_redis.zscore(RUNNABLE_KEY, runnable_member("acme", record.job_id)) is not None


async def test_submit_checks_every_seed(service: CrawlJobService, stub_guard: AsyncMock) -> None:
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


async def test_submit_checks_seeds_with_the_shared_fetch_policy(
    service: CrawlJobService, stub_guard: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a shared policy
    sentinel = object()
    monkeypatch.setattr("src.crawl.job_service.web_hunter_fetch_policy", lambda: sentinel)

    # when
    await service.submit_job("acme", _request())

    # then the seed guard ran with it
    assert [call.args[1] for call in stub_guard.await_args_list] == [sentinel]


async def test_submit_refuses_unsafe_seed_and_creates_no_job(
    service: CrawlJobService, stub_guard: AsyncMock
) -> None:
    # given
    stub_guard.side_effect = UnsafeUriError("non-public")

    # when / then
    with pytest.raises(UnsafeUriError):
        await service.submit_job("acme", _request())
    assert await service.list_jobs("acme") == []


async def test_submit_accepts_ignoring_robots_for_every_site(
    service: CrawlJobService, public_guard: None
) -> None:
    # when
    record = await service.submit_job("acme", _request(respect_robots=False))

    # then
    assert record.request.respect_robots is False
    assert [job.job_id for job in await service.list_jobs("acme")] == [record.job_id]


async def test_submit_refuses_oversized_extraction_schema_and_creates_no_job(
    service: CrawlJobService, stub_guard: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a schema above the read path's size cap
    monkeypatch.setattr(settings, "EXTRACTION_SCHEMA_MAX_BYTES", 10)
    request = _request(output_format="schema", extraction_schema={"type": "object", "title": "x" * 50})

    # when / then
    with pytest.raises(ValueError, match="EXTRACTION_SCHEMA_MAX_BYTES"):
        await service.submit_job("acme", request)
    assert await service.list_jobs("acme") == []
    assert stub_guard.await_count == 0


async def test_submit_accepts_extraction_schema_at_the_cap(
    service: CrawlJobService, stub_guard: AsyncMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a schema exactly at the size cap
    schema = {"type": "object"}
    monkeypatch.setattr(
        settings, "EXTRACTION_SCHEMA_MAX_BYTES", len(canonical_schema(schema).encode("utf-8"))
    )

    # when
    record = await service.submit_job("acme", _request(output_format="schema", extraction_schema=schema))

    # then
    assert record.state == "waiting"


async def test_get_missing_returns_none(service: CrawlJobService) -> None:
    # when
    record = await service.get_job("acme", "nope")

    # then
    assert record is None


async def test_get_corrupt_returns_none(service: CrawlJobService, fake_redis: FakeRedis) -> None:
    # given
    await fake_redis.set(job_key("acme", "bad"), "not-json{{{", ex=60)
    # when
    record = await service.get_job("acme", "bad")

    # then
    assert record is None


async def test_get_returns_record_after_lua_round_trip(
    service: CrawlJobService, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given a submitted job as real Redis leaves it after a script
    # round-trip: both empty pattern lists came back as empty maps
    submitted = await service.submit_job("acme", _request())
    raw = await fake_redis.get(job_key("acme", submitted.job_id))
    assert isinstance(raw, str)
    payload: dict[str, Any] = json.loads(raw)
    payload["request"]["include_patterns"] = {}
    payload["request"]["exclude_patterns"] = {}
    await fake_redis.set(job_key("acme", submitted.job_id), json.dumps(payload), ex=60)

    # when the status poll reads it back
    record = await service.get_job("acme", submitted.job_id)

    # then it returns the record instead of answering 404
    assert record is not None
    assert record.job_id == submitted.job_id
    assert record.request.include_patterns == []
    assert record.request.exclude_patterns == []


async def test_list_returns_only_own_tenant(service: CrawlJobService, stub_guard: AsyncMock) -> None:
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
    await fake_redis.set(job_key("acme", "bad"), "not-json{{{", ex=60)
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


async def test_cancel_waiting_moves_to_cancelled(service: CrawlJobService, stub_guard: AsyncMock) -> None:
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


async def test_cancel_deletes_frontier_keys(
    service: CrawlJobService, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    submitted = await service.submit_job("acme", _request())

    # when
    await service.cancel_job("acme", submitted.job_id)

    # then
    assert await fake_redis.exists(queue_key("acme", submitted.job_id, "example.com")) == 0
    assert await fake_redis.exists(seen_key("acme", submitted.job_id)) == 0
    assert await fake_redis.zscore(RUNNABLE_KEY, runnable_member("acme", submitted.job_id)) is None


async def test_cancel_terminal_returns_unchanged(service: CrawlJobService, fake_redis: FakeRedis) -> None:
    # given
    record = JobRecord(
        job_id="done1",
        tenant_id="acme",
        state="succeeded",
        request=_request(),
    )
    await fake_redis.set(job_key("acme", "done1"), record.model_dump_json(), ex=60)

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


def _record_with_old_bad_profile(fresh: JobRecord) -> str:
    stored = json.loads(fresh.model_dump_json())
    stored["request"]["profile"] = "a\nb"

    return json.dumps(stored)


async def test_a_stored_job_with_an_old_bad_profile_reads_as_not_found(
    service: CrawlJobService, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    record = await service.submit_job("acme", _request())
    await fake_redis.set(job_key("acme", record.job_id), _record_with_old_bad_profile(record))

    # when
    found = await service.get_job("acme", record.job_id)
    cancelled = await service.cancel_job("acme", record.job_id)

    # then
    assert found is None
    assert cancelled is None


async def test_the_tenant_list_skips_a_stored_job_with_an_old_bad_profile(
    service: CrawlJobService, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    bad = await service.submit_job("acme", _request())
    good = await service.submit_job("acme", _request())
    await fake_redis.set(job_key("acme", bad.job_id), _record_with_old_bad_profile(bad))

    # when
    listed = await service.list_jobs("acme")

    # then
    assert [record.job_id for record in listed] == [good.job_id]


async def test_a_seed_given_twice_is_queued_and_counted_once(
    service: CrawlJobService, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    request = _request(seeds=["https://example.com/a", "https://example.com/a", "https://example.com/b"])

    # when
    record = await service.submit_job("acme", request)

    # then
    assert record.pending == 2
    assert record.counts.queued == 2
    assert await fake_redis.lrange(queue_key("acme", record.job_id, "example.com"), 0, -1) == [
        "0\thttps://example.com/a",
        "0\thttps://example.com/b",
    ]
