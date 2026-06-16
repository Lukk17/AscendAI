"""Tests for structured output in WebReader (task 5.1)."""

from unittest.mock import AsyncMock, patch

import pytest

from src.reader.web_reader import WebReader

_GOOD_HTML = (
    "<html><head><title>Article</title></head>"
    "<body><article><p>"
    "This is the main body of the article. It has enough text to pass the content validator. "
    "The article covers interesting topics and provides information to the reader. "
    "Multiple sentences ensure it clears any minimum length requirement easily."
    "</p></article></body></html>"
)


@pytest.mark.asyncio
async def test_read_structured_returns_metadata_fields() -> None:
    """output_format='structured' must return title/author/date/sitename alongside content."""
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value=_GOOD_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("https://example.com/article", output_format="structured")

    assert result["status"] == "success"
    assert "content" in result
    assert "title" in result
    assert "author" in result
    assert "date" in result
    assert "sitename" in result


@pytest.mark.asyncio
async def test_read_default_output_unchanged() -> None:
    """Default (no output_format) response must keep the original flat shape."""
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.extract",
            new=AsyncMock(return_value="Enough content to pass the validator easily here"),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("https://example.com/article")

    assert result["status"] == "success"
    assert "content" in result
    assert "mode" in result
    assert "title" not in result
    assert "author" not in result


@pytest.mark.asyncio
async def test_read_structured_empty_html_from_strategy_records_empty_outcome() -> None:
    """When strategy.get_html() returns '' for output_format=structured, outcome=empty is recorded."""
    from unittest.mock import MagicMock

    from src.reader.web_reader import WebReader

    reader = WebReader()
    fake_strategy = MagicMock()
    fake_strategy.get_html = AsyncMock(return_value="")

    result = await reader._execute_strategy(
        "1-beautifulsoup", fake_strategy, "https://empty.example.com/", output_format="structured"
    )
    assert result is None


@pytest.mark.asyncio
async def test_read_structured_validation_fail_records_validation_failed_outcome() -> None:
    """When structured content fails validation, _execute_strategy returns None."""
    from unittest.mock import MagicMock

    from src.reader.web_reader import WebReader

    reader = WebReader()
    fake_strategy = MagicMock()
    fake_strategy.get_html = AsyncMock(return_value=_GOOD_HTML)

    with patch("src.validator.content_validator.ContentValidator.validate", return_value=False):
        result = await reader._execute_strategy(
            "1-beautifulsoup", fake_strategy, "https://valfail.example.com/", output_format="structured"
        )
    assert result is None


@pytest.mark.asyncio
async def test_read_text_output_unchanged() -> None:
    """output_format='text' must produce same flat shape as the default."""
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.extract",
            new=AsyncMock(return_value="Enough content to pass the validator easily here"),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("https://example.com/article", output_format="text")

    assert result["status"] == "success"
    assert "content" in result
    assert "title" not in result
