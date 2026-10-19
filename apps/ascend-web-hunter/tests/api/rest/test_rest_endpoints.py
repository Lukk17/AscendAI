from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError
from httpx import AsyncClient

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.session.session_manager import SessionInfo, SessionManager


@pytest.mark.asyncio
async def test_search_get_success(client: AsyncClient) -> None:
    # given
    mock_results = [{"title": "Unit", "url": "http://unit.com", "content": "desc"}]

    # when
    with patch(
        "src.api.rest.rest_endpoints.search_client.search",
        new_callable=AsyncMock,
        return_value=mock_results,
    ):
        resp = await client.get("/api/v1/web/search", params={"query": "unit"})

    # then
    assert resp.status_code == 200
    assert resp.json()[0]["title"] == "Unit"


@pytest.mark.asyncio
async def test_search_get_empty_query_returns_400(client: AsyncClient) -> None:
    # when
    resp = await client.get("/api/v1/web/search", params={"query": ""})

    # then
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_search_get_whitespace_query_returns_400(client: AsyncClient) -> None:
    # when
    resp = await client.get("/api/v1/web/search", params={"query": "   "})

    # then
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_search_get_too_long_returns_400(client: AsyncClient) -> None:
    # when
    resp = await client.get("/api/v1/web/search", params={"query": "x" * 501})

    # then
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_read_post_success(client: AsyncClient) -> None:
    # given
    mock_content = {"content": "Extracted unit", "status": "success", "mode": "test"}

    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new_callable=AsyncMock,
            return_value=mock_content,
        ),
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": "http://unit.com/"})

    # then
    assert resp.status_code == 200
    assert resp.json()["content"] == "Extracted unit"


@pytest.mark.asyncio
async def test_read_post_unsafe_url_returns_400(client: AsyncClient) -> None:
    # when
    with patch(
        "src.api.rest.rest_endpoints.check_fetch_uri",
        side_effect=UnsafeUriError("URI resolves to a non-public address"),
    ):
        resp = await client.post("/api/v2/web/read", json={"url": "http://127.0.0.1/"})

    # then
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_read_post_missing_url_returns_400(client: AsyncClient) -> None:
    # given
    payload: dict[str, Any] = {}

    # when
    resp = await client.post("/api/v2/web/read", json=payload)

    # then
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "validation"
    assert isinstance(body["errors"], list)
    fields = [entry["field"] for entry in body["errors"]]
    assert fields == sorted(fields)
    assert all("message" in entry for entry in body["errors"])


@pytest.mark.asyncio
async def test_read_post_with_include_links(client: AsyncClient) -> None:
    # given
    mock_res = {
        "content": "X",
        "links": {1: "http://unit.com/a"},
        "status": "success",
        "mode": "test",
    }

    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.web_reader.read_with_links",
            new_callable=AsyncMock,
            return_value=mock_res,
        ) as mock_read,
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": "http://unit.com/", "include_links": True, "link_filter": "/a"},
        )

    # then
    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(
        "http://unit.com/", "/a", heavy_mode=False, profile=None, output_format="text", tier=None
    )


@pytest.mark.asyncio
async def test_read_post_heavy_mode_forwarded(client: AsyncClient) -> None:
    # given
    mock_res = {"content": "X", "status": "success", "mode": "test"}

    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new_callable=AsyncMock,
            return_value=mock_res,
        ) as mock_read,
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": "http://unit.com/", "heavy_mode": True},
        )

    # then
    assert resp.status_code == 200
    mock_read.assert_awaited_once_with(
        "http://unit.com/", heavy_mode=True, profile=None, output_format="text", tier=None
    )


# ---------------------------------------------------------------------------
# POST /api/v2/web/session/establish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_establish_session_returns_vnc_url(client: AsyncClient) -> None:
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch.object(
            SessionManager,
            "establish",
            new=AsyncMock(return_value="http://vnc:7900"),
        ),
    ):
        resp = await client.post(
            "/api/v2/web/session/establish",
            json={"url": "http://example.com/"},
        )

    # then
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "login_required"
    assert body["vnc_url"] == "http://vnc:7900"
    assert "example.com" in body["target"]


@pytest.mark.asyncio
async def test_establish_session_returns_409_when_another_flow_is_in_flight(client: AsyncClient) -> None:
    # given
    exc = NoVNCFlowBusyException("http://in-flight.example", "default")

    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "establish", new=AsyncMock(side_effect=exc)),
    ):
        resp = await client.post(
            "/api/v2/web/session/establish",
            json={"url": "http://example.com/"},
        )

    # then
    assert resp.status_code == 409
    assert "retry-after" in {key.lower() for key in resp.headers}
    body = resp.json()
    assert body["code"] == "novnc_busy"
    assert body["type"] == "https://ascend.ai/errors/novnc-busy"
    assert body["status"] == 409
    assert body["holder_url"] == "http://in-flight.example"
    assert body["holder_profile"] == "default"


@pytest.mark.asyncio
async def test_establish_session_409_carries_cap_fields(client: AsyncClient) -> None:
    # given
    flows = [
        {
            "flow_id": "9f2c41ab77de",
            "url": "https://nowsecure.nl",
            "domain": "nowsecure.nl",
            "profile": "default",
            "intervention_type": "captcha",
            "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
            "age_seconds": 207.3,
            "expires_in_seconds": 412.7,
            "vnc_url": "http://vnc/x",
        }
    ]
    exc = NoVNCFlowBusyException(
        "https://nowsecure.nl",
        "default",
        active_flows=1,
        max_concurrent_flows=4,
        flows=flows,
    )

    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "establish", new=AsyncMock(side_effect=exc)),
    ):
        resp = await client.post(
            "/api/v2/web/session/establish",
            json={"url": "http://example.com/"},
        )

    # then
    assert resp.status_code == 409
    body = resp.json()
    assert body["holder_url"] == "https://nowsecure.nl"
    assert body["active_flows"] == 1
    assert body["max_concurrent_flows"] == 4
    assert body["flows"] == flows


def _assert_example_matches_shape(example: dict[str, Any], body: dict[str, Any]) -> None:
    # The handler omits traceId when no trace is active; the documented
    # example always shows it.
    assert set(body) | {"traceId"} == set(example)
    for key in ("type", "title", "status", "code", "instance"):
        assert example[key] == body[key]
    assert example["traceId"]


@pytest.mark.asyncio
async def test_openapi_captcha_example_matches_handler_body(client: AsyncClient) -> None:
    # given
    from src.api.rest.rest_endpoints import _CAPTCHA_EXAMPLE

    window = {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800}
    exc = HumanInterventionRequiredException(
        vnc_url="https://edge.example.com/novnc/host-1/vnc.html",
        intervention_type="captcha",
        flow_id="9f2c41ab77de",
        joined=False,
        window=window,
    )

    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new=AsyncMock(side_effect=exc),
        ),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": "http://example.com/"},
        )

    # then
    assert resp.status_code == 428
    body = resp.json()
    _assert_example_matches_shape(_CAPTCHA_EXAMPLE, body)
    assert body["intervention_type"] == "captcha"
    assert body["vnc_url"] == "https://edge.example.com/novnc/host-1/vnc.html"
    assert body["flow_id"] == "9f2c41ab77de"
    assert body["joined"] is False
    assert body["window"] == window


@pytest.mark.asyncio
async def test_openapi_login_example_matches_handler_body(client: AsyncClient) -> None:
    # given
    from src.api.rest.rest_endpoints import _LOGIN_EXAMPLE

    window = {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800}
    exc = HumanInterventionRequiredException(
        vnc_url="https://edge.example.com/novnc/host-1/vnc.html",
        intervention_type="login",
        flow_id="9f2c41ab77de",
        joined=False,
        window=window,
    )

    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new=AsyncMock(side_effect=exc),
        ),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": "http://example.com/"},
        )

    # then
    assert resp.status_code == 428
    body = resp.json()
    _assert_example_matches_shape(_LOGIN_EXAMPLE, body)
    assert body["intervention_type"] == "login"


@pytest.mark.asyncio
async def test_openapi_busy_example_matches_handler_body(client: AsyncClient) -> None:
    # given
    from src.api.rest.rest_endpoints import _BUSY_EXAMPLE

    entry = {
        "flow_id": "9f2c41ab77de",
        "url": "https://nowsecure.nl",
        "domain": "nowsecure.nl",
        "profile": "default",
        "intervention_type": "captcha",
        "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
        "age_seconds": 207.3,
        "expires_in_seconds": 412.7,
        "vnc_url": "https://edge.example.com/novnc/host-1/vnc.html",
    }
    exc = NoVNCFlowBusyException(
        "https://nowsecure.nl",
        "default",
        active_flows=1,
        max_concurrent_flows=4,
        flows=[entry],
    )

    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch(
            "src.api.rest.rest_endpoints.web_reader.read",
            new=AsyncMock(side_effect=exc),
        ),
    ):
        resp = await client.post(
            "/api/v2/web/read",
            json={"url": "http://example.com/"},
        )

    # then
    assert resp.status_code == 409
    body = resp.json()
    _assert_example_matches_shape(_BUSY_EXAMPLE, body)
    assert body["holder_url"] == "https://nowsecure.nl"
    assert body["active_flows"] == 1
    example_flows = cast("list[dict[str, Any]]", _BUSY_EXAMPLE["flows"])
    assert set(body["flows"][0]) == set(example_flows[0])


# ---------------------------------------------------------------------------
# GET /api/v2/session/interventions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_interventions_empty_registry(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    from src.reader.novnc.flow_registry import novnc_flow_registry
    from tests.reader.novnc.test_flow_registry import FakeRedis

    monkeypatch.setattr(novnc_flow_registry, "_redis", FakeRedis())

    # when
    resp = await client.get("/api/v2/session/interventions")

    # then
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_flows"] == 0
    assert body["max_concurrent_flows"] == 4
    assert body["flows"] == []


@pytest.mark.asyncio
async def test_list_interventions_reports_each_flow_once(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    from src.reader.novnc.flow_registry import (
        NoVNCFlowRegistry,
        flow_key_for,
        novnc_flow_registry,
    )
    from tests.reader.novnc.test_flow_registry import FakeRedis

    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    first = await novnc_flow_registry.reserve(
        key=flow_key_for("https://listed-a.com/1", "default"),
        url="https://listed-a.com/1",
        profile="default",
        intervention_type="captcha",
    )
    second = await novnc_flow_registry.reserve(
        key=flow_key_for("https://listed-b.com/1", "work"),
        url="https://listed-b.com/1",
        profile="work",
        intervention_type="login",
    )
    other_registry = NoVNCFlowRegistry(redis_client=fake)
    await other_registry.reserve(
        key=flow_key_for("https://listed-c.com/1", "default"),
        url="https://listed-c.com/1",
        profile="default",
        intervention_type="captcha",
    )

    # when
    resp = await client.get("/api/v2/session/interventions")

    # then
    assert resp.status_code == 200
    body = resp.json()
    assert body["active_flows"] == 3
    assert body["max_concurrent_flows"] == 4
    assert {entry["flow_id"] for entry in body["flows"]} == {
        first.flow_id,
        second.flow_id,
        next(entry for entry in body["flows"] if entry["url"] == "https://listed-c.com/1")["flow_id"],
    }
    for entry in body["flows"]:
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
        assert set(entry["window"]) == {"slot", "x", "y", "width", "height"}
        assert entry["expires_in_seconds"] > 0
        assert "cookie" not in str(body).lower()
        assert "storage" not in str(body).lower()
        assert entry["window"]["slot"] in (0, 1)

    # cleanup
    await novnc_flow_registry.release(first.flow_id)
    await novnc_flow_registry.release(second.flow_id)


@pytest.mark.asyncio
async def test_interventions_rest_and_mcp_return_same_payload(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    from src.api.mcp.mcp_server import session_interventions
    from src.reader.novnc.flow_registry import flow_key_for, novnc_flow_registry
    from tests.reader.novnc.test_flow_registry import FakeRedis

    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for("https://parity-site.com/1", "default"),
        url="https://parity-site.com/1",
        profile="default",
        intervention_type="captcha",
    )
    await novnc_flow_registry.set_vnc_url(flow.flow_id, "http://vnc/vnc.html")

    # when
    resp = await client.get("/api/v2/session/interventions")
    mcp_result = await session_interventions()

    # then
    assert resp.status_code == 200
    assert resp.json() == mcp_result

    # cleanup
    await novnc_flow_registry.release(flow.flow_id)


@pytest.mark.asyncio
async def test_busy_flows_and_listing_name_owner_hostname(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """One shared NOVNC_PUBLIC_URL, flows owned by host-1: the 409 flows and
    the listing read anywhere name the owning container's address."""
    # given
    from src.api.mcp.mcp_server import session_interventions
    from src.reader.novnc.flow_registry import flow_key_for, novnc_flow_registry
    from tests.reader.novnc.test_flow_registry import FakeRedis

    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    owned: list[str] = []
    for domain in ["h1-a.com", "h1-b.com", "h1-c.com", "h1-d.com"]:
        key = flow_key_for(f"https://{domain}/1", "default")
        flow = await novnc_flow_registry.reserve(
            key=key,
            url=f"https://{domain}/1",
            profile="default",
            intervention_type="captcha",
        )
        await novnc_flow_registry.set_vnc_url(
            flow.flow_id,
            "https://edge.example.com/novnc/host-1/vnc.html?autoconnect=true&path=novnc/host-1/websockify",
        )
        owned.append(flow.flow_id)

    # when
    busy: NoVNCFlowBusyException | None = None
    try:
        await novnc_flow_registry.reserve(
            key=flow_key_for("https://h2-e.com/1", "default"),
            url="https://h2-e.com/1",
            profile="default",
            intervention_type="captcha",
        )
    except NoVNCFlowBusyException as exc:
        busy = exc
    assert busy is not None
    resp = await client.get("/api/v2/session/interventions")
    mcp_result = await session_interventions()

    # then
    assert {entry["flow_id"] for entry in busy.flows} == set(owned)
    assert all("host-1" in str(entry["vnc_url"]) for entry in busy.flows)
    assert resp.status_code == 200
    assert {entry["flow_id"] for entry in resp.json()["flows"]} == set(owned)
    assert all("host-1" in entry["vnc_url"] for entry in resp.json()["flows"])
    assert {entry["flow_id"] for entry in mcp_result["flows"]} == set(owned)

    # cleanup
    for flow_id in owned:
        await novnc_flow_registry.release(flow_id)


@pytest.mark.asyncio
async def test_establish_session_unsafe_url_returns_400(client: AsyncClient) -> None:
    # when
    with patch(
        "src.api.rest.rest_endpoints.check_fetch_uri",
        side_effect=UnsafeUriError("URI resolves to a non-public address"),
    ):
        resp = await client.post(
            "/api/v2/web/session/establish",
            json={"url": "http://192.168.1.1/"},
        )

    # then
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# POST /api/v2/web/session/status
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_status_returns_info(client: AsyncClient) -> None:
    # given
    info = SessionInfo(
        status="active", auth_ttl_remaining=3600.0, last_validated=1_000_000.0, profile="default"
    )

    # when
    with patch.object(SessionManager, "status", new=AsyncMock(return_value=info)):
        resp = await client.post(
            "/api/v2/web/session/status",
            json={"url": "http://example.com/"},
        )

    # then
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "active"
    assert body["auth_ttl_remaining_seconds"] == 3600.0


# ---------------------------------------------------------------------------
# POST /api/v2/web/session/clear
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_clear_returns_cleared_status(client: AsyncClient) -> None:
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "clear", new=AsyncMock(return_value=True)),
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=2,
        ),
    ):
        resp = await client.post(
            "/api/v2/web/session/clear",
            json={"url": "http://example.com/"},
        )

    # then
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "cleared"
    assert body["existed"] is True
    assert body["cleared_cache_entries"] == 2


@pytest.mark.asyncio
async def test_session_clear_is_idempotent_when_nothing_stored(client: AsyncClient) -> None:
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "clear", new=AsyncMock(return_value=False)),
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=0,
        ),
    ):
        resp = await client.post(
            "/api/v2/web/session/clear",
            json={"url": "http://never-stored.example.com/"},
        )

    # then
    assert resp.status_code == 200
    assert resp.json()["existed"] is False


@pytest.mark.asyncio
async def test_session_clear_unsafe_url_returns_400(client: AsyncClient) -> None:
    # when
    with patch(
        "src.api.rest.rest_endpoints.check_fetch_uri",
        side_effect=UnsafeUriError("URI resolves to a non-public address"),
    ):
        resp = await client.post(
            "/api/v2/web/session/clear",
            json={"url": "http://192.168.1.1/"},
        )

    # then
    assert resp.status_code == 400
