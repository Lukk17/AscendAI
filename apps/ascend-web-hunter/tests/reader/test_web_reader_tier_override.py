"""A caller can choose where the escalation chain starts.

Change close-web-search-scraping-follow-ups, tasks 3.1 to 3.3.
"""

from unittest.mock import AsyncMock, patch

import pytest

from src.reader.cloudflare.cookie_manager import PRODUCED_BY_FLARESOLVERR
from src.reader.web_reader import NOVNC_STRATEGY_NAME, WebReader, _cache_key

_URL = "https://example.com/article"
_ALL_TIERS = [
    "1-beautifulsoup",
    "2-trafilatura",
    "3-flaresolverr",
    "4-playwright_stealth",
    "5-crawlee_adaptive",
    NOVNC_STRATEGY_NAME,
]


@pytest.mark.asyncio
async def test_the_first_tier_selects_the_whole_chain():
    # when
    selected = await WebReader()._select_strategies(_URL, heavy_mode=False, tier="1-beautifulsoup")

    # then
    assert list(selected) == _ALL_TIERS


@pytest.mark.asyncio
async def test_a_middle_tier_keeps_every_tier_after_it():
    # when
    selected = await WebReader()._select_strategies(_URL, heavy_mode=False, tier="3-flaresolverr")

    # then
    assert list(selected) == _ALL_TIERS[2:]


@pytest.mark.asyncio
async def test_the_last_tier_selects_only_itself():
    # when
    selected = await WebReader()._select_strategies(_URL, heavy_mode=False, tier=NOVNC_STRATEGY_NAME)

    # then
    assert list(selected) == [NOVNC_STRATEGY_NAME]


@pytest.mark.asyncio
async def test_an_explicit_tier_outranks_heavy_mode():
    # when
    selected = await WebReader()._select_strategies(_URL, heavy_mode=True, tier="1-beautifulsoup")

    # then
    assert list(selected) == _ALL_TIERS


@pytest.mark.asyncio
async def test_an_explicit_tier_outranks_the_producer_routing():
    # when
    with patch(
        "src.reader.web_reader.cookie_manager.get_stored_session_producer",
        new=AsyncMock(return_value=PRODUCED_BY_FLARESOLVERR),
    ):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False, tier="4-playwright_stealth")

    # then
    assert list(selected) == _ALL_TIERS[3:]


@pytest.mark.asyncio
async def test_a_login_redirect_url_outranks_an_explicit_tier():
    # when
    with patch(
        "src.reader.web_reader.ChallengeDetector.is_login_redirect_url",
        return_value=True,
    ):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False, tier="1-beautifulsoup")

    # then
    assert list(selected) == [NOVNC_STRATEGY_NAME]


@pytest.mark.asyncio
async def test_no_tier_leaves_the_existing_routing_alone():
    # when
    with patch(
        "src.reader.web_reader.cookie_manager.get_storage_state",
        new=AsyncMock(return_value=None),
    ):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False)

    # then
    assert list(selected) == _ALL_TIERS


@pytest.mark.asyncio
async def test_the_read_runs_the_tier_it_was_asked_for():
    # given
    reader = WebReader()
    ran: list[str] = []

    async def _execute(name, strategy, url, **_kwargs):
        ran.append(name)

        return {"content": "the page", "status": "success", "mode": name}

    # when
    with (
        patch(
            "src.reader.web_reader.cookie_manager.has_auth_cookies",
            new=AsyncMock(return_value=False),
        ),
        patch.object(reader, "_execute_strategy", side_effect=_execute),
    ):
        result = await reader.read(_URL, tier="5-crawlee_adaptive")

    # then
    assert ran == ["5-crawlee_adaptive"]
    assert result["mode"] == "5-crawlee_adaptive"


def test_two_tiers_and_two_formats_make_four_cache_keys():
    # when
    keys = {
        _cache_key(_URL, False, False, None, output_format, tier)
        for output_format in ("text", "structured")
        for tier in ("1-beautifulsoup", "4-playwright_stealth")
    }

    # then
    assert len(keys) == 4


def test_an_unset_tier_keeps_its_own_cache_key():
    # when / then
    assert _cache_key(_URL, False, False, None, "text") != _cache_key(
        _URL, False, False, None, "text", "1-beautifulsoup"
    )
