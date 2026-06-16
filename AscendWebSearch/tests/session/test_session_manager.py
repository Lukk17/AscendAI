"""Tests for SessionManager (task 3.1-3.2)."""

from unittest.mock import AsyncMock, patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException
from src.session.session_manager import SessionManager


@pytest.fixture
def mgr() -> SessionManager:
    return SessionManager()


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_status_returns_none_when_no_session(mgr: SessionManager):
    with patch(
        "src.session.session_manager.cookie_manager.get_auth_ttl_remaining",
        new=AsyncMock(return_value=0.0),
    ):
        with patch(
            "src.session.session_manager.cookie_manager._load_record",
            new=AsyncMock(return_value=None),
        ):
            info = await mgr.status("https://linkedin.com")

    assert info.status == "none"
    assert info.auth_ttl_remaining == 0.0


@pytest.mark.asyncio
async def test_status_returns_expired_when_record_exists_but_ttl_zero(mgr: SessionManager):
    with patch(
        "src.session.session_manager.cookie_manager.get_auth_ttl_remaining",
        new=AsyncMock(return_value=0.0),
    ):
        with patch(
            "src.session.session_manager.cookie_manager._load_record",
            new=AsyncMock(return_value={"auth": {"saved_at": 0}}),
        ):
            info = await mgr.status("https://linkedin.com")

    assert info.status == "expired"


@pytest.mark.asyncio
async def test_status_returns_active_when_ttl_positive(mgr: SessionManager):
    with patch(
        "src.session.session_manager.cookie_manager.get_auth_ttl_remaining",
        new=AsyncMock(return_value=86400.0),
    ):
        with patch(
            "src.session.session_manager.cookie_manager._load_record",
            new=AsyncMock(return_value={"auth": {"saved_at": 1_000_000.0}}),
        ):
            info = await mgr.status("https://linkedin.com")

    assert info.status == "active"
    assert info.auth_ttl_remaining == 86400.0
    assert info.last_validated == 1_000_000.0


@pytest.mark.asyncio
async def test_status_returns_active_with_no_auth_key_in_record(mgr: SessionManager):
    with patch(
        "src.session.session_manager.cookie_manager.get_auth_ttl_remaining",
        new=AsyncMock(return_value=86400.0),
    ):
        with patch(
            "src.session.session_manager.cookie_manager._load_record",
            new=AsyncMock(return_value={"cookies": []}),
        ):
            info = await mgr.status("https://linkedin.com")

    assert info.status == "active"
    assert info.last_validated is None


def test_session_info_to_dict(mgr: SessionManager):
    from src.session.session_manager import SessionInfo

    info = SessionInfo(status="active", auth_ttl_remaining=3600.0, last_validated=1_000_000.0, profile="work")
    d = info.to_dict()
    assert d["status"] == "active"
    assert d["auth_ttl_remaining_seconds"] == 3600.0
    assert d["profile"] == "work"


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_returns_false_when_ttl_expired(mgr: SessionManager):
    with patch(
        "src.session.session_manager.cookie_manager.get_auth_ttl_remaining",
        new=AsyncMock(return_value=0.0),
    ):
        result = await mgr.validate("https://linkedin.com")

    assert result is False


@pytest.mark.asyncio
async def test_validate_returns_false_when_no_cookies(mgr: SessionManager):
    with (
        patch(
            "src.session.session_manager.cookie_manager.get_auth_ttl_remaining",
            new=AsyncMock(return_value=86400.0),
        ),
        patch(
            "src.session.session_manager.cookie_manager.get_storage_state",
            new=AsyncMock(return_value={"cookies": [], "origins": []}),
        ),
    ):
        result = await mgr.validate("https://linkedin.com")

    assert result is False


@pytest.mark.asyncio
async def test_validate_slides_ttl_on_success(mgr: SessionManager):
    with (
        patch(
            "src.session.session_manager.cookie_manager.get_auth_ttl_remaining",
            new=AsyncMock(return_value=86400.0),
        ),
        patch(
            "src.session.session_manager.cookie_manager.get_storage_state",
            new=AsyncMock(return_value={"cookies": [{"name": "li_at", "value": "x"}], "origins": []}),
        ),
        patch(
            "src.session.session_manager.cookie_manager.slide_auth_ttl",
            new=AsyncMock(),
        ) as mock_slide,
    ):
        result = await mgr.validate("https://linkedin.com")

    assert result is True
    mock_slide.assert_awaited_once()


# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_establish_returns_vnc_url(mgr: SessionManager):
    exc = HumanInterventionRequiredException("http://vnc:7900", "login")
    with patch(
        "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
        new=AsyncMock(side_effect=exc),
    ):
        result = await mgr.establish("https://linkedin.com/login")

    assert result == "http://vnc:7900"


@pytest.mark.asyncio
async def test_establish_raises_runtime_error_when_no_intervention(mgr: SessionManager):
    with patch(
        "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
        new=AsyncMock(return_value=""),
    ):
        with pytest.raises(RuntimeError, match="NoVNC flow did not surface a VNC URL"):
            await mgr.establish("https://linkedin.com/login")
