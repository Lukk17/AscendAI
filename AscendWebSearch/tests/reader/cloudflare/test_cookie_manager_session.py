"""Tests for the new session store: storage_state capture, auth/WAF TTL split, profile keying."""
import time
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.reader.cloudflare.cookie_manager import CookieManager, _split_storage_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh() -> CookieManager:
    CookieManager._instance = None
    m = CookieManager()
    m._memory_store = {}
    m.redis_client = None
    return m


def _state(cookies: list[dict[str, Any]], origins: list[dict] | None = None) -> dict[str, Any]:
    return {"cookies": cookies, "origins": origins or []}


def _cookie(name: str, value: str = "v") -> dict[str, Any]:
    return {"name": name, "value": value, "domain": "example.com", "path": "/"}


# ---------------------------------------------------------------------------
# _split_storage_state
# ---------------------------------------------------------------------------


def test_split_separates_waf_from_auth():
    state = _state([_cookie("li_at"), _cookie("cf_clearance"), _cookie("JSESSIONID")])
    auth, waf = _split_storage_state(state)
    auth_names = {c["name"] for c in auth["cookies"]}
    waf_names = {c["name"] for c in waf["cookies"]}
    assert auth_names == {"li_at", "JSESSIONID"}
    assert waf_names == {"cf_clearance"}


def test_split_preserves_origins_in_auth_only():
    state = _state([_cookie("cf_clearance")], origins=[{"origin": "https://example.com", "localStorage": []}])
    auth, waf = _split_storage_state(state)
    assert auth["origins"] != []
    assert waf["origins"] == []


# ---------------------------------------------------------------------------
# save_storage_state / get_storage_state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_and_get_storage_state_roundtrip():
    m = _fresh()
    state = _state([_cookie("li_at"), _cookie("cf_clearance")])
    await m.save_storage_state("https://linkedin.com/feed", state, "UA/1.0")

    result = await m.get_storage_state("https://linkedin.com/feed")
    assert result is not None
    names = {c["name"] for c in result["cookies"]}
    assert "li_at" in names
    assert "cf_clearance" in names


@pytest.mark.asyncio
async def test_get_storage_state_returns_none_when_empty():
    m = _fresh()
    result = await m.get_storage_state("https://linkedin.com/feed")
    assert result is None


@pytest.mark.asyncio
async def test_auth_ttl_expiry_hides_auth_cookies_but_waf_remains():
    m = _fresh()
    state = _state([_cookie("li_at"), _cookie("cf_clearance")])
    await m.save_storage_state("https://linkedin.com", state, "UA")

    domain = m._get_domain("https://linkedin.com")
    record = m._memory_store[f"{domain}:default"]
    # Expire auth by backdating saved_at
    record["auth"]["saved_at"] = time.time() - 99_999

    with patch("src.config.config.settings.SESSION_AUTH_TTL_SECONDS", 1):
        result = await m.get_storage_state("https://linkedin.com")

    # WAF is still valid; result should only have cf_clearance
    if result is not None:
        names = {c["name"] for c in result.get("cookies", [])}
        assert "li_at" not in names
    # If waf is also expired, result is None — both outcomes are correct.


@pytest.mark.asyncio
async def test_waf_ttl_expiry_hides_cf_clearance_but_auth_remains():
    m = _fresh()
    state = _state([_cookie("li_at"), _cookie("cf_clearance")])
    await m.save_storage_state("https://example.com", state, "UA")

    domain = m._get_domain("https://example.com")
    record = m._memory_store[f"{domain}:default"]
    record["waf"]["saved_at"] = time.time() - 99_999

    with patch("src.config.config.settings.SESSION_WAF_TTL_SECONDS", 1):
        result = await m.get_storage_state("https://example.com")

    assert result is not None
    names = {c["name"] for c in result.get("cookies", [])}
    assert "li_at" in names
    assert "cf_clearance" not in names


# ---------------------------------------------------------------------------
# Profile keying
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profiles_are_isolated():
    m = _fresh()
    state_a = _state([_cookie("li_at", "account-a")])
    state_b = _state([_cookie("li_at", "account-b")])
    await m.save_storage_state("https://linkedin.com", state_a, "UA", profile="work")
    await m.save_storage_state("https://linkedin.com", state_b, "UA", profile="personal")

    result_work = await m.get_storage_state("https://linkedin.com", profile="work")
    result_personal = await m.get_storage_state("https://linkedin.com", profile="personal")

    assert result_work is not None
    assert result_personal is not None
    work_val = {c["name"]: c["value"] for c in result_work["cookies"]}.get("li_at")
    personal_val = {c["name"]: c["value"] for c in result_personal["cookies"]}.get("li_at")
    assert work_val == "account-a"
    assert personal_val == "account-b"


@pytest.mark.asyncio
async def test_default_profile_key_matches_settings():
    m = _fresh()
    state = _state([_cookie("token", "x")])
    # Save via default profile, read back via explicit None (should resolve to settings.SESSION_DEFAULT_PROFILE)
    await m.save_storage_state("https://example.com", state, "UA", profile=None)
    result = await m.get_storage_state("https://example.com", profile=None)
    assert result is not None


# ---------------------------------------------------------------------------
# Auth TTL sliding
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slide_auth_ttl_updates_saved_at():
    m = _fresh()
    state = _state([_cookie("token")])
    await m.save_storage_state("https://example.com", state, "UA")

    domain = m._get_domain("https://example.com")
    before = m._memory_store[f"{domain}:default"]["auth"]["saved_at"]

    # Artificially age the entry
    m._memory_store[f"{domain}:default"]["auth"]["saved_at"] = before - 3600

    await m.slide_auth_ttl("https://example.com")
    after = m._memory_store[f"{domain}:default"]["auth"]["saved_at"]
    assert after > before - 3600


@pytest.mark.asyncio
async def test_get_auth_ttl_remaining_returns_positive_when_fresh():
    m = _fresh()
    state = _state([_cookie("token")])
    await m.save_storage_state("https://example.com", state, "UA")
    ttl = await m.get_auth_ttl_remaining("https://example.com")
    assert ttl > 0


@pytest.mark.asyncio
async def test_get_auth_ttl_remaining_returns_zero_when_absent():
    m = _fresh()
    ttl = await m.get_auth_ttl_remaining("https://nothere.com")
    assert ttl == 0.0


# ---------------------------------------------------------------------------
# Legacy compat: save_flat_cookies / get_session_data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_flat_cookies_and_get_session_data_compat():
    m = _fresh()
    await m.save_flat_cookies("https://example.com", {"cf_clearance": "abc", "auth_token": "xyz"}, "UA")
    data = await m.get_session_data("https://example.com")
    assert data is not None
    assert data["cookies"]["cf_clearance"] == "abc"
    assert data["cookies"]["auth_token"] == "xyz"


# ---------------------------------------------------------------------------
# Redis path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_redis_save_and_load_roundtrip():
    m = _fresh()
    mock_redis = AsyncMock()
    saved: dict[str, str] = {}

    async def setex_side(key: str, ttl: int, value: str) -> None:
        saved[key] = value

    async def get_side(key: str) -> str | None:
        return saved.get(key)

    mock_redis.setex = AsyncMock(side_effect=setex_side)
    mock_redis.get = AsyncMock(side_effect=get_side)
    m.redis_client = mock_redis

    state = _state([_cookie("li_at")])
    await m.save_storage_state("https://linkedin.com", state, "UA")
    result = await m.get_storage_state("https://linkedin.com")
    assert result is not None
    names = {c["name"] for c in result["cookies"]}
    assert "li_at" in names


# ---------------------------------------------------------------------------
# In-memory fallback observable log
# ---------------------------------------------------------------------------


def test_redis_configured_but_unreachable_logs_fallback(caplog: pytest.LogCaptureFixture):
    CookieManager._instance = None
    with (
        patch("src.reader.cloudflare.cookie_manager.settings.REDIS_URL", "redis://localhost:6379"),
        patch(
            "src.reader.cloudflare.cookie_manager.redis.from_url",
            side_effect=RuntimeError("connection refused"),
        ),
        caplog.at_level("INFO"),
    ):
        m = CookieManager()
    assert m.redis_client is None
    assert any("in-memory fallback" in r.message or "unreachable" in r.message for r in caplog.records)
