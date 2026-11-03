import re
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient

from src.reader.cloudflare.cookie_manager import PRODUCED_BY_IMPORT, PRODUCED_BY_LOGIN_SEED
from src.session.session_manager import SessionManager

_URL = "https://www.example.net/page"
_STORAGE = {
    "cookies": [
        {
            "name": "sessionid",
            "value": "canary-auth-1",
            "domain": ".example.net",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        },
        {
            "name": "cf_clearance",
            "value": "canary-waf-1",
            "domain": ".example.net",
            "path": "/",
            "expires": -1,
            "httpOnly": True,
            "secure": True,
            "sameSite": "None",
        },
        {
            "name": "other",
            "value": "drop-me",
            "domain": ".example.org",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        },
    ],
    "origins": [],
}

_TRACE_RE = re.compile(r"[0-9a-f]{32}")


def _payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "url": _URL,
        "profile": "e2e",
        "storage_state": _STORAGE,
        "user_agent": "import-test/1.0",
    }
    base.update(overrides)

    return base


def _assert_problem(body: dict[str, Any], code: str, instance: str = "/api/v2/web/session/import") -> None:
    assert body["code"] == code
    assert body["type"] == f"https://ascend.ai/errors/{code.replace('_', '-')}"
    assert body["status"] == 400
    assert body["instance"] == instance
    assert _TRACE_RE.fullmatch(body["traceId"]) is not None


@pytest.mark.asyncio
async def test_import_success_returns_d3_body_and_stores_filtered(client: AsyncClient) -> None:
    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=1,
        ) as mock_purge,
    ):
        resp = await client.post("/api/v2/web/session/import", json=_payload())

    # then
    assert resp.status_code == 200
    body = resp.json()
    assert body == {
        "status": "imported",
        "domain": "example.net",
        "profile": "e2e",
        "auth_cookies": 1,
        "waf_cookies": 1,
        "dropped_cookies": 1,
    }
    mock_save.assert_awaited_once()
    _, kwargs = mock_save.call_args
    assert kwargs["produced_by"] == PRODUCED_BY_IMPORT
    assert kwargs["produced_by"] == "import"
    saved_state = mock_save.call_args.args[1]
    saved_names = {c["name"] for c in saved_state["cookies"]}
    assert saved_names == {"sessionid", "cf_clearance"}
    mock_purge.assert_called_once_with("example.net")


@pytest.mark.asyncio
async def test_import_success_defaults_profile(client: AsyncClient) -> None:
    # given
    payload = _payload()
    del payload["profile"]

    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=0,
        ),
    ):
        resp = await client.post("/api/v2/web/session/import", json=payload)

    # then
    assert resp.status_code == 200
    assert resp.json()["profile"] == "default"
    _, kwargs = mock_save.call_args
    assert kwargs["produced_by"] == PRODUCED_BY_IMPORT


@pytest.mark.asyncio
async def test_import_accepts_1000_cookies_for_domain(client: AsyncClient) -> None:
    # given
    cookies = [
        {
            "name": f"c{i}",
            "value": "v",
            "domain": ".example.net",
            "path": "/",
            "expires": -1,
            "httpOnly": False,
            "secure": True,
            "sameSite": "Lax",
        }
        for i in range(1000)
    ]
    payload = _payload(storage_state={"cookies": cookies, "origins": []})

    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=0,
        ),
    ):
        resp = await client.post("/api/v2/web/session/import", json=payload)

    # then
    assert resp.status_code == 200
    body = resp.json()
    assert body["auth_cookies"] == 1000
    assert body["waf_cookies"] == 0
    assert body["dropped_cookies"] == 0
    mock_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_import_bad_url_answers_validation(client: AsyncClient) -> None:
    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=0,
        ) as mock_purge,
    ):
        resp = await client.post("/api/v2/web/session/import", json=_payload(url="not-a-url"))

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    body = resp.json()
    assert body["code"] == "validation"
    assert isinstance(body["errors"], list)
    assert len(body["errors"]) > 0
    mock_save.assert_not_awaited()
    mock_purge.assert_not_called()


@pytest.mark.asyncio
async def test_import_unknown_field_answers_validation(client: AsyncClient) -> None:
    # given
    payload = _payload()
    payload["unknown_field"] = "nope"

    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=0,
        ) as mock_purge,
    ):
        resp = await client.post("/api/v2/web/session/import", json=payload)

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    assert resp.json()["code"] == "validation"
    mock_save.assert_not_awaited()
    mock_purge.assert_not_called()


@pytest.mark.asyncio
async def test_import_unknown_storage_field_answers_validation(client: AsyncClient) -> None:
    # given
    payload = _payload(storage_state={"cookies": [], "origins": [], "extra": 1})

    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=0,
        ) as mock_purge,
    ):
        resp = await client.post("/api/v2/web/session/import", json=payload)

    # then
    assert resp.status_code == 400
    assert resp.json()["code"] == "validation"
    mock_save.assert_not_awaited()
    mock_purge.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/admin",
        "http://[::1]/",
        "http://localhost/",
        "http://singlelabel/",
    ],
    ids=["ipv4", "ipv6", "localhost", "single-label"],
)
async def test_import_host_without_registrable_domain_answers_unsafe_uri(
    client: AsyncClient, url: str
) -> None:
    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=0,
        ) as mock_purge,
        patch("socket.getaddrinfo", side_effect=AssertionError("no lookup allowed")),
    ):
        resp = await client.post("/api/v2/web/session/import", json=_payload(url=url))

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    _assert_problem(resp.json(), "unsafe_uri")
    mock_save.assert_not_awaited()
    mock_purge.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "profile",
    ["bad profile!", "", "a" * 65, "with/slash", "semi;colon"],
    ids=["space-bang", "empty", "too-long", "slash", "semicolon"],
)
async def test_import_bad_profile_answers_invalid_profile(client: AsyncClient, profile: str) -> None:
    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=0,
        ) as mock_purge,
    ):
        resp = await client.post("/api/v2/web/session/import", json=_payload(profile=profile))

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    _assert_problem(resp.json(), "invalid_profile")
    mock_save.assert_not_awaited()
    mock_purge.assert_not_called()


@pytest.mark.asyncio
async def test_import_no_cookie_for_domain_answers_no_cookies_for_domain(
    client: AsyncClient,
) -> None:
    # given
    foreign = {
        "cookies": [
            {
                "name": "other",
                "value": "x",
                "domain": ".example.org",
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            }
        ],
        "origins": [],
    }

    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ) as mock_save,
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=0,
        ) as mock_purge,
    ):
        resp = await client.post("/api/v2/web/session/import", json=_payload(storage_state=foreign))

    # then
    assert resp.status_code == 400
    assert "application/problem+json" in resp.headers["content-type"]
    _assert_problem(resp.json(), "no_cookies_for_domain")
    mock_save.assert_not_awaited()
    mock_purge.assert_not_called()


@pytest.mark.asyncio
async def test_imported_record_replays_like_login_seed() -> None:
    # given
    from src.reader.web_reader import WebReader

    reader = WebReader()
    stored = {"cookies": [{"name": "sessionid", "value": "x"}], "origins": []}

    async def _strategy_keys(producer: str) -> list[str]:
        with (
            patch(
                "src.reader.web_reader.cookie_manager.get_storage_state",
                new=AsyncMock(return_value=stored),
            ),
            patch(
                "src.reader.web_reader.cookie_manager.get_stored_session_producer",
                new=AsyncMock(return_value=producer),
            ),
        ):
            strategies = await reader._select_strategies("https://www.example.net/", False, None, None)

            return list(strategies)

    # when
    import_keys = await _strategy_keys(PRODUCED_BY_IMPORT)
    seed_keys = await _strategy_keys(PRODUCED_BY_LOGIN_SEED)

    # then
    assert PRODUCED_BY_IMPORT == "import"
    assert import_keys == seed_keys
    assert import_keys


@pytest.mark.asyncio
async def test_import_success_publishes_domain_purge_once(client: AsyncClient) -> None:
    # when
    with (
        patch(
            "src.api.rest.rest_endpoints.cookie_manager.save_storage_state",
            new=AsyncMock(),
        ),
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=1,
        ) as mock_clear,
        patch(
            "src.api.rest.rest_endpoints.publish_purge",
            new=AsyncMock(return_value=True),
        ) as mock_publish,
    ):
        resp = await client.post("/api/v2/web/session/import", json=_payload())

    # then
    assert resp.status_code == 200
    mock_clear.assert_called_once_with("example.net")
    mock_publish.assert_awaited_once_with("example.net")


@pytest.mark.asyncio
async def test_session_clear_still_publishes_domain_purge_once(client: AsyncClient) -> None:
    # when
    with (
        patch("src.api.rest.rest_endpoints.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "clear", new=AsyncMock(return_value=True)),
        patch(
            "src.api.rest.rest_endpoints.web_reader.clear_cache_for_domain",
            return_value=2,
        ) as mock_clear,
        patch(
            "src.api.rest.rest_endpoints.publish_purge",
            new=AsyncMock(return_value=True),
        ) as mock_publish,
    ):
        resp = await client.post(
            "/api/v2/web/session/clear",
            json={"url": "https://www.example.net/page"},
        )

    # then
    assert resp.status_code == 200
    mock_clear.assert_called_once_with("example.net")
    mock_publish.assert_awaited_once_with("example.net")
