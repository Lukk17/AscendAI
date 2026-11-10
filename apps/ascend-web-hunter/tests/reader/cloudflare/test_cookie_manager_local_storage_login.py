"""A login the site keeps only in localStorage counts as a saved login.

Covered in the store, the session status and the read path.
"""

import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.reader.cloudflare.cookie_manager import PRODUCED_BY_NOVNC, CookieManager
from src.session.session_manager import SessionManager

_URL = "https://app.example.com/dashboard"
_SITE_ORIGIN = "https://app.example.com"
_THIRD_PARTY_ORIGIN = "https://widgets.thirdparty.net"


def _fresh() -> CookieManager:
    CookieManager._instance = None
    manager = CookieManager()
    manager._memory_store = {}
    manager.redis_client = None

    return manager


def _origin(address: str, *names: str) -> dict[str, Any]:
    return {"origin": address, "localStorage": [{"name": name, "value": f"{name}-value"} for name in names]}


def _state(*origins: dict[str, Any], cookies: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"cookies": cookies or [], "origins": list(origins)}


async def _save_login(manager: CookieManager, state: dict[str, Any]) -> None:
    await manager.save_storage_state(_URL, state, "ua", None, PRODUCED_BY_NOVNC, replaces_login=True)


async def test_a_local_storage_only_login_is_valid_and_restored() -> None:
    # given
    manager = _fresh()
    state = _state(_origin(_SITE_ORIGIN, "auth_token"))
    await _save_login(manager, state)

    # when
    ttl_remaining = await manager.get_auth_ttl_remaining(_URL)
    restored = await manager.get_storage_state(_URL)

    # then
    assert ttl_remaining > 0
    assert restored == state
    assert await manager.has_valid_login(_URL) is True
    assert await manager.has_auth_state(_URL) is True
    assert await manager.get_stored_session_producer(_URL) == PRODUCED_BY_NOVNC


@pytest.mark.parametrize(
    "origins",
    [
        [_origin(_THIRD_PARTY_ORIGIN, "auth_token")],
        [_origin(_SITE_ORIGIN, "_ga", "OptanonConsent")],
        [{"origin": _SITE_ORIGIN, "localStorage": []}],
    ],
    ids=["third-party-origin", "tracking-only", "empty-origin"],
)
async def test_local_storage_the_site_did_not_set_as_login_state_is_no_session(
    origins: list[dict[str, Any]],
) -> None:
    # given
    manager = _fresh()
    await _save_login(manager, _state(*origins))

    # when
    ttl_remaining = await manager.get_auth_ttl_remaining(_URL)

    # then
    assert ttl_remaining == 0.0
    assert await manager.get_storage_state(_URL) is None
    assert await manager.has_valid_login(_URL) is False
    assert await manager.has_auth_state(_URL) is False


async def test_a_local_storage_only_login_still_lapses_at_the_ceiling() -> None:
    # given
    manager = _fresh()
    await _save_login(manager, _state(_origin(_SITE_ORIGIN, "auth_token")))
    manager._memory_store["example.com:default"]["auth"]["saved_at"] = time.time() - 10_000_000

    # when
    ttl_remaining = await manager.get_auth_ttl_remaining(_URL)

    # then
    assert ttl_remaining == 0.0
    assert await manager.has_auth_state(_URL) is True


async def test_a_capture_without_the_local_storage_login_keeps_the_stored_login() -> None:
    # given
    manager = _fresh()
    login = _state(_origin(_SITE_ORIGIN, "auth_token"))
    await _save_login(manager, login)

    # when
    await manager.save_storage_state(
        _URL, _state(cookies=[{"name": "cf_clearance", "value": "c", "domain": ".example.com"}]), "ua"
    )

    # then
    assert await manager.has_valid_login(_URL) is True
    assert manager._memory_store["example.com:default"]["auth"]["storage_state"] == login


async def test_a_capture_carrying_the_local_storage_login_forward_replaces_it() -> None:
    # given
    manager = _fresh()
    await _save_login(manager, _state(_origin(_SITE_ORIGIN, "auth_token")))
    renewed = _state(_origin(_SITE_ORIGIN, "auth_token", "theme"))

    # when
    await manager.save_storage_state(_URL, renewed, "ua")

    # then
    assert manager._memory_store["example.com:default"]["auth"]["storage_state"] == renewed
    assert await manager.has_valid_login(_URL) is True


async def test_session_status_and_validate_accept_a_local_storage_only_login() -> None:
    # given
    manager = _fresh()
    await _save_login(manager, _state(_origin(_SITE_ORIGIN, "auth_token")))
    session_manager = SessionManager()

    # when
    with patch("src.session.session_manager.cookie_manager", manager):
        info = await session_manager.status(_URL)
        valid = await session_manager.validate(_URL)

    # then
    assert info.status == "active"
    assert valid is True


async def test_validate_refuses_a_stored_state_holding_only_third_party_local_storage() -> None:
    # given
    session_manager = SessionManager()

    # when
    with (
        patch(
            "src.session.session_manager.cookie_manager.get_auth_ttl_remaining",
            new=AsyncMock(return_value=86400.0),
        ),
        patch(
            "src.session.session_manager.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=_state(_origin(_THIRD_PARTY_ORIGIN, "auth_token"))),
        ),
    ):
        valid = await session_manager.validate(_URL)

    # then
    assert valid is False


async def test_the_read_path_does_not_gate_a_valid_local_storage_only_login() -> None:
    # given
    from src.reader.web_reader import WebReader

    manager = _fresh()
    await _save_login(manager, _state(_origin(_SITE_ORIGIN, "auth_token")))

    # when
    with (
        patch("src.reader.web_reader.cookie_manager", manager),
        patch("src.session.session_manager.cookie_manager", manager),
    ):
        expired = await WebReader._session_expired(_URL, None)

    # then
    assert expired is False


async def test_the_read_path_reports_a_lapsed_local_storage_only_login_as_expired() -> None:
    # given
    from src.reader.web_reader import WebReader

    manager = _fresh()
    await _save_login(manager, _state(_origin(_SITE_ORIGIN, "auth_token")))
    manager._memory_store["example.com:default"]["auth"]["saved_at"] = time.time() - 10_000_000

    # when
    with (
        patch("src.reader.web_reader.cookie_manager", manager),
        patch("src.session.session_manager.cookie_manager", manager),
    ):
        expired = await WebReader._session_expired(_URL, None)

    # then
    assert expired is True
