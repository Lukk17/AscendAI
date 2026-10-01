"""Tests for the record-presence questions the read and session layers ask: has_auth_cookies,
has_session_record and get_auth_saved_at.

Change close-web-search-scraping-follow-ups, task 2.1.
"""

import time
from typing import Any

from src.reader.cloudflare.cookie_manager import PRODUCED_BY_FLARESOLVERR, CookieManager

_URL = "https://example.com/article"


def _fresh() -> CookieManager:
    CookieManager._instance = None
    manager = CookieManager()
    manager._memory_store = {}
    manager.redis_client = None

    return manager


def _cookie(name: str) -> dict[str, Any]:
    return {"name": name, "value": "v", "domain": "example.com", "path": "/"}


async def test_no_record_means_no_auth_cookies():
    # given
    manager = _fresh()

    # when / then
    assert await manager.has_auth_cookies(_URL) is False


async def test_a_captured_login_has_auth_cookies():
    # given
    manager = _fresh()
    await manager.save_storage_state(
        _URL, {"cookies": [_cookie("li_at")], "origins": []}, "ua", None, PRODUCED_BY_FLARESOLVERR
    )

    # when / then
    assert await manager.has_auth_cookies(_URL) is True


async def test_a_lapsed_login_still_has_auth_cookies():
    """The gate asks whether a login was ever captured, not whether it is still valid."""
    # given
    manager = _fresh()
    await manager.save_storage_state(_URL, {"cookies": [_cookie("li_at")], "origins": []}, "ua")
    stored = manager._memory_store["example.com:default"]
    stored["auth"]["saved_at"] = time.time() - 10_000_000

    # when / then
    assert await manager.has_auth_cookies(_URL) is True


async def test_a_waf_only_record_has_no_auth_cookies():
    # given
    manager = _fresh()
    await manager.save_flat_cookies(_URL, {"cf_clearance": "x"}, "ua", None, PRODUCED_BY_FLARESOLVERR)

    # when / then
    assert await manager.has_auth_cookies(_URL) is False


async def test_a_profile_without_a_login_is_independent_of_one_with():
    # given
    manager = _fresh()
    await manager.save_storage_state(_URL, {"cookies": [_cookie("li_at")], "origins": []}, "ua", "work")

    # when / then
    assert await manager.has_auth_cookies(_URL, "work") is True
    assert await manager.has_auth_cookies(_URL, "personal") is False


async def test_nothing_stored_means_no_session_record():
    # given
    manager = _fresh()

    # when / then
    assert await manager.has_session_record(_URL) is False


async def test_a_waf_only_record_is_still_a_session_record():
    """Wider than has_auth_cookies on purpose: this is what tells an expired
    session apart from one that was never established."""
    # given
    manager = _fresh()
    await manager.save_flat_cookies(_URL, {"cf_clearance": "x"}, "ua", None, PRODUCED_BY_FLARESOLVERR)

    # when / then
    assert await manager.has_session_record(_URL) is True
    assert await manager.has_session_record(_URL, "personal") is False


async def test_auth_saved_at_reports_the_stored_timestamp():
    # given
    manager = _fresh()
    await manager.save_storage_state(_URL, {"cookies": [_cookie("li_at")], "origins": []}, "ua")
    stored = manager._memory_store["example.com:default"]
    stored["auth"]["saved_at"] = 1_000_000.0

    # when / then
    assert await manager.get_auth_saved_at(_URL) == 1_000_000.0


async def test_auth_saved_at_is_none_when_nothing_is_stored():
    # given
    manager = _fresh()

    # when / then
    assert await manager.get_auth_saved_at(_URL) is None


async def test_auth_saved_at_is_none_for_a_record_carrying_no_auth_entry():
    # given
    manager = _fresh()
    manager._memory_store["example.com:default"] = {"waf": {"saved_at": 1_000_000.0}}

    # when / then
    assert await manager.get_auth_saved_at(_URL) is None


async def test_auth_saved_at_is_none_when_the_stored_value_is_not_a_number():
    """A record written before the field existed, or by something that wrote
    junk into it, reports no timestamp rather than handing one out."""
    # given
    manager = _fresh()
    await manager.save_storage_state(_URL, {"cookies": [_cookie("li_at")], "origins": []}, "ua")
    stored = manager._memory_store["example.com:default"]
    stored["auth"]["saved_at"] = "not-a-timestamp"

    # when / then
    assert await manager.get_auth_saved_at(_URL) is None
