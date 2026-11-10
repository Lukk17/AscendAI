"""The patched browser tiers sit between Playwright and Crawlee (task 2.3)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError

from src.api.exceptions import (
    ChallengeDetectedException,
    ExtractionFailedError,
    ExtractionNotConfiguredError,
    HumanInterventionRequiredException,
)
from src.reader.cloudflare.challenge_signals import ChallengeVerdict
from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.web_reader import TIER_ORDER, OutputFormat, TierName, WebReader

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


def _raising_strategy(error: Exception) -> BaseStrategy:
    """A tier whose get_html raises *error*."""
    stub = MagicMock()
    stub.get_html = AsyncMock(side_effect=error)

    return stub


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
async def test_explicit_tier_starts_at_camoufox() -> None:  # when
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
    with patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value="5-crawlee_adaptive")):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False)

    # then
    assert list(selected) == ["5-crawlee_adaptive", "6-novnc"]


@pytest.mark.asyncio
async def test_caller_tier_outranks_memory() -> None:
    # when
    with patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value="5-crawlee_adaptive")):
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


@pytest.mark.asyncio
async def test_crawlee_refusal_never_opens_the_novnc_window() -> None:
    """A crawlee read the guard refused answers unsafe_uri and stops the ladder."""
    # given
    stubs = _stub_strategies({"6-novnc": _ARTICLE_HTML})
    stubs["5-crawlee_adaptive"] = _raising_strategy(
        UnsafeUriError("browser request refused: http://169.254.169.254/")
    )

    # when / then
    with patch.object(WebReader, "_build_strategies", return_value=stubs):
        with pytest.raises(UnsafeUriError):
            await WebReader().read(_URL, tier="5-crawlee_adaptive")

    stubs["6-novnc"].get_html.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_extraction_failed_from_tier_propagates_from_read_with_links() -> None:
    """A tier that could not read the page is fatal on the read-with-links path too."""
    # given
    stubs = _stub_strategies({"6-novnc": _ARTICLE_HTML})
    stubs["5-crawlee_adaptive"] = _raising_strategy(
        ExtractionFailedError("CrawleeStrategy: the crawl handled no request for the page")
    )

    # when / then
    with patch.object(WebReader, "_build_strategies", return_value=stubs):
        with pytest.raises(ExtractionFailedError):
            await WebReader().read_with_links(_URL, tier="5-crawlee_adaptive")


@pytest.mark.asyncio
async def test_extraction_not_configured_from_a_tier_stays_fatal_on_the_ladder() -> None:
    """A schema request with no model configured is a caller error, not a tier to skip."""
    # given
    stubs = _stub_strategies({"6-novnc": _ARTICLE_HTML})
    stubs["5-crawlee_adaptive"] = _raising_strategy(
        ExtractionNotConfiguredError("schema extraction needs EXTRACTION_LLM_BASE_URL")
    )

    # when / then
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.tier_memory.record", new=AsyncMock()),
    ):
        with pytest.raises(ExtractionNotConfiguredError):
            await WebReader().read_with_links(_URL)


@pytest.mark.asyncio
async def test_extraction_failed_from_a_tier_falls_through_to_the_next_on_the_ladder() -> None:
    """An unpinned ladder read keeps climbing after a tier that could not fetch the page."""
    # given
    stubs = _stub_strategies({"6-novnc": _ARTICLE_HTML})
    stubs["5-crawlee_adaptive"] = _raising_strategy(
        ExtractionFailedError("CrawleeStrategy: the crawl handled no request for the page")
    )

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.tier_memory.record", new=AsyncMock()),
    ):
        result = await WebReader().read(_URL)

    # then
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_extraction_failed_from_a_tier_falls_through_on_read_with_links() -> None:
    """The read-with-links ladder keeps climbing after a tier that could not fetch the page."""
    # given
    stubs = _stub_strategies({"6-novnc": _ARTICLE_HTML})
    stubs["5-crawlee_adaptive"] = _raising_strategy(
        ExtractionFailedError("CrawleeStrategy: the crawl handled no request for the page")
    )

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.tier_memory.record", new=AsyncMock()),
    ):
        result = await WebReader().read_with_links(_URL)

    # then
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["read", "read_with_links"])
@pytest.mark.parametrize(
    "flags",
    [
        pytest.param({"tier": "4b-camoufox"}, id="explicit-tier"),
        pytest.param({"heavy_mode": True}, id="heavy-mode"),
    ],
)
async def test_pinned_read_leaves_tier_memory_alone(method: str, flags: dict[str, object]) -> None:
    # given
    stubs = _stub_strategies({"4b-camoufox": _ARTICLE_HTML})

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.tier_memory.record", new=AsyncMock()) as mock_record,
    ):
        result = await getattr(WebReader(), method)(_URL, **flags)

    # then
    assert result["mode"] == "4b-camoufox"
    mock_record.assert_not_awaited()


@pytest.mark.asyncio
async def test_successful_read_with_links_records_its_tier() -> None:
    # given
    stubs = _stub_strategies({"4b-camoufox": _ARTICLE_HTML})

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.tier_memory.record", new=AsyncMock()) as mock_record,
    ):
        result = await WebReader().read_with_links(_URL)

    # then
    assert result["mode"] == "4b-camoufox"
    mock_record.assert_awaited_once_with(_URL, "4b-camoufox")


@pytest.mark.asyncio
async def test_explicit_tier_skips_disabled_camoufox() -> None:
    # when
    with patch("src.reader.web_reader.settings.CAMOUFOX_ENABLED", False):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False, tier="4a-patchright")

    # then
    assert list(selected) == ["4a-patchright", "5-crawlee_adaptive", "6-novnc"]


@pytest.mark.asyncio
async def test_explicit_tier_read_never_runs_disabled_camoufox() -> None:
    # given
    stubs = _stub_strategies({"4b-camoufox": _ARTICLE_HTML, "5-crawlee_adaptive": _ARTICLE_HTML})

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.settings.CAMOUFOX_ENABLED", False),
    ):
        result = await WebReader().read(_URL, tier="4a-patchright")

    # then
    assert result["mode"] == "5-crawlee_adaptive"
    stubs["4b-camoufox"].get_html.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_read_with_links_without_the_human_tier_never_opens_novnc() -> None:
    # given
    stubs = _stub_strategies({"6-novnc": _ARTICLE_HTML})

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
    ):
        result = await WebReader().read_with_links(_URL, allow_human_tier=False)

    # then
    assert result["status"] == "error"
    assert result["reason"] == "all_tiers_failed"
    stubs["6-novnc"].get_html.assert_not_awaited()  # type: ignore[attr-defined]
    stubs["5-crawlee_adaptive"].get_html.assert_awaited_once()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_read_with_links_without_the_human_tier_skips_novnc_after_the_budget() -> None:
    # given
    stubs = _stub_strategies({"6-novnc": _ARTICLE_HTML})

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", -1),
    ):
        result = await WebReader().read_with_links(_URL, allow_human_tier=False)

    # then
    assert result["reason"] == "budget_exhausted"
    stubs["6-novnc"].get_html.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_login_redirect_url_without_the_human_tier_runs_no_tier() -> None:
    # when
    with patch(
        "src.reader.web_reader.ChallengeDetector.is_login_redirect_url",
        return_value=True,
    ):
        selected = await WebReader()._select_strategies(_URL, heavy_mode=False, allow_human_tier=False)

    # then
    assert selected == {}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("heavy_mode", "tier", "first"),
    [
        pytest.param(False, None, "1-beautifulsoup", id="remembered-human-tier"),
        pytest.param(False, "5-crawlee_adaptive", "5-crawlee_adaptive", id="explicit-tier"),
        pytest.param(True, None, "4-playwright_stealth", id="heavy-mode"),
    ],
)
async def test_selection_without_the_human_tier_drops_novnc(
    heavy_mode: bool, tier: TierName | None, first: str
) -> None:
    # when
    with patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value="6-novnc")):
        selected = await WebReader()._select_strategies(
            _URL, heavy_mode=heavy_mode, tier=tier, allow_human_tier=False
        )

    # then
    assert next(iter(selected)) == first
    assert "6-novnc" not in selected


@pytest.mark.asyncio
async def test_explicit_human_tier_without_the_human_tier_runs_no_tier() -> None:
    # when
    selected = await WebReader()._select_strategies(
        _URL, heavy_mode=False, tier="6-novnc", allow_human_tier=False
    )

    # then
    assert selected == {}


def _novnc_only_strategies() -> dict[str, BaseStrategy]:
    """Every rung but 6-novnc returns nothing, in HTML and in a screenshot."""
    strategies = _stub_strategies({"6-novnc": _ARTICLE_HTML})
    for name, stub in strategies.items():
        page = (_ARTICLE_HTML, b"\x89PNG") if name == "6-novnc" else None
        stub.screenshot_page = AsyncMock(return_value=page)  # type: ignore[attr-defined]

    return strategies


@pytest.mark.asyncio
@pytest.mark.parametrize("output_format", ["text", "structured", "schema", "tables", "screenshot"])
async def test_read_without_the_human_tier_never_opens_novnc(output_format: OutputFormat) -> None:
    # given
    stubs = _novnc_only_strategies()
    schema = {"type": "object"} if output_format == "schema" else None

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
    ):
        result = await WebReader().read(
            _URL,
            output_format=output_format,
            extraction_schema=schema,
            allow_human_tier=False,
        )

    # then
    assert result["status"] == "error"
    stubs["6-novnc"].get_html.assert_not_awaited()  # type: ignore[attr-defined]
    stubs["6-novnc"].screenshot_page.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_read_without_the_human_tier_skips_novnc_after_the_budget() -> None:
    # given
    stubs = _novnc_only_strategies()

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", -1),
    ):
        result = await WebReader().read(_URL, allow_human_tier=False)

    # then
    assert result["reason"] == "budget_exhausted"
    stubs["6-novnc"].get_html.assert_not_awaited()  # type: ignore[attr-defined]


def _login_landing_strategies() -> dict[str, BaseStrategy]:
    """The first rung lands on a login page through the landing rule, every other rung serves the article."""
    landing = ChallengeVerdict(
        score=20,
        threshold=100,
        signals=(),
        vendor=None,
        wall=False,
        has_content=True,
        intervention_type="login",
        login_landing=True,
    )
    strategies = _stub_strategies(dict.fromkeys(TIER_ORDER, _ARTICLE_HTML))
    strategies["1-beautifulsoup"] = _raising_strategy(ChallengeDetectedException(landing))
    strategies["6-novnc"].get_html = AsyncMock(  # type: ignore[method-assign]
        side_effect=HumanInterventionRequiredException("http://vnc:7900", "login")
    )

    return strategies


_MIDDLE_TIERS = (
    "2-trafilatura",
    "4-playwright_stealth",
    "4a-patchright",
    "4b-camoufox",
    "5-crawlee_adaptive",
)


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["read", "read_with_links"])
async def test_a_login_landing_goes_straight_to_the_human_tier(method: str) -> None:
    # given
    stubs = _login_landing_strategies()

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
        pytest.raises(HumanInterventionRequiredException) as raised,
    ):
        await getattr(WebReader(), method)(_URL)

    # then
    assert raised.value.intervention_type == "login"
    novnc_call = stubs["6-novnc"].get_html.await_args  # type: ignore[attr-defined]
    assert novnc_call.args[0] == _URL
    assert novnc_call.args[1].login_landing is True
    for name in _MIDDLE_TIERS:
        stubs[name].get_html.assert_not_awaited()  # type: ignore[attr-defined]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["read", "read_with_links"])
async def test_a_login_landing_without_the_human_tier_stops_the_ladder_with_the_login_answer(
    method: str,
) -> None:
    # given
    stubs = _login_landing_strategies()

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
    ):
        result = await getattr(WebReader(), method)(_URL, allow_human_tier=False)

    # then
    assert result["status"] == "error"
    assert result["reason"] == "login_required"
    stubs["6-novnc"].get_html.assert_not_awaited()  # type: ignore[attr-defined]
    for name in _MIDDLE_TIERS:
        stubs[name].get_html.assert_not_awaited()  # type: ignore[attr-defined]
