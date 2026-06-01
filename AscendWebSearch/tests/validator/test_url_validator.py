import socket
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.validator.url_validator import URLValidator, is_safe_external_url


@pytest.fixture
def mock_blocklist():
    mock = MagicMock()
    mock.should_block.return_value = False
    return mock


def test_url_validator_should_block_returns_false_for_clean(mock_blocklist):
    validator = URLValidator(rules=mock_blocklist)
    assert validator.should_block("https://example.com") is False


def test_url_validator_should_block_returns_true_when_rules_match(mock_blocklist):
    mock_blocklist.should_block.return_value = True
    validator = URLValidator(rules=mock_blocklist)
    assert validator.should_block("https://ads.example.com") is True


@pytest.mark.asyncio
async def test_route_handler_continues_for_allowed(mock_blocklist):
    validator = URLValidator(rules=mock_blocklist)
    route = MagicMock()
    route.request.url = "https://example.com"
    route.continue_ = AsyncMock()
    route.abort = AsyncMock()
    await validator.route_handler(route)
    route.continue_.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_handler_aborts_for_blocked(mock_blocklist):
    mock_blocklist.should_block.return_value = True
    validator = URLValidator(rules=mock_blocklist)
    route = MagicMock()
    route.request.url = "https://ads.example.com"
    route.continue_ = AsyncMock()
    route.abort = AsyncMock()
    await validator.route_handler(route)
    route.abort.assert_awaited_once()


def _addr(ip: str):
    return (socket.AF_INET, 0, 0, "", (ip, 0))


def test_is_safe_external_url_valid_public_address():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("93.184.216.34")]):
        assert is_safe_external_url("https://example.com") is True


def test_is_safe_external_url_rejects_non_http_scheme():
    assert is_safe_external_url("ftp://example.com") is False


def test_is_safe_external_url_rejects_no_host():
    assert is_safe_external_url("http://") is False


def test_is_safe_external_url_unresolvable_returns_false():
    with patch("src.validator.url_validator.socket.getaddrinfo", side_effect=socket.gaierror("nope")):
        assert is_safe_external_url("http://nope.invalid") is False


def test_is_safe_external_url_rejects_loopback():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("127.0.0.1")]):
        assert is_safe_external_url("http://localhost") is False


def test_is_safe_external_url_rejects_private():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("10.0.0.1")]):
        assert is_safe_external_url("http://internal") is False


def test_is_safe_external_url_rejects_link_local_aws_imds():
    with patch("src.validator.url_validator.socket.getaddrinfo", return_value=[_addr("169.254.169.254")]):
        assert is_safe_external_url("http://imds") is False


def test_is_safe_external_url_handles_value_error_in_ip_parse():
    # malformed address returned by getaddrinfo (artificial)
    with patch(
        "src.validator.url_validator.socket.getaddrinfo",
        return_value=[(socket.AF_INET, 0, 0, "", ("not-an-ip", 0))],
    ):
        assert is_safe_external_url("http://example.com") is False


def test_is_safe_external_url_handles_urlparse_exception():
    with patch("src.validator.url_validator.urlparse", side_effect=ValueError("bad")):
        assert is_safe_external_url("http://example.com") is False
