from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.validator.url_validator import URLValidator


@pytest.fixture
def mock_blocklist() -> Any:
    mock = MagicMock()
    mock.should_block.return_value = False
    return mock


def test_url_validator_should_block_returns_false_for_clean(mock_blocklist: Any) -> None:
    # given
    validator = URLValidator(rules=mock_blocklist)

    # when / then
    assert validator.should_block("https://example.com") is False


def test_url_validator_should_block_returns_true_when_rules_match(mock_blocklist: Any) -> None:
    # given
    mock_blocklist.should_block.return_value = True
    validator = URLValidator(rules=mock_blocklist)

    # when / then
    assert validator.should_block("https://ads.example.com") is True


@pytest.mark.asyncio
async def test_route_handler_continues_for_allowed(mock_blocklist: Any) -> None:
    # given
    validator = URLValidator(rules=mock_blocklist)
    route = MagicMock()
    route.request.url = "https://example.com"
    route.continue_ = AsyncMock()
    route.abort = AsyncMock()

    # when
    await validator.route_handler(route)

    # then
    route.continue_.assert_awaited_once()


@pytest.mark.asyncio
async def test_route_handler_aborts_for_blocked(mock_blocklist: Any) -> None:
    # given
    mock_blocklist.should_block.return_value = True
    validator = URLValidator(rules=mock_blocklist)
    route = MagicMock()
    route.request.url = "https://ads.example.com"
    route.continue_ = AsyncMock()
    route.abort = AsyncMock()

    # when
    await validator.route_handler(route)

    # then
    route.abort.assert_awaited_once()
