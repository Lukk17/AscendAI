from unittest.mock import MagicMock, AsyncMock

import pytest

from src.validator.url_validator import URLValidator


@pytest.fixture
def mock_blocklist():
    mock = MagicMock()
    mock.should_block.return_value = False  # Default allow
    return mock


def test_is_safe_url_valid(mock_blocklist):
    # given
    validator = URLValidator(rules=mock_blocklist)
    url = "https://example.com"

    # when
    # should_block returns True if blocked (unsafe)
    result = validator.should_block(url)

    # then
    assert result is False  # Safe URL should NOT be blocked


def test_is_safe_url_blocked(mock_blocklist):
    # given
    mock_blocklist.should_block.return_value = True
    validator = URLValidator(rules=mock_blocklist)
    url = "https://ads.example.com"

    # when
    result = validator.should_block(url)

    # then
    assert result is True  # Unsafe URL SHOULD be blocked


def test_route_handler(mock_blocklist):
    # given
    validator = URLValidator(rules=mock_blocklist)
    mock_route = MagicMock()
    mock_route.request.url = "https://example.com"
    mock_route.continue_ = AsyncMock()  # Must be awaitable
    mock_route.abort = AsyncMock()  # Must be awaitable

    # when
    import asyncio
    loop = asyncio.new_event_loop()
    loop.run_until_complete(validator.route_handler(mock_route))
    loop.close()

    # then
    mock_route.continue_.assert_called()
