from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import ChallengeDetectedException, HumanInterventionRequiredException
from src.reader.cloudflare.cookie_manager import (
    PRODUCED_BY_LOGIN_SEED,
    PRODUCED_BY_NOVNC,
    PRODUCED_BY_UNKNOWN,
)
from src.reader.web_reader import WebReader

_ARTICLE_HTML = (
    "<html><head><title>Article</title></head>"
    "<body><article><p>"
    "This is a genuine paragraph of article content with more than ten words in it. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    "</p></article></body></html>"
)

_WALL_HTML = "<html><body><div id='cf-challenge-running'></div></body></html>"

_LOGIN_WALL_HTML = (
    "<html><body>"
    "<div id='cf-challenge-running'></div>"
    "<p>" + " ".join(["outside"] * 39) + "</p>"
    "<form><p>" + " ".join(["inside"] * 61) + "</p>"
    "<input name='captcha'><input type='password' name='pw'></form>"
    "</body></html>"
)


def _challenge(intervention_type: str) -> ChallengeDetectedException:
    """A ChallengeDetectedException carrying a real scored verdict, so the
    reader's fall-through and escalation paths are exercised, not the
    constructor."""
    from src.reader.cloudflare.challenge_signals import as_login_verdict, assess

    html = _LOGIN_WALL_HTML if intervention_type == "login" else _WALL_HTML
    verdict = assess(200, html)
    assert verdict.wall is True
    if intervention_type == "login":
        verdict = as_login_verdict(verdict)
    assert verdict.intervention_type == intervention_type

    return ChallengeDetectedException(verdict)


@pytest.mark.asyncio
async def test_execute_strategy_logs_verdict_on_challenge(caplog: pytest.LogCaptureFixture) -> None:
    """The read path logs the scored verdict when the second look trips."""
    # given
    import logging

    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(return_value=_WALL_HTML)

    # when
    with caplog.at_level(logging.INFO):
        result = await reader._execute_strategy("1-beautifulsoup", strategy, "http://test.com")

    # then
    assert result is None
    assert any(
        "Challenge verdict:" in record.getMessage()
        and "vendor=cloudflare" in record.getMessage()
        and "type=captcha" in record.getMessage()
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_execute_html_strategy_logs_verdict_on_challenge(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The read_with_links path logs the scored verdict when the second look trips."""
    # given
    import logging

    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(return_value=_WALL_HTML)

    # when
    with caplog.at_level(logging.INFO):
        result = await reader._execute_html_strategy("1-beautifulsoup", strategy, "http://test.com")

    # then
    assert result == ""
    assert any(
        "Challenge verdict:" in record.getMessage() and "vendor=cloudflare" in record.getMessage()
        for record in caplog.records
    )


@pytest.fixture(autouse=True)
def _default_no_stored_session() -> Any:
    """Keep read() tests hermetic: no stored session unless a test overrides it."""
    with patch(
        "src.reader.web_reader.cookie_manager.get_storage_state",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.mark.asyncio
async def test_read_succeeds_on_first_strategy() -> None:
    # when
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com")

    # then
    assert result["status"] == "success"
    assert result["mode"] == "1-beautifulsoup"


@pytest.mark.asyncio
async def test_read_all_strategies_fail_returns_failure_response() -> None:
    # when
    with patch(
        "src.reader.web_reader.WebReader._execute_strategy",
        new=AsyncMock(return_value=None),
    ):
        result = await WebReader().read("http://fail.com")

    # then
    assert result["status"] == "error"
    assert result["reason"] == "all_tiers_failed"


@pytest.mark.asyncio
async def test_read_preempts_to_novnc_on_login_redirect_url() -> None:
    # when
    with (
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com?login=1")

    # then
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_heavy_mode_skips_lightweight() -> None:
    # when
    with (
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com", heavy_mode=True)

    # then
    assert result["mode"] == "4-playwright_stealth"


@pytest.mark.asyncio
async def test_read_routes_browser_first_when_stored_session_exists() -> None:
    """A stored session (e.g. a captured cf_clearance) forces the browser tier first
    even without heavy_mode, so a curl tier can't trip the challenge and bypass the
    Playwright tier that replays the clearance with its matching user-agent."""
    # when
    with (
        patch(
            "src.reader.web_reader.cookie_manager.get_storage_state",
            new=AsyncMock(return_value={"cookies": [{"name": "cf_clearance", "value": "x"}], "origins": []}),
        ),
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value="curl tier content that must be skipped"),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com")

    # then
    assert result["mode"] == "4-playwright_stealth"


@pytest.mark.parametrize(
    "producer",
    [PRODUCED_BY_NOVNC, PRODUCED_BY_LOGIN_SEED, PRODUCED_BY_UNKNOWN],
    ids=["novnc", "login-seed", "unknown-or-legacy-record"],
)
@pytest.mark.asyncio
async def test_read_routes_browser_first_for_stored_session_producers(
    producer: Any,
) -> None:
    """A stored session starts at the browser tiers, never at the cheap tiers:
    a clearance the browser itself earned (NoVNC, a login seed), or a stored
    session with no recorded producer at all (a pre-fix record, or a caller
    that omitted the field)."""
    # given
    beautifulsoup_mock = AsyncMock(return_value="cheap tiers must not run when a session is stored")

    # when
    with (
        patch(
            "src.reader.web_reader.cookie_manager.get_storage_state",
            new=AsyncMock(return_value={"cookies": [{"name": "li_at", "value": "x"}], "origins": []}),
        ),
        patch(
            "src.reader.web_reader.cookie_manager.get_stored_session_producer",
            new=AsyncMock(return_value=producer),
        ),
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=beautifulsoup_mock,
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com")

    # then
    assert result["mode"] == "4-playwright_stealth"
    beautifulsoup_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_read_heavy_mode_skips_producer_lookup_and_goes_browser_first() -> None:
    """heavy_mode is an explicit caller preference and takes priority: straight
    to the browser tiers, with no producer lookup at all."""
    # given
    producer_mock = AsyncMock(return_value=PRODUCED_BY_NOVNC)

    # when
    with (
        patch(
            "src.reader.web_reader.cookie_manager.get_storage_state",
            new=AsyncMock(return_value={"cookies": [{"name": "cf_clearance", "value": "x"}], "origins": []}),
        ),
        patch(
            "src.reader.web_reader.cookie_manager.get_stored_session_producer",
            new=producer_mock,
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com", heavy_mode=True)

    # then
    assert result["mode"] == "4-playwright_stealth"
    producer_mock.assert_not_awaited()


@pytest.mark.asyncio
async def test_prefer_browser_does_not_treat_a_freshly_saved_empty_cookie_jar_as_a_stored_session() -> None:
    """A NoVNC captcha flow saves whatever cookies the page holds once it is
    accepted, which can be none at all (see NoVNCStrategy's monitor). A login
    flow, which establish() opens, saves only after a real login, so it never
    writes such a record. The tier chooser must not read a zero-cookie record
    as grounds to force the browser tier: it buys no auth benefit and costs
    exactly what tiering exists to avoid.
    Exercises the real CookieManager, not the module's default mock, so the
    fix is proven where it lives (the read side), not merely asserted."""
    # given
    from src.reader.cloudflare.cookie_manager import CookieManager

    CookieManager._instance = None
    fresh_cookie_manager = CookieManager()
    fresh_cookie_manager._memory_store = {}
    fresh_cookie_manager.redis_client = None
    await fresh_cookie_manager.save_storage_state(
        "https://empty-jar.example.com", {"cookies": [], "origins": []}, "UA"
    )

    # when
    with patch(
        "src.reader.web_reader.cookie_manager.get_storage_state",
        new=fresh_cookie_manager.get_storage_state,
    ):
        prefer = await WebReader()._prefer_browser(
            "https://empty-jar.example.com", heavy_mode=False, profile=None
        )

    # then
    assert prefer is False


@pytest.mark.asyncio
async def test_read_propagates_human_intervention() -> None:
    # given
    exc = HumanInterventionRequiredException("http://vnc", "captcha")

    # when / then
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=exc),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await WebReader().read("http://test.com")


@pytest.mark.asyncio
async def test_read_falls_through_to_novnc_when_challenge_unsolved() -> None:
    """A curl-tier challenge no longer short-circuits to NoVNC; it falls through the
    ladder so the auto-solving tiers get a chance. When none resolve it, NoVNC (the
    last tier) handles it."""
    # when
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(side_effect=_challenge("captcha")),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.PatchrightStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.camoufox_strategy.CamoufoxStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.CrawleeStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch(
            "src.validator.content_validator.ContentValidator.validate",
            side_effect=lambda c: bool(c and c.strip()),
        ),
    ):
        result = await WebReader().read("http://test.com")

    # then
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_returns_failure_when_all_tiers_including_novnc_fail() -> None:
    """Every tier falls through on its challenge (NoVNC included); read ends in a
    failure response rather than looping."""
    # when
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(side_effect=_challenge("login")),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(side_effect=_challenge("captcha")),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.PatchrightStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.camoufox_strategy.CamoufoxStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.CrawleeStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
    ):
        result = await WebReader().read("http://test.com")

    # then
    assert result["status"] == "error"
    assert result["reason"] == "all_tiers_failed"


@pytest.mark.asyncio
async def test_read_with_links_success() -> None:
    # given
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job One</a></body></html>"
    )

    # when
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(return_value=raw_html),
    ):
        result = await WebReader().read_with_links("http://test.com")

    # then
    assert result["status"] == "success"
    assert result["links"][1] == "https://example.com/job1"


@pytest.mark.asyncio
async def test_read_with_links_filter_keeps_matching_only() -> None:
    # given
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit. "
        "<a href='https://example.com/job-offer/senior'>Senior</a>"
        "<a href='https://example.com/about'>About</a>"
        "</body></html>"
    )

    # when
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(return_value=raw_html),
    ):
        result = await WebReader().read_with_links("http://test.com", link_filter="/job-offer/")

    # then
    assert len(result["links"]) == 1
    assert result["links"][1] == "https://example.com/job-offer/senior"


@pytest.mark.asyncio
async def test_read_with_links_falls_through_when_first_returns_empty() -> None:
    # given
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job</a></body></html>"
    )

    # when
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=raw_html),
        ),
    ):
        result = await WebReader().read_with_links("http://test.com")

    # then
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_read_with_links_preempts_to_novnc_on_login_redirect_url() -> None:
    # given
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job</a></body></html>"
    )

    # when
    with patch(
        "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
        new=AsyncMock(return_value=raw_html),
    ):
        result = await WebReader().read_with_links("http://test.com?login=1")

    # then
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_read_with_links_propagates_human_intervention() -> None:
    # given
    exc = HumanInterventionRequiredException("http://vnc", "captcha")

    # when / then
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=exc),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await WebReader().read_with_links("http://test.com")


@pytest.mark.asyncio
async def test_read_with_links_all_strategies_fail() -> None:
    # when
    with patch(
        "src.reader.web_reader.WebReader._execute_html_strategy",
        new=AsyncMock(return_value=""),
    ):
        result = await WebReader().read_with_links("http://test.com")

    # then
    assert result["status"] == "error"
    assert result["reason"] == "all_tiers_failed"


@pytest.mark.asyncio
async def test_read_with_links_falls_through_to_novnc_on_challenge() -> None:
    # given
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job</a></body></html>"
    )

    # when
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(side_effect=_challenge("login")),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.PatchrightStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.camoufox_strategy.CamoufoxStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.CrawleeStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=raw_html),
        ),
    ):
        result = await WebReader().read_with_links("http://test.com")

    # then
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_execute_strategy_returns_none_on_exception() -> None:
    # given
    reader = WebReader()
    fail_strategy = MagicMock()
    fail_strategy.get_html = AsyncMock(side_effect=RuntimeError("boom"))

    # when
    result = await reader._execute_strategy("dummy", fail_strategy, "http://test.com")

    # then
    assert result is None


@pytest.mark.asyncio
async def test_execute_strategy_returns_none_on_validation_fail() -> None:
    # given
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(return_value=_ARTICLE_HTML)

    # when
    with patch("src.validator.content_validator.ContentValidator.validate", return_value=False):
        result = await reader._execute_strategy("dummy", strategy, "http://test.com")

    # then
    assert result is None


@pytest.mark.asyncio
async def test_execute_html_strategy_returns_empty_on_exception() -> None:
    # given
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(side_effect=RuntimeError("boom"))

    # when
    result = await reader._execute_html_strategy("dummy", strategy, "http://test.com")

    # then
    assert result == ""


@pytest.mark.asyncio
async def test_execute_html_strategy_returns_empty_string_when_html_blank() -> None:
    # given
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(return_value="")

    # when
    result = await reader._execute_html_strategy("dummy", strategy, "http://test.com")

    # then
    assert result == ""


@pytest.mark.asyncio
async def test_read_bails_when_budget_exceeded() -> None:
    """READ_TOTAL_BUDGET shortcut path: NoVNC rescue also fails, so reason stays budget_exhausted."""
    # given
    reader = WebReader()

    # when
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
    ):
        result = await reader.read("http://test.com")

    # then
    assert result["status"] == "error"
    assert result["reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_read_bails_but_novnc_rescue_succeeds() -> None:
    """READ_TOTAL_BUDGET shortcut path: NoVNC is exempt from the budget check
    and, when it returns usable content, its result is the successful read."""
    # given
    reader = WebReader()

    # when
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await reader.read("http://test.com")

    # then
    assert result["status"] == "success"
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_with_links_bails_when_budget_exceeded() -> None:
    # given
    reader = WebReader()

    # when
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
    ):
        result = await reader.read_with_links("http://test.com")

    # then
    assert result["status"] == "error"
    assert result["reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_read_with_links_bails_but_novnc_rescue_succeeds() -> None:
    """NoVNC is exempt from the budget check on the links path too: when it
    returns usable content, its result is the successful read."""
    # given
    reader = WebReader()
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job One</a></body></html>"
    )

    # when
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=raw_html),
        ),
    ):
        result = await reader.read_with_links("http://test.com")

    # then
    assert result["status"] == "success"
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_with_links_bails_and_novnc_rescue_fails_validation() -> None:
    """NoVNC's rescue HTML can clear the interstitial gate yet still fail the
    annotated-content validator; that must end in a failure response, not a
    false success."""
    # given
    reader = WebReader()
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job One</a></body></html>"
    )

    # when
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=raw_html),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=False),
    ):
        result = await reader.read_with_links("http://test.com")

    # then
    assert result["status"] == "error"
    assert result["reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_failure_response_reports_all_tiers_failed_when_strategies_run_but_all_fail() -> None:
    # when
    with patch(
        "src.reader.web_reader.WebReader._execute_strategy",
        new=AsyncMock(return_value=None),
    ):
        result = await WebReader().read("http://test.com")

    # then
    assert result["reason"] == "all_tiers_failed"


@pytest.mark.asyncio
async def test_read_falls_through_when_validation_fails_then_succeeds() -> None:
    """Validation-fail on tier 1 should not stop the chain."""
    # when
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch(
            "src.validator.content_validator.ContentValidator.validate",
            side_effect=[False, True],
        ),
    ):
        result = await WebReader().read("http://test.com")

    # then
    assert result["mode"] == "2-trafilatura"


@pytest.mark.asyncio
async def test_read_with_links_validation_fail_then_next_tier_succeeds() -> None:
    # given
    short_html = "<html><body>short</body></html>"
    long_html = (
        "<html><body>This is long enough filler content to pass the validator. "
        "<a href='https://example.com/x'>Link</a></body></html>"
    )

    # when
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value=short_html),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=long_html),
        ),
    ):
        result = await WebReader().read_with_links("http://test.com")

    # then
    assert result["status"] == "success"
    assert result["mode"] == "2-trafilatura"


@pytest.mark.asyncio
async def test_read_with_links_falls_through_when_annotated_content_fails_validation() -> None:
    """Raw HTML that clears the interstitial gate (real, article-shaped content)
    can still fail ContentValidator on the annotated text; that must fall
    through to the next tier rather than stopping the chain."""
    # given
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job One</a></body></html>"
    )

    # when
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value=raw_html),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=raw_html),
        ),
        patch(
            "src.validator.content_validator.ContentValidator.validate",
            side_effect=[False, True],
        ),
    ):
        result = await WebReader().read_with_links("http://test.com")

    # then
    assert result["status"] == "success"
    assert result["mode"] == "2-trafilatura"


@pytest.mark.asyncio
async def test_load_user_agents_falls_back_when_path_missing() -> None:
    # given
    reader = WebReader()

    # when
    with patch("src.reader.web_reader.Path.exists", return_value=False):
        agents = reader._load_user_agents()

    # then
    assert isinstance(agents, list)
    assert len(agents) >= 1


@pytest.mark.asyncio
async def test_read_json_file_returns_fallback_on_bad_json(tmp_path: Any) -> None:
    # given
    reader = WebReader()
    bad = tmp_path / "broken.json"
    bad.write_text("not json", encoding="utf-8")

    # when
    agents = reader._read_json_file(bad)

    # then
    assert isinstance(agents, list)


def test_get_random_user_agent_returns_string() -> None:
    # when
    reader = WebReader()

    # then
    assert isinstance(reader._get_random_user_agent(), str)


@pytest.mark.asyncio
async def test_execute_html_strategy_falls_through_on_challenge() -> None:
    """A challenge on the get_html path yields '' so the ladder advances to the next tier."""
    # given
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(side_effect=_challenge("login"))

    # when
    result = await reader._execute_html_strategy("1-beautifulsoup", strategy, "http://test.com")

    # then
    assert result == ""


@pytest.mark.asyncio
async def test_execute_strategy_falls_through_on_challenge() -> None:
    """A challenge on the get_html path yields None so the ladder advances to the next tier."""
    # given
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(side_effect=_challenge("captcha"))

    # when
    result = await reader._execute_strategy("1-beautifulsoup", strategy, "http://test.com")

    # then
    assert result is None


@pytest.mark.asyncio
async def test_execute_strategy_rejects_interstitial_before_validating() -> None:
    """A tier that returns a small page with no article-shaped content (an
    interstitial that clears ContentValidator's shallow checks) must be
    rejected before ever reaching content validation, not reported as success."""
    # given
    reader = WebReader()
    strategy = MagicMock()
    interstitial_html = "<html><body><p>Continue shopping</p></body></html>"
    strategy.get_html = AsyncMock(return_value=interstitial_html)

    # when
    with patch("src.validator.content_validator.ContentValidator.validate", return_value=True):
        result = await reader._execute_strategy("1-beautifulsoup", strategy, "http://test.com")

    # then
    assert result is None


@pytest.mark.asyncio
async def test_execute_html_strategy_rejects_interstitial_before_returning() -> None:
    """The links path must reject a tier's raw HTML when the article extractor
    finds nothing, even though annotate_links would otherwise accept it."""
    # given
    reader = WebReader()
    strategy = MagicMock()
    interstitial_html = "<html><body><p>Continue shopping</p></body></html>"
    strategy.get_html = AsyncMock(return_value=interstitial_html)

    # when
    result = await reader._execute_html_strategy("1-beautifulsoup", strategy, "http://test.com")

    # then
    assert result == ""


@pytest.mark.asyncio
async def test_read_rejects_amazon_style_interstitial_and_escalates() -> None:
    """End-to-end regression test for the reported bug: a 200 response whose
    entire body is Amazon's own captcha interstitial must not be reported as a
    successful scrape. This is a trimmed faithful copy of the real page fetched
    from amazon.pl on 2026-09-04: it carries no phrase from the dictionary, and
    its footer boilerplate (terms/privacy links, copyright line) alone clears
    has_real_content's word count, so only the locale-independent structural
    marker (the fixed internal form action Amazon uses for this page) catches
    it. A fixture built from a dictionary phrase would pass for the wrong
    reason and miss a regression in the structural check."""
    # given
    interstitial_html = (
        "<html lang='pl'><head><title>Amazon.pl</title></head><body>"
        "<div class='a-box a-alert a-alert-info'>"
        "<h4>Kliknij poniższy przycisk, aby kontynuować zakupy</h4></div>"
        "<form method='get' action='/errors_page/validateCaptcha' name=''>"
        "<button type='submit'>Kontynuuj zakupy</button>"
        "<button type='submit'>Kontynuuj zakupy</button>"
        "</form>"
        "<a href='/gp/help/customer/display.html?nodeId=508088'>Warunki użytkowania i sprzedaży</a>"
        "<a href='/gp/help/customer/display.html?nodeId=468496'>Zasady ochrony prywatności</a>"
        "<div>© 1996-2025 Amazon.com, Inc. lub podmioty stowarzyszone</div>"
        "</body></html>"
    )

    # when / then
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value=interstitial_html),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.patchright_strategy.PatchrightStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.camoufox_strategy.CamoufoxStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.CrawleeStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(side_effect=HumanInterventionRequiredException("http://vnc", "captcha")),
        ),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await WebReader().read("https://www.amazon.pl/dp/B09D14YFR9")


class _SecondLookStub:
    def __init__(self, html: str) -> None:
        self._html = html

    async def extract(self, _url: str) -> str:
        return self._html

    async def get_html(self, _url: str) -> str:
        return self._html

    async def screenshot_page(self, _url: str) -> tuple[str, bytes]:
        return self._html, b"\x89PNG"


def _reader_verdicts(outcome: str) -> float:
    from prometheus_client import REGISTRY

    return (
        REGISTRY.get_sample_value("challenge_verdicts_total", {"verdict": outcome, "tier": "reader"}) or 0.0
    )


def _sample_total(sample_name: str) -> float:
    from prometheus_client import REGISTRY

    return sum(
        sample.value
        for family in REGISTRY.collect()
        for sample in family.samples
        if sample.name == sample_name
    )


async def _read_text(reader: WebReader) -> dict[str, Any]:
    return await reader.read("http://test.com", tier="1-beautifulsoup")


async def _read_screenshot(reader: WebReader) -> dict[str, Any]:
    return await reader.read("http://test.com", output_format="screenshot", tier="4-playwright_stealth")


async def _read_links(reader: WebReader) -> dict[str, Any]:
    return await reader.read_with_links("http://test.com", tier="1-beautifulsoup")


_SECOND_LOOK_READS: list[Any] = [
    pytest.param(_read_text, id="read"),
    pytest.param(_read_screenshot, id="screenshot"),
    pytest.param(_read_links, id="read_with_links"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("read", _SECOND_LOOK_READS)
@pytest.mark.parametrize(
    ("html", "outcome"),
    [pytest.param(_WALL_HTML, "wall", id="wall"), pytest.param(_ARTICLE_HTML, "content", id="content")],
)
async def test_the_second_look_counts_one_verdict_one_score_and_one_signal_set_under_reader(
    read: Any, html: str, outcome: str
) -> None:
    # given
    from src.reader.cloudflare.challenge_signals import assess

    reader = WebReader()
    stub = _SecondLookStub(html)
    signals_per_check = len(assess(200, html, record_metrics=False).signals)
    outcome_before = _reader_verdicts(outcome)
    verdicts_before = _sample_total("challenge_verdicts_total")
    scores_before = _sample_total("challenge_score_count")
    signals_before = _sample_total("challenge_signals_fired_total")

    # when
    with patch.object(
        reader, "_select_strategies", new=AsyncMock(return_value={"4-playwright_stealth": stub})
    ):
        await read(reader)

    # then
    assert _reader_verdicts(outcome) == outcome_before + 1.0
    assert _sample_total("challenge_verdicts_total") == verdicts_before + 1.0
    assert _sample_total("challenge_score_count") == scores_before + 1.0
    assert _sample_total("challenge_signals_fired_total") == signals_before + signals_per_check


_USER_INFO_READ_URL = "https://reader:hunter2@test.com/page?X-Amz-Signature=secret"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "outcome",
    [
        AsyncMock(return_value=_WALL_HTML),
        AsyncMock(side_effect=RuntimeError(f"tier broke at {_USER_INFO_READ_URL}")),
    ],
    ids=["challenge", "failure"],
)
async def test_tier_log_lines_name_the_read_without_its_user_info(
    caplog: pytest.LogCaptureFixture, outcome: AsyncMock
) -> None:
    # given
    import logging

    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = outcome

    # when
    with caplog.at_level(logging.DEBUG):
        await reader._execute_strategy("1-beautifulsoup", strategy, _USER_INFO_READ_URL)
        await reader._execute_html_strategy("1-beautifulsoup", strategy, _USER_INFO_READ_URL)

    # then
    assert "https://test.com/page" in caplog.text
    assert "hunter2" not in caplog.text
    assert "X-Amz-Signature" not in caplog.text


@pytest.mark.asyncio
async def test_a_failed_tier_logs_the_reason_without_the_query(caplog: pytest.LogCaptureFixture) -> None:
    # given
    import logging

    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(
        side_effect=RuntimeError(f"net::ERR_CONNECTION_REFUSED at {_USER_INFO_READ_URL}")
    )

    # when
    with caplog.at_level(logging.WARNING):
        await reader._execute_strategy("1-beautifulsoup", strategy, _USER_INFO_READ_URL)
        await reader._execute_html_strategy("1-beautifulsoup", strategy, _USER_INFO_READ_URL)

    # then
    reason = "net::ERR_CONNECTION_REFUSED at https://test.com/page"
    assert f"Strategy 1-beautifulsoup failed for https://test.com/page: {reason}" in caplog.text
    assert f"Strategy 1-beautifulsoup get_html failed for https://test.com/page: {reason}" in caplog.text
    assert "hunter2" not in caplog.text
    assert "X-Amz-Signature" not in caplog.text


@pytest.mark.asyncio
async def test_a_read_logs_its_address_without_user_info(caplog: pytest.LogCaptureFixture) -> None:
    # given
    import logging

    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(return_value=_ARTICLE_HTML)

    # when
    with (
        caplog.at_level(logging.DEBUG),
        patch.object(reader, "_build_strategies", return_value={"1-beautifulsoup": strategy}),
        patch("src.reader.web_reader.route_document", new=AsyncMock(return_value=None)),
    ):
        await reader.read(_USER_INFO_READ_URL)
        await reader.read(_USER_INFO_READ_URL)
        await reader.read_with_links(_USER_INFO_READ_URL)
        await reader.read_with_links(_USER_INFO_READ_URL)

    # then
    assert "Reading URL: https://test.com/page" in caplog.text
    assert "Reading URL with links: https://test.com/page" in caplog.text
    assert "cache hit for https://test.com/page" in caplog.text
    assert "cache hit (with links) for https://test.com/page" in caplog.text
    assert "hunter2" not in caplog.text
    assert "X-Amz-Signature" not in caplog.text


@pytest.mark.asyncio
async def test_a_login_redirect_read_logs_its_address_without_user_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    import logging

    reader = WebReader()

    # when
    with caplog.at_level(logging.WARNING):
        await reader._select_strategies("https://reader:hunter2@test.com/?login=1", heavy_mode=False)

    # then
    assert "Pre-emptive URL redirect login detected on https://test.com/." in caplog.text
    assert "login=1" not in caplog.text
    assert "hunter2" not in caplog.text
