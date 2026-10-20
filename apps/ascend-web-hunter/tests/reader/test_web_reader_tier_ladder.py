"""The patched browser tiers sit between Playwright and Crawlee (task 2.3)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError

from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.web_reader import TIER_ORDER, WebReader

_URL = "https://example.com/article"

_ARTICLE_HTML = (
    "<html><head><title>Article</title></head>"
    "<body><article><p>"
    "This is a genuine paragraph of article content with more than ten words in it. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    "</p></article></body></html>"
)


def _stub_strategies(winners: dict[str, str]) -> dict[str, BaseStrategy]:
    """One stub strategy per ladder rung; rungs missing from *winners* return no HTML."""
    strategies: dict[str, BaseStrategy] = {}
    for name in TIER_ORDER:
        stub = MagicMock()
        stub.get_html = AsyncMock(return_value=winners.get(name, ""))
        strategies[name] = stub

    return strategies


@pytest.mark.asyncio
async def test_chain_reaches_camoufox_after_earlier_browser_tiers_fail() -> None:
    # given
    stubs = _stub_strategies({"4b-camoufox": _ARTICLE_HTML})

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read(_URL)

    # then
    assert result["mode"] == "4b-camoufox"


@pytest.mark.asyncio
async def test_disabled_camoufox_is_skipped() -> None:
    # given
    stubs = _stub_strategies({"4b-camoufox": _ARTICLE_HTML, "5-crawlee_adaptive": _ARTICLE_HTML})

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.settings.CAMOUFOX_ENABLED", False),
    ):
        result = await WebReader().read(_URL)

    # then
    assert result["mode"] == "5-crawlee_adaptive"
    stubs["4b-camoufox"].get_html.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_disabled_camoufox_is_skipped_in_heavy_mode() -> None:
    # given
    stubs = _stub_strategies({"4b-camoufox": _ARTICLE_HTML, "5-crawlee_adaptive": _ARTICLE_HTML})

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.settings.CAMOUFOX_ENABLED", False),
    ):
        result = await WebReader().read(_URL, heavy_mode=True)

    # then
    assert result["mode"] == "5-crawlee_adaptive"
    stubs["4b-camoufox"].get_html.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_explicit_tier_starts_at_patchright() -> None:
    # when
    selected = await WebReader()._select_strategies(_URL, heavy_mode=False, tier="4a-patchright")

    # then
    assert list(selected) == [
        "4a-patchright",
        "4b-camoufox",
        "5-crawlee_adaptive",
        "6-novnc",
    ]


@pytest.mark.asyncio
async def test_explicit_tier_starts_at_camoufox() -> None:    # when
    selected = await WebReader()._select_strategies(_URL, heavy_mode=False, tier="4b-camoufox")

    # then
    assert list(selected) == ["4b-camoufox", "5-crawlee_adaptive", "6-novnc"]


def test_tier_order_lists_the_patched_tiers_between_playwright_and_crawlee() -> None:
    # when / then
    assert list(TIER_ORDER) == [
        "1-beautifulsoup",
        "2-trafilatura",
        "4-playwright_stealth",
        "4a-patchright",
        "4b-camoufox",
        "5-crawlee_adaptive",
        "6-novnc",
    ]


@pytest.mark.asyncio
async def test_stored_session_starts_at_the_browser_tiers() -> None:
    # when
    with (
        patch(
            "src.reader.web_reader.cookie_manager.get_storage_state",
            new=AsyncMock(return_value={"cookies": [{"name": "li_at", "value": "x"}], "origins": []}),
        ),
    ):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False)

    # then
    assert next(iter(selected)) == "4-playwright_stealth"


@pytest.mark.asyncio
async def test_remembered_tier_is_the_start_point() -> None:
    # when
    with patch(
        "src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value="5-crawlee_adaptive")
    ):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False)

    # then
    assert list(selected) == ["5-crawlee_adaptive", "6-novnc"]


@pytest.mark.asyncio
async def test_caller_tier_outranks_memory() -> None:
    # when
    with patch(
        "src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value="5-crawlee_adaptive")
    ):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False, tier="1-beautifulsoup")

    # then
    assert next(iter(selected)) == "1-beautifulsoup"
    assert "5-crawlee_adaptive" in selected


@pytest.mark.asyncio
async def test_stored_session_outranks_memory() -> None:
    # when
    with (
        patch(
            "src.reader.web_reader.tier_memory.get",
            new=AsyncMock(return_value="2-trafilatura"),
        ),
        patch(
            "src.reader.web_reader.cookie_manager.get_storage_state",
            new=AsyncMock(return_value={"cookies": [{"name": "li_at", "value": "x"}], "origins": []}),
        ),
    ):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False)

    # then
    assert next(iter(selected)) == "4-playwright_stealth"


@pytest.mark.asyncio
async def test_unknown_remembered_tier_falls_back_to_the_full_ladder() -> None:
    # when
    with patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value="9-telepathy")):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False)

    # then
    assert next(iter(selected)) == "1-beautifulsoup"
    assert "9-telepathy" not in selected


@pytest.mark.asyncio
async def test_successful_read_records_its_tier() -> None:
    # given
    stubs = _stub_strategies({"4b-camoufox": _ARTICLE_HTML})

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.tier_memory.record", new=AsyncMock()) as mock_record,
    ):
        result = await WebReader().read(_URL)

    # then
    assert result["mode"] == "4b-camoufox"
    mock_record.assert_awaited_once_with(_URL, "4b-camoufox")


@pytest.mark.asyncio
async def test_unsafe_uri_from_tier_propagates_from_read() -> None:
    # when / then
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=UnsafeUriError("URI resolves to a non-public address")),
    ):
        with pytest.raises(UnsafeUriError):
            await WebReader().read(_URL)


@pytest.mark.asyncio
async def test_unsafe_uri_from_tier_propagates_from_read_with_links() -> None:
    # when / then
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=UnsafeUriError("URI resolves to a non-public address")),
    ):
        with pytest.raises(UnsafeUriError):
            await WebReader().read_with_links(_URL)
