"""Every REST model that takes a profile or a session address checks it at the boundary."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

_URL = "https://example.com/"
_URL_BODY: dict[str, Any] = {"url": _URL}

_PROFILE_ENTRY_POINTS: tuple[tuple[str, dict[str, Any]], ...] = (
    ("/api/v2/web/read", _URL_BODY),
    ("/api/v2/web/session/establish", _URL_BODY),
    ("/api/v2/web/session/status", _URL_BODY),
    ("/api/v2/web/session/clear", _URL_BODY),
    ("/api/v2/web/session/import", {**_URL_BODY, "storage_state": {"cookies": [], "origins": []}}),
    ("/api/v1/crawl/jobs", {"seeds": [_URL]}),
)

_SESSION_ROUTES = (
    "/api/v2/web/session/establish",
    "/api/v2/web/session/status",
    "/api/v2/web/session/clear",
)

_PROFILE_LONGER_THAN_ALLOWED = "a" * 65


def _refused_fields(body: dict[str, Any]) -> list[str]:
    return [error["field"] for error in body["errors"]]


@pytest.mark.asyncio
@pytest.mark.parametrize(("route", "body"), _PROFILE_ENTRY_POINTS, ids=lambda value: str(value)[:40])
@pytest.mark.parametrize(
    "profile", ["a\nb", _PROFILE_LONGER_THAN_ALLOWED, "ab\n"], ids=["newline", "too-long", "trailing-newline"]
)
async def test_a_bad_profile_answers_400_invalid_profile(
    client: AsyncClient, route: str, body: dict[str, Any], profile: str
) -> None:
    # when
    with patch("src.api.rest.rest_endpoints.check_fetch_uri", new=AsyncMock()) as guard:
        resp = await client.post(route, json={**body, "profile": profile})

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    problem = resp.json()
    assert problem["code"] == "invalid_profile"
    assert {"type", "title", "status", "detail", "instance", "traceId"} <= set(problem)
    guard.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_read_with_an_empty_profile_uses_the_default_profile(client: AsyncClient) -> None:
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", new=AsyncMock()),
        patch(
            "src.api.rest.rest_endpoints.web_reader.read", new=AsyncMock(return_value={"status": "success"})
        ) as read,
    ):
        resp = await client.post("/api/v2/web/read", json={**_URL_BODY, "profile": ""})

    # then
    assert resp.status_code == 200
    assert read.await_args is not None
    assert read.await_args.kwargs["profile"] is None


@pytest.mark.asyncio
async def test_an_establish_with_an_empty_profile_uses_the_default_profile(client: AsyncClient) -> None:
    # given
    established = SimpleNamespace(
        intervention_type="login", vnc_url="https://vnc.example.com", flow_id="f", joined=False, window=None
    )

    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", new=AsyncMock()),
        patch(
            "src.api.rest.rest_endpoints.session_manager.establish", new=AsyncMock(return_value=established)
        ) as establish,
    ):
        resp = await client.post("/api/v2/web/session/establish", json={**_URL_BODY, "profile": ""})

    # then
    assert resp.status_code == 200
    establish.assert_awaited_once_with(_URL, None)


@pytest.mark.asyncio
async def test_a_status_with_an_empty_profile_uses_the_default_profile(client: AsyncClient) -> None:
    # given
    info = SimpleNamespace(to_dict=lambda: {"active": False})

    # when
    with patch(
        "src.api.rest.rest_endpoints.session_manager.status", new=AsyncMock(return_value=info)
    ) as status:
        resp = await client.post("/api/v2/web/session/status", json={**_URL_BODY, "profile": ""})

    # then
    assert resp.status_code == 200
    status.assert_awaited_once_with(_URL, None)


@pytest.mark.asyncio
async def test_a_clear_with_an_empty_profile_uses_the_default_profile(client: AsyncClient) -> None:
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", new=AsyncMock()),
        patch("src.api.rest.rest_endpoints.publish_purge", new=AsyncMock()),
        patch("src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain", return_value=0),
        patch(
            "src.api.rest.rest_endpoints.session_manager.clear", new=AsyncMock(return_value=False)
        ) as clear,
    ):
        resp = await client.post("/api/v2/web/session/clear", json={**_URL_BODY, "profile": ""})

    # then
    assert resp.status_code == 200
    clear.assert_awaited_once_with(_URL, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("route", _SESSION_ROUTES)
async def test_a_session_address_with_user_info_answers_400_validation(
    client: AsyncClient, route: str
) -> None:
    # when
    with patch("src.api.rest.rest_endpoints.check_fetch_uri", new=AsyncMock()) as guard:
        resp = await client.post(route, json={"url": "https://x.com:443@y.com/"})

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "validation"
    assert _refused_fields(resp.json()) == ["url"]
    guard.assert_not_awaited()
