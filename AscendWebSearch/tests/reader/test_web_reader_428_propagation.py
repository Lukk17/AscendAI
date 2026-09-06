"""Tests for 428 propagation on the include_links path (task 6.1)."""

from unittest.mock import AsyncMock, patch

import pytest

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.reader.web_reader import WebReader


@pytest.mark.asyncio
async def test_read_with_links_propagates_428_when_novnc_raises():
    """
    When a strategy raises ChallengeDetectedException the orchestrator escalates
    to NoVNC.  If NoVNC raises HumanInterventionRequiredException the 428 must
    propagate out of read_with_links, not be swallowed.
    """
    exc = HumanInterventionRequiredException("http://vnc:7900", "login")

    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(side_effect=Exception("net")),
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
            new=AsyncMock(side_effect=exc),
        ),
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc_info:
            await WebReader().read_with_links("http://test.com")

    assert exc_info.value.vnc_url == "http://vnc:7900"


@pytest.mark.asyncio
async def test_read_with_links_direct_428_propagates():
    """
    When a strategy directly raises HumanInterventionRequiredException
    on the get_html path, it must escape the _execute_html_strategy wrapper.
    """
    exc = HumanInterventionRequiredException("http://vnc:7900", "captcha")

    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=exc),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await WebReader().read_with_links("http://test.com")


@pytest.mark.asyncio
async def test_read_propagates_novnc_busy_instead_of_swallowing_it():
    """
    A read that escalates all the way to NoVNC while another intervention
    already holds the shared browser/display must surface that conflict to
    the caller, not report a generic 'all_tiers_failed'.
    """
    exc = NoVNCFlowBusyException("http://other-site.example", "default")

    with (
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(return_value=""),
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
            new=AsyncMock(side_effect=exc),
        ),
    ):
        with pytest.raises(NoVNCFlowBusyException) as exc_info:
            await WebReader().read("http://test.com")

    assert exc_info.value.holder_url == "http://other-site.example"


@pytest.mark.asyncio
async def test_read_with_links_propagates_novnc_busy_instead_of_swallowing_it():
    exc = NoVNCFlowBusyException("http://other-site.example", "default")

    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=exc),
    ):
        with pytest.raises(NoVNCFlowBusyException):
            await WebReader().read_with_links("http://test.com")
