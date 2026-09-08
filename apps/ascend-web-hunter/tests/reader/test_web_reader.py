from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import ChallengeDetectedException, HumanInterventionRequiredException
from src.reader.web_reader import WebReader

_ARTICLE_HTML = (
    "<html><head><title>Article</title></head>"
    "<body><article><p>"
    "This is a genuine paragraph of article content with more than ten words in it. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    "</p></article></body></html>"
)


@pytest.fixture(autouse=True)
def _default_no_stored_session():
    """Keep read() tests hermetic: no stored session unless a test overrides it."""
    with patch(
        "src.reader.web_reader.cookie_manager.get_storage_state",
        new=AsyncMock(return_value=None),
    ):
        yield


@pytest.mark.asyncio
async def test_read_succeeds_on_first_strategy():
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com")
    assert result["status"] == "success"
    assert result["mode"] == "1-beautifulsoup"


@pytest.mark.asyncio
async def test_read_all_strategies_fail_returns_failure_response():
    with patch(
        "src.reader.web_reader.WebReader._execute_strategy",
        new=AsyncMock(return_value=None),
    ):
        result = await WebReader().read("http://fail.com")
    assert result["status"] == "error"
    assert result["reason"] == "all_tiers_failed"


@pytest.mark.asyncio
async def test_read_preempts_to_novnc_on_login_redirect_url():
    with (
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com?login=1")
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_heavy_mode_skips_lightweight():
    with (
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com", heavy_mode=True)
    assert result["mode"] == "4-playwright_stealth"


@pytest.mark.asyncio
async def test_read_routes_browser_first_when_stored_session_exists():
    """A stored session (e.g. a captured cf_clearance) forces the browser tier first
    even without heavy_mode, so a curl tier can't trip the challenge and bypass the
    Playwright tier that replays the clearance with its matching user-agent."""
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
    assert result["mode"] == "4-playwright_stealth"


@pytest.mark.asyncio
async def test_prefer_browser_does_not_treat_a_freshly_saved_empty_cookie_jar_as_a_stored_session():
    """establish() legitimately writes a record with zero cookies for a page
    nobody was challenged on (see NoVNCStrategy's monitor). The tier chooser
    must not read that record as grounds to force the browser tier -- it
    buys no auth benefit and costs exactly what tiering exists to avoid.
    Exercises the real CookieManager, not the module's default mock, so the
    fix is proven where it lives (the read side), not merely asserted."""
    from src.reader.cloudflare.cookie_manager import CookieManager

    CookieManager._instance = None
    fresh_cookie_manager = CookieManager()
    fresh_cookie_manager._memory_store = {}
    fresh_cookie_manager.redis_client = None
    await fresh_cookie_manager.save_storage_state(
        "https://empty-jar.example.com", {"cookies": [], "origins": []}, "UA"
    )

    with patch(
        "src.reader.web_reader.cookie_manager.get_storage_state",
        new=fresh_cookie_manager.get_storage_state,
    ):
        prefer = await WebReader()._prefer_browser(
            "https://empty-jar.example.com", heavy_mode=False, profile=None
        )

    assert prefer is False


@pytest.mark.asyncio
async def test_read_propagates_human_intervention():
    exc = HumanInterventionRequiredException("http://vnc", "captcha")
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=exc),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await WebReader().read("http://test.com")


@pytest.mark.asyncio
async def test_read_falls_through_to_novnc_when_challenge_unsolved():
    """A curl-tier challenge no longer short-circuits to NoVNC; it falls through the
    ladder so the auto-solving tiers get a chance. When none resolve it, NoVNC (the
    last tier) handles it."""
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(side_effect=ChallengeDetectedException(intervention_type="captcha")),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.flaresolverr_strategy.FlareSolverrStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
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
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_returns_failure_when_all_tiers_including_novnc_fail():
    """Every tier falls through on its challenge (NoVNC included); read ends in a
    failure response rather than looping."""
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(side_effect=ChallengeDetectedException(intervention_type="login")),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(side_effect=ChallengeDetectedException(intervention_type="captcha")),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.flaresolverr_strategy.FlareSolverrStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.CrawleeStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
    ):
        result = await WebReader().read("http://test.com")
    assert result["status"] == "error"
    assert result["reason"] == "all_tiers_failed"


@pytest.mark.asyncio
async def test_read_with_links_success():
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job One</a></body></html>"
    )
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(return_value=raw_html),
    ):
        result = await WebReader().read_with_links("http://test.com")
    assert result["status"] == "success"
    assert result["links"][1] == "https://example.com/job1"


@pytest.mark.asyncio
async def test_read_with_links_filter_keeps_matching_only():
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit. "
        "<a href='https://example.com/job-offer/senior'>Senior</a>"
        "<a href='https://example.com/about'>About</a>"
        "</body></html>"
    )
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(return_value=raw_html),
    ):
        result = await WebReader().read_with_links("http://test.com", link_filter="/job-offer/")
    assert len(result["links"]) == 1
    assert result["links"][1] == "https://example.com/job-offer/senior"


@pytest.mark.asyncio
async def test_read_with_links_falls_through_when_first_returns_empty():
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job</a></body></html>"
    )
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
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_read_with_links_preempts_to_novnc_on_login_redirect_url():
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job</a></body></html>"
    )
    with patch(
        "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
        new=AsyncMock(return_value=raw_html),
    ):
        result = await WebReader().read_with_links("http://test.com?login=1")
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_read_with_links_propagates_human_intervention():
    exc = HumanInterventionRequiredException("http://vnc", "captcha")
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=exc),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await WebReader().read_with_links("http://test.com")


@pytest.mark.asyncio
async def test_read_with_links_all_strategies_fail():
    with patch(
        "src.reader.web_reader.WebReader._execute_html_strategy",
        new=AsyncMock(return_value=""),
    ):
        result = await WebReader().read_with_links("http://test.com")
    assert result["status"] == "error"
    assert result["reason"] == "all_tiers_failed"


@pytest.mark.asyncio
async def test_read_with_links_falls_through_to_novnc_on_challenge():
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job</a></body></html>"
    )
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(side_effect=ChallengeDetectedException(intervention_type="login")),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.flaresolverr_strategy.FlareSolverrStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
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
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_execute_strategy_returns_none_on_exception():
    reader = WebReader()
    fail_strategy = MagicMock()
    fail_strategy.get_html = AsyncMock(side_effect=RuntimeError("boom"))
    result = await reader._execute_strategy("dummy", fail_strategy, "http://test.com")
    assert result is None


@pytest.mark.asyncio
async def test_execute_strategy_returns_none_on_validation_fail():
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(return_value=_ARTICLE_HTML)
    with patch("src.validator.content_validator.ContentValidator.validate", return_value=False):
        result = await reader._execute_strategy("dummy", strategy, "http://test.com")
    assert result is None


@pytest.mark.asyncio
async def test_execute_html_strategy_returns_empty_on_exception():
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(side_effect=RuntimeError("boom"))
    result = await reader._execute_html_strategy("dummy", strategy, "http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_execute_html_strategy_returns_empty_string_when_html_blank():
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(return_value="")
    result = await reader._execute_html_strategy("dummy", strategy, "http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_read_bails_when_budget_exceeded():
    """READ_TOTAL_BUDGET shortcut path: NoVNC rescue also fails, so reason stays budget_exhausted."""
    reader = WebReader()
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
    ):
        result = await reader.read("http://test.com")
    assert result["status"] == "error"
    assert result["reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_read_bails_but_novnc_rescue_succeeds():
    """READ_TOTAL_BUDGET shortcut path: NoVNC is exempt from the budget check
    and, when it returns usable content, its result is the successful read."""
    reader = WebReader()
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=_ARTICLE_HTML),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await reader.read("http://test.com")
    assert result["status"] == "success"
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_with_links_bails_when_budget_exceeded():
    reader = WebReader()
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
    ):
        result = await reader.read_with_links("http://test.com")
    assert result["status"] == "error"
    assert result["reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_read_with_links_bails_but_novnc_rescue_succeeds():
    """NoVNC is exempt from the budget check on the links path too: when it
    returns usable content, its result is the successful read."""
    reader = WebReader()
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job One</a></body></html>"
    )
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=raw_html),
        ),
    ):
        result = await reader.read_with_links("http://test.com")
    assert result["status"] == "success"
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_with_links_bails_and_novnc_rescue_fails_validation():
    """NoVNC's rescue HTML can clear the interstitial gate yet still fail the
    annotated-content validator; that must end in a failure response, not a
    false success."""
    reader = WebReader()
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job One</a></body></html>"
    )
    with (
        patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.get_html",
            new=AsyncMock(return_value=raw_html),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=False),
    ):
        result = await reader.read_with_links("http://test.com")
    assert result["status"] == "error"
    assert result["reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_failure_response_reports_all_tiers_failed_when_strategies_run_but_all_fail():
    with patch(
        "src.reader.web_reader.WebReader._execute_strategy",
        new=AsyncMock(return_value=None),
    ):
        result = await WebReader().read("http://test.com")
    assert result["reason"] == "all_tiers_failed"


@pytest.mark.asyncio
async def test_read_falls_through_when_validation_fails_then_succeeds():
    """Validation-fail on tier 1 should not stop the chain."""
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
    assert result["mode"] == "2-trafilatura"


@pytest.mark.asyncio
async def test_read_with_links_validation_fail_then_next_tier_succeeds():
    short_html = "<html><body>short</body></html>"
    long_html = (
        "<html><body>This is long enough filler content to pass the validator. "
        "<a href='https://example.com/x'>Link</a></body></html>"
    )
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
    assert result["status"] == "success"
    assert result["mode"] == "2-trafilatura"


@pytest.mark.asyncio
async def test_read_with_links_falls_through_when_annotated_content_fails_validation():
    """Raw HTML that clears the interstitial gate (real, article-shaped content)
    can still fail ContentValidator on the annotated text; that must fall
    through to the next tier rather than stopping the chain."""
    raw_html = (
        "<html><body>This is filler text to pass the ten word minimum validation limit "
        "<a href='https://example.com/job1'>Job One</a></body></html>"
    )
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
    assert result["status"] == "success"
    assert result["mode"] == "2-trafilatura"


@pytest.mark.asyncio
async def test_load_user_agents_falls_back_when_path_missing():
    reader = WebReader()
    with patch("src.reader.web_reader.Path.exists", return_value=False):
        agents = reader._load_user_agents()
    assert isinstance(agents, list)
    assert len(agents) >= 1


@pytest.mark.asyncio
async def test_read_json_file_returns_fallback_on_bad_json(tmp_path):
    reader = WebReader()
    bad = tmp_path / "broken.json"
    bad.write_text("not json", encoding="utf-8")
    agents = reader._read_json_file(bad)
    assert isinstance(agents, list)


def test_get_random_user_agent_returns_string():
    reader = WebReader()
    assert isinstance(reader._get_random_user_agent(), str)


@pytest.mark.asyncio
async def test_execute_html_strategy_falls_through_on_challenge():
    """A challenge on the get_html path yields '' so the ladder advances to the next tier."""
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(side_effect=ChallengeDetectedException(intervention_type="login"))
    result = await reader._execute_html_strategy("1-beautifulsoup", strategy, "http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_execute_strategy_falls_through_on_challenge():
    """A challenge on the get_html path yields None so the ladder advances to the next tier."""
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(side_effect=ChallengeDetectedException(intervention_type="captcha"))
    result = await reader._execute_strategy("1-beautifulsoup", strategy, "http://test.com")
    assert result is None


@pytest.mark.asyncio
async def test_execute_strategy_rejects_interstitial_before_validating():
    """A tier that returns a small page with no article-shaped content (an
    interstitial that clears ContentValidator's shallow checks) must be
    rejected before ever reaching content validation, not reported as success."""
    reader = WebReader()
    strategy = MagicMock()
    interstitial_html = "<html><body><p>Continue shopping</p></body></html>"
    strategy.get_html = AsyncMock(return_value=interstitial_html)
    with patch("src.validator.content_validator.ContentValidator.validate", return_value=True):
        result = await reader._execute_strategy("1-beautifulsoup", strategy, "http://test.com")
    assert result is None


@pytest.mark.asyncio
async def test_execute_html_strategy_rejects_interstitial_before_returning():
    """The links path must reject a tier's raw HTML when the article extractor
    finds nothing, even though annotate_links would otherwise accept it."""
    reader = WebReader()
    strategy = MagicMock()
    interstitial_html = "<html><body><p>Continue shopping</p></body></html>"
    strategy.get_html = AsyncMock(return_value=interstitial_html)
    result = await reader._execute_html_strategy("1-beautifulsoup", strategy, "http://test.com")
    assert result == ""


@pytest.mark.asyncio
async def test_read_rejects_amazon_style_interstitial_and_escalates():
    """End-to-end regression test for the reported bug: a 200 response whose
    entire body is Amazon's own captcha interstitial must not be reported as a
    successful scrape. This is a trimmed faithful copy of the real page fetched
    from amazon.pl on 2026-09-04: it carries no phrase from the dictionary, and
    its footer boilerplate (terms/privacy links, copyright line) alone clears
    has_real_content's word count, so only the locale-independent structural
    marker (the fixed internal form action Amazon uses for this page) catches
    it. A fixture built from a dictionary phrase would pass for the wrong
    reason and miss a regression in the structural check."""
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
            "src.reader.strategies.flaresolverr_strategy.FlareSolverrStrategy.get_html",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.get_html",
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
