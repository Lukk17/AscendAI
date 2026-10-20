from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fakeredis.aioredis import FakeRedis
from fastmcp.exceptions import ToolError
from httpx import AsyncClient

from src.api.mcp.mcp_server import (
    _mcp_tenant,
    crawl_cancel_job,
    crawl_job_status,
    crawl_list_jobs,
    crawl_submit,
)
from src.crawl import job_service as job_service_module
from src.crawl.job_service import job_service


def _ctx(tenant: str | None) -> Any:
    if tenant is None:
        return SimpleNamespace(request_context=None)
    return SimpleNamespace(
        request_context=SimpleNamespace(meta={"ascend.ai/tenant_id": tenant})
    )


def _ns(**kwargs: Any) -> Any:
    return SimpleNamespace(**kwargs)


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


def test_mcp_tenant_defaults_without_context() -> None:
    assert _mcp_tenant(None) == "default"


def test_mcp_tenant_defaults_without_request_context() -> None:
    assert _mcp_tenant(_ns(request_context=None)) == "default"


def test_mcp_tenant_defaults_without_meta() -> None:
    assert _mcp_tenant(_ns(request_context=_ns(meta=None))) == "default"


def test_mcp_tenant_defaults_without_tenant_entry() -> None:
    ctx = _ns(request_context=_ns(meta={}))
    assert _mcp_tenant(ctx) == "default"


def test_mcp_tenant_defaults_for_non_string_entry() -> None:
    ctx = _ns(request_context=_ns(meta={"ascend.ai/tenant_id": 123}))
    assert _mcp_tenant(ctx) == "default"


def test_mcp_tenant_reads_meta_entry() -> None:
    assert _mcp_tenant(_ctx("acme")) == "acme"


async def test_submit_returns_same_fields_as_rest_twin(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given a job submitted over REST
    rest_submit = (
        await client.post("/api/v1/crawl/jobs", json={"seeds": ["https://example.com/"]})
    ).json()

    # when the MCP twin submits the same request
    mcp_submit = await crawl_submit(seeds=["https://example.com/"])

    # then the field sets match
    assert set(mcp_submit) == set(rest_submit)
    assert mcp_submit["state"] == "waiting"
    assert mcp_submit["poll_after_seconds"] == rest_submit["poll_after_seconds"] == 5


async def test_status_returns_same_fields_as_rest_twin(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given a job submitted over REST
    job_id = (
        await client.post("/api/v1/crawl/jobs", json={"seeds": ["https://example.com/"]})
    ).json()["job_id"]
    rest_status = (await client.get(f"/api/v1/crawl/jobs/{job_id}")).json()

    # when the MCP twin reads it
    mcp_status = await crawl_job_status(job_id)

    # then the answers match exactly
    assert mcp_status == rest_status


async def test_list_returns_same_fields_as_rest_twin(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given a job submitted over REST
    await client.post("/api/v1/crawl/jobs", json={"seeds": ["https://example.com/"]})
    rest_list = (await client.get("/api/v1/crawl/jobs")).json()

    # when the MCP twin lists
    mcp_list = await crawl_list_jobs()

    # then the answers match exactly
    assert mcp_list == rest_list


async def test_cancel_returns_same_fields_as_rest_twin(
    client: AsyncClient, fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given a job submitted over REST
    job_id = (
        await client.post("/api/v1/crawl/jobs", json={"seeds": ["https://example.com/"]})
    ).json()["job_id"]
    rest_cancel = (await client.delete(f"/api/v1/crawl/jobs/{job_id}")).json()

    # given a second job for the MCP cancel
    second_id = (
        await client.post("/api/v1/crawl/jobs", json={"seeds": ["https://example.com/"]})
    ).json()["job_id"]

    # when the MCP twin cancels it
    mcp_cancel = await crawl_cancel_job(second_id)

    # then the field sets match and both read cancelled
    assert set(mcp_cancel) == set(rest_cancel)
    assert mcp_cancel["state"] == "cancelled"


async def test_submit_honours_depth_and_budget(
    fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # when
    submitted = await crawl_submit(
        seeds=["https://example.com/"], max_depth=3, page_budget=10
    )
    status = await crawl_job_status(submitted["job_id"])

    # then
    assert status["state"] == "waiting"


async def test_unknown_job_answers_tool_error_starting_with_code(
    fake_redis: FakeRedis,
) -> None:
    # when / then
    with pytest.raises(ToolError, match=r"^job_not_found: ") as exc_info:
        await crawl_job_status("nope")
    assert str(exc_info.value).startswith("job_not_found: ")

    with pytest.raises(ToolError, match=r"^job_not_found: "):
        await crawl_cancel_job("nope")


async def test_invalid_request_answers_validation_tool_error(
    fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # when / then
    with pytest.raises(ToolError, match=r"^validation: "):
        await crawl_submit(seeds=[])


async def test_unsafe_seed_answers_unsafe_uri_tool_error(fake_redis: FakeRedis) -> None:
    # when / then
    with pytest.raises(ToolError, match=r"^unsafe_uri: "):
        await crawl_submit(seeds=["http://127.0.0.1/"])
    assert await crawl_list_jobs() == {"jobs": []}


async def test_tools_scope_by_meta_tenant(
    fake_redis: FakeRedis, stub_guard: AsyncMock
) -> None:
    # given a job of tenant acme
    submitted = await crawl_submit(seeds=["https://example.com/"], ctx=_ctx("acme"))

    # when read as another tenant
    with pytest.raises(ToolError, match=r"^job_not_found: "):
        await crawl_job_status(submitted["job_id"], ctx=_ctx("globex"))
    with pytest.raises(ToolError, match=r"^job_not_found: "):
        await crawl_cancel_job(submitted["job_id"], ctx=_ctx("globex"))

    # then the other tenant's list hides it
    assert await crawl_list_jobs(ctx=_ctx("globex")) == {"jobs": []}
    assert (await crawl_job_status(submitted["job_id"], ctx=_ctx("acme")))["job_id"] == submitted[
        "job_id"
    ]


async def test_tools_refuse_invalid_meta_tenant(fake_redis: FakeRedis) -> None:
    # when / then
    with pytest.raises(ToolError, match=r"^invalid_tenant: "):
        await crawl_list_jobs(ctx=_ctx("../acme"))


async def test_submit_uses_meta_tenant(fake_redis: FakeRedis, stub_guard: AsyncMock) -> None:
    # when
    submitted = await crawl_submit(seeds=["https://example.com/"], ctx=_ctx("acme"))

    # then the stored job belongs to that tenant
    status = await crawl_job_status(submitted["job_id"], ctx=_ctx("acme"))
    assert status["tenant_id"] == "acme"


async def test_store_failure_answers_internal_tool_error(
    fake_redis: FakeRedis,
    stub_guard: AsyncMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given a store that fails on every operation
    async def failing(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("redis is down")

    monkeypatch.setattr(job_service, "get_job", failing)
    monkeypatch.setattr(job_service, "cancel_job", failing)

    # when / then
    with pytest.raises(ToolError, match=r"^internal: "):
        await crawl_job_status("job1")
    with pytest.raises(ToolError, match=r"^internal: "):
        await crawl_cancel_job("job1")
