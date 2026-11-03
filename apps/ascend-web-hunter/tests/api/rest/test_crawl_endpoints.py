import asyncio
import re
import socket
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis
from httpx import AsyncClient

from src.config.config import settings
from src.crawl import job_service as job_service_module
from src.crawl.job_service import job_service

_TRACE_RE = re.compile(r"[0-9a-f]{32}")

_SEED = "https://example.com/"


@pytest.fixture
def fake_redis(monkeypatch: pytest.MonkeyPatch) -> FakeRedis:
    fake = FakeRedis(decode_responses=True)
    monkeypatch.setattr(job_service, "_client", fake)
    return fake


@pytest.fixture
def stub_guard(monkeypatch: pytest.MonkeyPatch) -> AsyncMock:
    check = AsyncMock()
    monkeypatch.setattr(job_service_module, "check_fetch_uri", check)
    return check


async def _submit(
    client: AsyncClient,
    seed: str = _SEED,
    headers: dict[str, str] | None = None,
    payload: dict[str, Any] | None = None,
) -> Any:
    body: dict[str, Any] = {"seeds": [seed]}
    if payload is not None:
        body.update(payload)
    return await client.post("/api/v1/crawl/jobs", json=body, headers=headers or {})


@pytest.mark.asyncio
async def test_submit_answers_202_with_poll_hint(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # when
    resp = await _submit(client)

    # then
    assert resp.status_code == 202
    body = resp.json()
    assert set(body) == {"job_id", "state", "poll_after_seconds"}
    assert body["state"] == "waiting"
    assert body["poll_after_seconds"] == settings.CRAWL_POLL_AFTER_SECONDS == 5
    assert re.fullmatch(r"[0-9a-f]{32}", body["job_id"]) is not None
    assert stub_guard.await_count == 1


@pytest.mark.asyncio
async def test_status_returns_state_counts_and_keys(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    job_id = (await _submit(client)).json()["job_id"]

    # when
    resp = await client.get(f"/api/v1/crawl/jobs/{job_id}")

    # then
    assert resp.status_code == 200
    body = resp.json()
    assert body["job_id"] == job_id
    assert body["tenant_id"] == "default"
    assert body["state"] == "waiting"
    assert body["counts"] == {
        "queued": 1,
        "fetched": 0,
        "unchanged": 0,
        "failed": 0,
        "skipped_unsafe": 0,
    }
    assert body["pages_ndjson_key"] is None
    assert body["error"] is None


@pytest.mark.asyncio
async def test_status_unknown_answers_problem_404(client: AsyncClient, fake_redis: FakeRedis) -> None:
    # when
    resp = await client.get("/api/v1/crawl/jobs/nope")

    # then
    assert resp.status_code == 404
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    assert body["code"] == "job_not_found"
    assert body["type"] == "https://ascend.ai/errors/job-not-found"
    assert body["instance"] == "/api/v1/crawl/jobs/nope"
    assert _TRACE_RE.fullmatch(body["traceId"]) is not None


@pytest.mark.asyncio
async def test_list_returns_own_jobs(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    job_id = (await _submit(client)).json()["job_id"]

    # when
    resp = await client.get("/api/v1/crawl/jobs")

    # then
    assert resp.status_code == 200
    assert [job["job_id"] for job in resp.json()["jobs"]] == [job_id]


@pytest.mark.asyncio
async def test_cancel_moves_waiting_to_cancelled(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    job_id = (await _submit(client)).json()["job_id"]

    # when
    resp = await client.delete(f"/api/v1/crawl/jobs/{job_id}")

    # then
    assert resp.status_code == 200
    assert resp.json()["state"] == "cancelled"
    assert (await client.get(f"/api/v1/crawl/jobs/{job_id}")).json()["state"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_unknown_answers_problem_404(client: AsyncClient, fake_redis: FakeRedis) -> None:
    # when
    resp = await client.delete("/api/v1/crawl/jobs/nope")

    # then
    assert resp.status_code == 404
    assert resp.json()["code"] == "job_not_found"


@pytest.mark.asyncio
async def test_request_outside_bounds_answers_validation(client: AsyncClient, fake_redis: FakeRedis) -> None:
    # when
    resp = await client.post("/api/v1/crawl/jobs", json={"seeds": []})

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "validation"


@pytest.mark.asyncio
async def test_other_tenant_cannot_read_job(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    job_id = (await _submit(client, headers={"X-Ascend-Tenant": "acme"})).json()["job_id"]

    # when / then a call with no tenant runs as default and misses the acme job
    missing = await client.get(f"/api/v1/crawl/jobs/{job_id}")
    assert missing.status_code == 404
    assert missing.json()["code"] == "job_not_found"
    other_status = await client.get(f"/api/v1/crawl/jobs/{job_id}", headers={"X-Ascend-Tenant": "globex"})
    assert other_status.status_code == 404
    assert other_status.json()["code"] == "job_not_found"
    other_cancel = await client.delete(f"/api/v1/crawl/jobs/{job_id}", headers={"X-Ascend-Tenant": "globex"})
    assert other_cancel.status_code == 404
    assert other_cancel.json()["code"] == "job_not_found"


@pytest.mark.asyncio
async def test_list_hides_other_tenant_jobs(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    await _submit(client, headers={"X-Ascend-Tenant": "acme"})
    own = (await _submit(client, headers={"X-Ascend-Tenant": "globex"})).json()["job_id"]

    # when
    resp = await client.get("/api/v1/crawl/jobs", headers={"X-Ascend-Tenant": "globex"})

    # then
    assert [job["job_id"] for job in resp.json()["jobs"]] == [own]


@pytest.mark.asyncio
async def test_missing_and_default_tenant_both_run_as_default(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given
    first = (await _submit(client)).json()["job_id"]
    second = (await _submit(client, headers={"X-Ascend-Tenant": "default"})).json()["job_id"]

    # when
    resp = await client.get("/api/v1/crawl/jobs")

    # then
    assert {job["job_id"] for job in resp.json()["jobs"]} == {first, second}


@pytest.mark.asyncio
async def test_invalid_tenant_is_refused_and_creates_no_job(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # when
    resp = await _submit(client, headers={"X-Ascend-Tenant": "../acme"})

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_tenant"
    assert stub_guard.await_count == 0
    assert (await client.get("/api/v1/crawl/jobs")).json() == {"jobs": []}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "seed",
    [
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "file:///etc/passwd",
        "https://user:pass@example.com/",
    ],
)
async def test_unsafe_seed_is_refused_and_creates_no_job(
    client: AsyncClient, fake_redis: FakeRedis, seed: str
) -> None:
    # when
    resp = await _submit(client, seed=seed)

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "unsafe_uri"
    assert (await client.get("/api/v1/crawl/jobs")).json() == {"jobs": []}


@pytest.mark.asyncio
async def test_seed_resolving_to_private_address_is_refused(
    client: AsyncClient, fake_redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a hostname that resolves to a private address
    async def fake_getaddrinfo(host: object, port: object, **kwargs: object) -> list[Any]:
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("10.9.9.9", 0))]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "getaddrinfo", fake_getaddrinfo)

    # when
    resp = await _submit(client, seed="https://internal.example/")

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "unsafe_uri"
    assert (await client.get("/api/v1/crawl/jobs")).json() == {"jobs": []}
