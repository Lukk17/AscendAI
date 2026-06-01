from unittest.mock import MagicMock, patch

import pytest

from src.config.startup_banner import (
    _probe_http_sync,
    _probe_tcp_sync,
    _resolve_host,
    log_startup_banner,
)


def test_resolve_host_returns_hostname():
    with patch("src.config.startup_banner.socket.gethostname", return_value="test-host"):
        assert _resolve_host() == "test-host"


def test_resolve_host_falls_back_to_localhost():
    with patch("src.config.startup_banner.socket.gethostname", side_effect=OSError()):
        assert _resolve_host() == "localhost"


def test_probe_http_sync_success():
    mock_response = MagicMock()
    mock_response.status = 200
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch("src.config.startup_banner.urllib.request.urlopen", return_value=mock_response):
        result = _probe_http_sync("http://upstream")
    assert "Connected" in result


def test_probe_http_sync_warns_on_non_2xx():
    mock_response = MagicMock()
    mock_response.status = 503
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=False)
    with patch("src.config.startup_banner.urllib.request.urlopen", return_value=mock_response):
        result = _probe_http_sync("http://upstream")
    assert "Warning" in result


def test_probe_http_sync_http_error():
    import urllib.error
    from email.message import Message

    err = urllib.error.HTTPError("http://upstream", 502, "Bad Gateway", Message(), None)
    with patch("src.config.startup_banner.urllib.request.urlopen", side_effect=err):
        result = _probe_http_sync("http://upstream")
    assert "Warning" in result


def test_probe_http_sync_other_error():
    with patch("src.config.startup_banner.urllib.request.urlopen", side_effect=RuntimeError("dns")):
        result = _probe_http_sync("http://upstream")
    assert "FAILED" in result


def test_probe_tcp_sync_success():
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    with patch("src.config.startup_banner.socket.create_connection", return_value=mock_conn):
        result = _probe_tcp_sync("redis://localhost:6379")
    assert "Connected" in result


def test_probe_tcp_sync_failure():
    with patch("src.config.startup_banner.socket.create_connection", side_effect=OSError()):
        result = _probe_tcp_sync("redis://localhost:6379")
    assert "FAILED" in result


@pytest.mark.asyncio
async def test_log_startup_banner_smoke():
    with (
        patch(
            "src.config.startup_banner.asyncio.to_thread",
            side_effect=lambda fn, *a, **kw: (
                _probe_http_sync.__wrapped__(*a)  # type: ignore[attr-defined]
                if hasattr(_probe_http_sync, "__wrapped__")
                else "[Connected]"
            ),
        ),
        patch("src.config.startup_banner.logger") as mock_logger,
    ):
        await log_startup_banner()
    mock_logger.info.assert_called()
