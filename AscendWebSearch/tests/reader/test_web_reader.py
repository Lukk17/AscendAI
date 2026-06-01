from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.api.exceptions import ChallengeDetectedException, HumanInterventionRequiredException
from src.reader.web_reader import WebReader


@pytest.mark.asyncio
async def test_read_succeeds_on_first_strategy():
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.extract",
            new=AsyncMock(return_value="Extracted Content"),
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
    assert result["reason"] in ("budget_exhausted", "all_tiers_failed")


@pytest.mark.asyncio
async def test_read_preempts_to_novnc_on_login_redirect_url():
    with (
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.extract",
            new=AsyncMock(return_value="NoVNC out"),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com?login=1")
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_heavy_mode_skips_lightweight():
    with (
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.extract",
            new=AsyncMock(return_value="PW Content"),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com", heavy_mode=True)
    assert result["mode"] == "4-playwright_stealth"


@pytest.mark.asyncio
async def test_read_propagates_human_intervention():
    exc = HumanInterventionRequiredException("http://vnc", "captcha")
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.extract",
        new=AsyncMock(side_effect=exc),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await WebReader().read("http://test.com")


@pytest.mark.asyncio
async def test_read_escalates_to_novnc_on_challenge_detected():
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.extract",
            new=AsyncMock(side_effect=ChallengeDetectedException(intervention_type="login")),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.extract",
            new=AsyncMock(return_value="NoVNC out"),
        ),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
    ):
        result = await WebReader().read("http://test.com")
    assert result["mode"] == "6-novnc"


@pytest.mark.asyncio
async def test_read_does_not_recurse_when_novnc_itself_raises_challenge():
    """The escalating=True guard short-circuits the second recursive dispatch."""
    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.extract",
            new=AsyncMock(side_effect=ChallengeDetectedException(intervention_type="login")),
        ),
        patch(
            "src.reader.strategies.novnc_strategy.NoVNCStrategy.extract",
            new=AsyncMock(side_effect=ChallengeDetectedException(intervention_type="captcha")),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.extract",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.flaresolverr_strategy.FlareSolverrStrategy.extract",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.playwright_strategy.PlaywrightStrategy.extract",
            new=AsyncMock(return_value=""),
        ),
        patch(
            "src.reader.strategies.crawlee_strategy.CrawleeStrategy.extract",
            new=AsyncMock(return_value=""),
        ),
    ):
        result = await WebReader().read("http://test.com")
    assert result["status"] == "error"
    assert result["reason"] in (
        "budget_exhausted",
        "all_tiers_failed",
    )  # all strategies including NoVNC failed without recursion


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
    assert result["reason"] in ("budget_exhausted", "all_tiers_failed")


@pytest.mark.asyncio
async def test_read_with_links_escalates_html_to_novnc_on_challenge():
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
    fail_strategy.extract = AsyncMock(side_effect=RuntimeError("boom"))
    result = await reader._execute_strategy("dummy", fail_strategy, "http://test.com")
    assert result is None


@pytest.mark.asyncio
async def test_execute_strategy_returns_none_on_validation_fail():
    reader = WebReader()
    strategy = MagicMock()
    strategy.extract = AsyncMock(return_value="too short")
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
    """READ_TOTAL_BUDGET shortcut path."""
    reader = WebReader()
    with patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0):
        result = await reader.read("http://test.com")
    assert result["status"] == "error"
    assert result["reason"] == "budget_exhausted"


@pytest.mark.asyncio
async def test_read_with_links_bails_when_budget_exceeded():
    reader = WebReader()
    with patch("src.reader.web_reader.settings.READ_TOTAL_BUDGET", 0.0):
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
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.extract",
            new=AsyncMock(return_value="short"),
        ),
        patch(
            "src.reader.strategies.trafilatura_strategy.TrafilaturaStrategy.extract",
            new=AsyncMock(return_value="Long enough validated content here"),
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
async def test_execute_html_strategy_aborts_on_recursive_challenge():
    """When the NoVNC escalation itself raises ChallengeDetectedException,
    the escalating=True guard must short-circuit and return ''."""
    reader = WebReader()
    strategy = MagicMock()
    strategy.get_html = AsyncMock(side_effect=ChallengeDetectedException(intervention_type="login"))
    result = await reader._execute_html_strategy("6-novnc", strategy, "http://test.com", escalating=True)
    assert result == ""
