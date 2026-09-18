"""Tests for SSRF redirect / DNS-rebinding validation (task 6.2)."""

import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.validator.url_validator import PinnedHost, is_safe_external_url


def _addr(ip: str) -> tuple:
    return (socket.AF_INET, 0, 0, "", (ip, 0))


# ---------------------------------------------------------------------------


def test_safe_public_address():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("93.184.216.34")]):
        assert is_safe_external_url("https://example.com") is True


def test_rejects_loopback():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("127.0.0.1")]):
        assert is_safe_external_url("http://localhost") is False


def test_rejects_private_rfc1918():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("192.168.1.1")]):
        assert is_safe_external_url("http://router") is False


def test_rejects_link_local_aws_imds():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("169.254.169.254")]):
        assert is_safe_external_url("http://imds") is False


def test_rejects_non_http_scheme():
    assert is_safe_external_url("ftp://example.com") is False


# ---------------------------------------------------------------------------
# curl_cffi fetcher: blocked redirect
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_curl_cffi_fetcher_blocks_redirect_to_private_ip():
    """
    When a redirect Location header points to a private IP, the fetcher must
    return '' without following the redirect.
    """
    from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi

    redirect_response = MagicMock()
    redirect_response.status_code = 302
    redirect_response.headers = {"location": "http://192.168.1.1/secret"}
    redirect_response.text = ""
    redirect_response.url = "https://example.com"

    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=False)
    mock_session.get = AsyncMock(return_value=redirect_response)

    with (
        patch("src.reader.strategies.curl_cffi_fetcher.requests.AsyncSession", return_value=mock_session),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_flat_cookies",
            new=AsyncMock(return_value={}),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.cookie_manager.get_user_agent",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "src.reader.strategies.curl_cffi_fetcher.pin_safe_host",
            side_effect=lambda url: (
                None
                if url == "http://192.168.1.1/secret"
                else PinnedHost(host="example.com", port=443, addresses=("93.184.216.34",))
            ),
        ),
    ):
        result = await fetch_with_curl_cffi("https://example.com", lambda: "UA", "test")

    assert result == ""
