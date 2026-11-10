import asyncio
import shutil
import socket
import subprocess
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
import uvicorn
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.main import create_app


@pytest.fixture
def app() -> FastAPI:
    # given
    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> Any:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _counts(queued: int = 0, running: int = 0) -> SimpleNamespace:
    return SimpleNamespace(documents_waiting=lambda: queued, documents_running=lambda: running)


async def test_occupied_by_job_past_budget_answers_503(client: AsyncClient) -> None:
    # given
    overrun = True
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=True),
        patch("src.api.readiness.is_accepting_work", return_value=not overrun),
        patch("src.api.readiness.job_runner", _counts(queued=0, running=1)),
    ):
        response = await client.get("/ready")
    # then
    assert response.status_code == 503
    assert response.json()["status"] == "not-ready"


async def test_worker_replacement_reports_not_ready_then_ready_again(client: AsyncClient) -> None:
    # given
    replacing = True
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=True),
        patch("src.api.readiness.is_accepting_work", return_value=not replacing),
        patch("src.api.readiness.job_runner", _counts()),
    ):
        refused = await client.get("/ready")
    # then
    assert refused.status_code == 503
    assert refused.json()["status"] == "not-ready"
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=True),
        patch("src.api.readiness.is_accepting_work", return_value=True),
        patch("src.api.readiness.job_runner", _counts()),
    ):
        recovered = await client.get("/ready")
    # then
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "ready"


async def test_engine_never_warmed_answers_503_with_warm_false(client: AsyncClient) -> None:
    # given
    warmed = False
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=warmed),
        patch("src.api.readiness.is_accepting_work", return_value=True),
        patch("src.api.readiness.job_runner", _counts()),
    ):
        response = await client.get("/ready")
    # then
    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not-ready"
    assert body["checks"]["engine"]["warm"] == "false"


async def test_unusable_pool_answers_503_until_rebuilt(client: AsyncClient) -> None:
    # given
    usable = False
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=True),
        patch("src.api.readiness.is_accepting_work", return_value=usable),
        patch("src.api.readiness.job_runner", _counts()),
    ):
        refused = await client.get("/ready")
    # then
    assert refused.status_code == 503
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=True),
        patch("src.api.readiness.is_accepting_work", return_value=True),
        patch("src.api.readiness.job_runner", _counts()),
    ):
        recovered = await client.get("/ready")
    # then
    assert recovered.status_code == 200
    assert recovered.json()["status"] == "ready"


async def test_rebuilds_given_up_stays_503(client: AsyncClient) -> None:
    # given
    usable = False
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=True),
        patch("src.api.readiness.is_accepting_work", return_value=usable),
        patch("src.api.readiness.job_runner", _counts()),
    ):
        first = await client.get("/ready")
        second = await client.get("/ready")
    # then
    assert first.status_code == 503
    assert second.status_code == 503
    assert second.json()["status"] == "not-ready"


async def test_shared_body_shape(client: AsyncClient) -> None:
    # given
    queued = 2
    running = 1
    # when
    with (
        patch("src.api.readiness.is_engine_warm", return_value=True),
        patch("src.api.readiness.is_accepting_work", return_value=True),
        patch("src.api.readiness.job_runner", _counts(queued=queued, running=running)),
    ):
        response = await client.get("/ready")
    # then
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["service"] == "ascend-ocr"
    assert isinstance(body["version"], str)
    assert len(body["version"]) > 0
    assert set(body["checks"]) == {"engine", "worker_pool", "jobs"}
    assert body["checks"]["engine"]["status"] == "ok"
    assert body["checks"]["worker_pool"]["status"] == "ok"
    assert body["checks"]["jobs"] == {"status": "ok", "queued": "2", "running": "1"}


async def test_curl_fss_against_not_ready_app_exits_non_zero() -> None:
    # given
    curl = shutil.which("curl.exe") or shutil.which("curl")
    assert curl is not None
    app = create_app()
    with socket.socket() as listening:
        listening.bind(("127.0.0.1", 0))
        listening.listen()
        port = listening.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, log_config=None, ws="none", lifespan="off"))
        serving = asyncio.create_task(server.serve(sockets=[listening]))
        try:
            async with AsyncClient(base_url=f"http://127.0.0.1:{port}") as probe:
                for _ in range(200):
                    try:
                        if (await probe.get("/health")).status_code == 200:
                            break
                    except Exception:
                        await asyncio.sleep(0.1)
            # when
            with (
                patch("src.api.readiness.is_engine_warm", return_value=False),
                patch("src.api.readiness.is_accepting_work", return_value=True),
            ):
                completed = await asyncio.to_thread(
                    subprocess.run,
                    [str(curl), "-fsS", f"http://127.0.0.1:{port}/ready"],
                    capture_output=True,
                )
        finally:
            server.should_exit = True
            await serving
    # then
    assert completed.returncode != 0
