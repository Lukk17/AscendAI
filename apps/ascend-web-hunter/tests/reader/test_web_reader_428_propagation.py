"""Tests for 428 propagation on the include_links path (task 6.1)."""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.api.exceptions import (
    ChallengeDetectedException,
    HumanInterventionRequiredException,
    NoVNCFlowBusyException,
)
from src.reader.cloudflare.challenge_signals import ChallengeVerdict
from src.reader.web_reader import WebReader


def _login_verdict() -> ChallengeVerdict:
    return ChallengeVerdict(
        score=130,
        threshold=100,
        signals=(),
        vendor=None,
        wall=True,
        has_content=False,
        intervention_type="login",
    )


def _tier_patches(novnc_side_effect: Any) -> list[Any]:
    return [
        patch(
            "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
            new=AsyncMock(side_effect=ChallengeDetectedException(_login_verdict())),
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
            new=AsyncMock(side_effect=novnc_side_effect),
        ),
    ]


@pytest.mark.asyncio
async def test_read_with_links_propagates_428_when_novnc_raises() -> None:
    """
    When a strategy raises ChallengeDetectedException the orchestrator escalates
    to NoVNC.  If NoVNC raises HumanInterventionRequiredException the 428 must
    propagate out of read_with_links, not be swallowed.
    """
    # given
    exc = HumanInterventionRequiredException("http://vnc:7900", "login")

    # when
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
            new=AsyncMock(side_effect=exc),
        ),
    ):
        with pytest.raises(HumanInterventionRequiredException) as exc_info:
            await WebReader().read_with_links("http://test.com")

    # then
    assert exc_info.value.vnc_url == "http://vnc:7900"


@pytest.mark.asyncio
async def test_read_with_links_direct_428_propagates() -> None:
    """
    When a strategy directly raises HumanInterventionRequiredException
    on the get_html path, it must escape the _execute_html_strategy wrapper.
    """
    # given
    exc = HumanInterventionRequiredException("http://vnc:7900", "captcha")

    # when / then
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=exc),
    ):
        with pytest.raises(HumanInterventionRequiredException):
            await WebReader().read_with_links("http://test.com")


@pytest.mark.asyncio
async def test_read_propagates_novnc_busy_instead_of_swallowing_it() -> None:
    """
    A read that escalates all the way to NoVNC while another intervention
    already holds the shared browser/display must surface that conflict to
    the caller, not report a generic 'all_tiers_failed'.
    """
    # given
    exc = NoVNCFlowBusyException("http://other-site.example", "default")

    # when
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
            new=AsyncMock(side_effect=exc),
        ),
    ):
        with pytest.raises(NoVNCFlowBusyException) as exc_info:
            await WebReader().read("http://test.com")

    # then
    assert exc_info.value.holder_url == "http://other-site.example"


@pytest.mark.asyncio
async def test_read_with_links_propagates_novnc_busy_instead_of_swallowing_it() -> None:
    # given
    exc = NoVNCFlowBusyException("http://other-site.example", "default")

    # when / then
    with patch(
        "src.reader.strategies.beautifulsoup_strategy.BeautifulSoupStrategy.get_html",
        new=AsyncMock(side_effect=exc),
    ):
        with pytest.raises(NoVNCFlowBusyException):
            await WebReader().read_with_links("http://test.com")


@pytest.mark.asyncio
async def test_read_forwards_login_verdict_to_novnc_flow_type() -> None:
    # given a login wall verdict on a plain URL from an early tier
    seen: dict[str, Any] = {}

    async def _novnc(url: str, last_verdict: ChallengeVerdict | None = None) -> str:
        seen["verdict"] = last_verdict
        raise HumanInterventionRequiredException(
            "http://vnc:7900",
            last_verdict.intervention_type if last_verdict is not None else "captcha",
        )

    # when the chain escalates to NoVNC
    patches = _tier_patches(_novnc)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with pytest.raises(HumanInterventionRequiredException) as exc_info:
            await WebReader().read("http://test.com")

    # then the 428 carries the verdict type, not the URL fallback
    assert exc_info.value.intervention_type == "login"
    assert isinstance(seen["verdict"], ChallengeVerdict)
    assert seen["verdict"].intervention_type == "login"


@pytest.mark.asyncio
async def test_read_with_links_forwards_login_verdict_to_novnc_flow_type() -> None:
    # given a login wall verdict on a plain URL from an early tier
    seen: dict[str, Any] = {}

    async def _novnc(url: str, last_verdict: ChallengeVerdict | None = None) -> str:
        seen["verdict"] = last_verdict
        raise HumanInterventionRequiredException(
            "http://vnc:7900",
            last_verdict.intervention_type if last_verdict is not None else "captcha",
        )

    # when the chain escalates to NoVNC
    patches = _tier_patches(_novnc)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5], patches[6]:
        with pytest.raises(HumanInterventionRequiredException) as exc_info:
            await WebReader().read_with_links("http://test.com")

    # then the 428 carries the verdict type, not the URL fallback
    assert exc_info.value.intervention_type == "login"
    assert isinstance(seen["verdict"], ChallengeVerdict)
    assert seen["verdict"].intervention_type == "login"
