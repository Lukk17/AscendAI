"""The crawlee tier judges a 403, 429 or 503 answer itself instead of letting Crawlee retry it.

The private Crawlee methods called below were checked against Crawlee 1.3.1.

Crawlee's own block handling raises a session error on a blocked status code or on a
challenge iframe before the request handler runs, then rotates the session and fetches
the page again. The tier turns that handling off, so the answer reaches the request
handler once and the tier's scored verdict decides.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from crawlee.crawlers import PlaywrightCrawler
from crawlee.sessions import Session
from crawlee.statistics import FinalStatistics
from prometheus_client import REGISTRY

from src.api.exceptions import ChallengeDetectedException
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from tests.reader.crawlee_test_support import final_statistics

_URL = "http://e2e-fake-site:7031/wall-403"

_CRAWLER_FACTORY_PATH = (
    "src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser"
)

_CHALLENGE_HTML = "<html><head><title>Checking</title></head><body><p>One moment.</p></body></html>"

_CRAWLEE_DEFAULT_RETRY_ON_BLOCKED = True

_CRAWLER_TEMP_DIR_WARNING = "ignore:Implicitly cleaning up:ResourceWarning"
"""Crawlee's BasicCrawler builds a TemporaryDirectory for its TLD cache and keeps only its name,
so constructing a real crawler emits this third-party cleanup warning."""


def _hermetic() -> Any:
    return (
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch("src.reader.strategies.crawlee_strategy.check_fetch_uri", new=AsyncMock()),
    )


def _verdicts(verdict: str) -> float:
    return (
        REGISTRY.get_sample_value("challenge_verdicts_total", {"verdict": verdict, "tier": "crawlee"}) or 0.0
    )


def _main_frame_response(status: int, headers: dict[str, str]) -> MagicMock:
    response = MagicMock(status=status)
    response.all_headers = AsyncMock(return_value=headers)
    response.request.is_navigation_request = MagicMock(return_value=True)
    response.frame.parent_frame = None

    return response


async def _crawler_options() -> dict[str, Any]:
    captured: dict[str, Any] = {}

    def fake_crawler_factory(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)
        crawler = MagicMock()
        crawler.router.default_handler = lambda f: f
        crawler.pre_navigation_hook = lambda f: f
        crawler.run = AsyncMock(return_value=final_statistics(1))

        return crawler

    seed_storage, seed_check = _hermetic()
    with patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory), seed_storage, seed_check:
        await CrawleeStrategy(MagicMock()).get_html(_URL)

    return captured


def _blocked_context(status: int) -> MagicMock:
    context = MagicMock()
    context.response.status = status
    context.session = Session()
    context.page.query_selector = AsyncMock(return_value=MagicMock())

    return context


@pytest.mark.asyncio
@pytest.mark.filterwarnings(_CRAWLER_TEMP_DIR_WARNING)
@pytest.mark.parametrize("status", [403, 429, 503])
async def test_crawlee_hands_a_blocked_status_to_the_request_handler(status: int) -> None:
    """Crawlee's own status and challenge-iframe checks let the answer through to the handler."""
    # given
    options = await _crawler_options()
    crawler = PlaywrightCrawler(
        retry_on_blocked=options.get("retry_on_blocked", _CRAWLEE_DEFAULT_RETRY_ON_BLOCKED),
        ignore_http_error_status_codes=options.get("ignore_http_error_status_codes", ()),
        configure_logging=options.get("configure_logging", True),
    )
    context = _blocked_context(status)

    # when
    after_status_check = await anext(crawler._handle_status_code_response(context))
    after_content_check = await anext(crawler._handle_blocked_request_by_content(context))

    # then
    assert after_status_check is context
    assert after_content_check is context


@pytest.mark.asyncio
async def test_crawlee_read_of_a_403_wall_records_one_wall_verdict() -> None:
    """A 403 answer with the definitive Cloudflare header is one wall verdict under crawlee."""
    # given
    captured: dict[str, Any] = {}
    page = MagicMock()
    page.content = AsyncMock(return_value=_CHALLENGE_HTML)
    page.url = _URL
    page.context.route = AsyncMock()
    page.context.route_web_socket = None

    def fake_crawler_factory(**_kwargs: Any) -> MagicMock:
        crawler = MagicMock()
        crawler.router.default_handler = lambda f: captured.setdefault("default", f)
        crawler.pre_navigation_hook = lambda f: captured.setdefault("pre_nav", f)

        async def fake_run(urls: list[str]) -> FinalStatistics:
            crawl_context = MagicMock()
            crawl_context.page = page
            await captured["pre_nav"](crawl_context)
            listener = next(call.args[1] for call in page.on.call_args_list if call.args[0] == "response")
            listener(_main_frame_response(403, {"cf-mitigated": "challenge"}))
            await captured["default"](crawl_context)

            return final_statistics(1)

        crawler.run = AsyncMock(side_effect=fake_run)

        return crawler

    walls_before = _verdicts("wall")
    others_before = _verdicts("content") + _verdicts("no_content")
    seed_storage, seed_check = _hermetic()

    # when
    with (
        patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory),
        seed_storage,
        seed_check,
        pytest.raises(ChallengeDetectedException) as exc,
    ):
        await CrawleeStrategy(MagicMock(should_block=MagicMock(return_value=False))).get_html(_URL)

    # then
    assert exc.value.verdict.wall is True
    assert "definitive_header" in {signal.id for signal in exc.value.verdict.signals}
    assert _verdicts("wall") == walls_before + 1.0
    assert _verdicts("content") + _verdicts("no_content") == others_before
