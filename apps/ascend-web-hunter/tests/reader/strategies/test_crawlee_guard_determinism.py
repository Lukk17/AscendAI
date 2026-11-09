"""The crawlee tier fails closed on every read: no stale queue, no silent empty crawl.

A read of the same URL twice must reach the site twice. Crawlee deduplicates a request
that an earlier crawl already handled when both crawls share a request queue, so each
read owns a queue and drops it when the crawl ends. A crawl that handled no request at
all never returns an empty page that the reader would treat as "escalate to NoVNC".
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError
from crawlee.crawlers import RenderingTypePrediction, RenderingTypePredictor
from crawlee.statistics import FinalStatistics
from crawlee.storages import RequestQueue

from src.api.exceptions import ExtractionFailedError
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from tests.reader.crawlee_test_support import final_statistics

_URL = "http://e2e-fake-site:7031/redirect-blocked"

_CRAWLER_FACTORY_PATH = (
    "src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser"
)


def _fake_crawler(run: Any) -> MagicMock:
    crawler = MagicMock()
    crawler.router = MagicMock()
    crawler.router.default_handler = lambda f: f
    crawler.pre_navigation_hook = lambda f: f
    crawler.run = AsyncMock(side_effect=run)
    return crawler


@contextmanager
def _hermetic() -> Iterator[None]:
    """Keep the tier away from Redis, the DNS lookup and the login-wall check."""
    with (
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch("src.reader.strategies.crawlee_strategy.check_fetch_uri", new=AsyncMock()),
        patch(
            "src.reader.strategies.crawlee_strategy.ChallengeDetector.is_login_required",
            return_value=False,
        ),
    ):
        yield


@pytest.mark.asyncio
async def test_each_read_processes_the_url_in_its_own_request_queue() -> None:
    """Two reads of one URL each get a fresh queue that is dropped when the crawl ends."""
    # given
    processed: list[str | None] = []
    managers: list[Any] = []
    drops: list[AsyncMock] = []

    def fake_crawler_factory(**kwargs: Any) -> MagicMock:
        manager = kwargs.get("request_manager")
        managers.append(manager)

        async def fake_run(urls: list[str]) -> FinalStatistics:
            if manager is None:
                processed.append(None)
                return final_statistics(1)
            manager.drop = AsyncMock(wraps=manager.drop)
            drops.append(manager.drop)
            await manager.add_request(urls[0])
            request = await manager.fetch_next_request()
            processed.append(request.url if request is not None else None)
            return final_statistics(1 if request is not None else 0)

        return _fake_crawler(fake_run)

    # when
    with patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory), _hermetic():
        strategy = CrawleeStrategy(MagicMock())
        await strategy.get_html(_URL)
        await strategy.get_html(_URL)

    # then
    assert processed == [_URL, _URL]
    assert all(isinstance(manager, RequestQueue) for manager in managers)
    assert managers[0] is not managers[1]
    assert managers[0].name != managers[1].name
    assert [drop.await_count for drop in drops] == [1, 1]


@pytest.mark.asyncio
async def test_crawl_that_handled_no_request_raises_extraction_failed() -> None:
    """A crawl that processed zero requests is a failure, never an empty page."""

    # given
    async def fake_run(_urls: list[str]) -> FinalStatistics:
        return final_statistics(0)

    # when / then
    with patch(_CRAWLER_FACTORY_PATH, return_value=_fake_crawler(fake_run)), _hermetic():
        with pytest.raises(ExtractionFailedError, match="handled no request"):
            await CrawleeStrategy(MagicMock()).get_html(_URL)


@pytest.mark.asyncio
async def test_refused_navigation_outranks_an_empty_crawl() -> None:
    """A refused navigation still answers unsafe_uri, not extraction_failed."""
    # given
    captured: dict[str, Any] = {}
    fake_context = MagicMock()
    fake_context.page.context.route = AsyncMock()
    fake_context.page.on = MagicMock()

    def fake_crawler_factory(**_kwargs: Any) -> MagicMock:
        crawler = MagicMock()
        crawler.router = MagicMock()
        crawler.router.default_handler = lambda f: f
        crawler.pre_navigation_hook = lambda f: captured.setdefault("pre_nav", f)

        async def fake_run(_urls: list[str]) -> FinalStatistics:
            await captured["pre_nav"](fake_context)
            return final_statistics(0)

        crawler.run = AsyncMock(side_effect=fake_run)
        return crawler

    # when / then
    with (
        patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory),
        _hermetic(),
        patch(
            "src.reader.strategies.crawlee_strategy.install_browser_guard",
            new=AsyncMock(return_value=["http://169.254.169.254/"]),
        ),
    ):
        with pytest.raises(UnsafeUriError):
            await CrawleeStrategy(MagicMock()).get_html(_URL)


@pytest.mark.asyncio
async def test_crawlee_forces_the_browser_rendering_type() -> None:
    """Every read takes the browser path, where the navigation guard is installed."""
    # given
    captured: dict[str, Any] = {}

    def fake_crawler_factory(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)

        async def fake_run(_urls: list[str]) -> FinalStatistics:
            return final_statistics(1)

        return _fake_crawler(fake_run)

    # when
    with patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory), _hermetic():
        await CrawleeStrategy(MagicMock()).get_html(_URL)

    # then
    predictor = captured["rendering_type_predictor"]
    assert isinstance(predictor, RenderingTypePredictor)
    assert predictor.predict(MagicMock()) == RenderingTypePrediction("client only", 0.0)
    assert predictor.store_result(MagicMock(), "client only") is None


_CRAWLEE_ATTEMPTS = 4
"""One navigation plus crawlee's three default retries."""


def _retrying_crawler(fetches: list[str], refuse: bool) -> tuple[MagicMock, Any]:
    """A crawler that retries a failed navigation the way crawlee does: the error handler
    runs before each retry, and a stopped crawler starts no further attempt."""
    captured: dict[str, Any] = {}
    refused_lists: list[list[str]] = []
    fake_context = MagicMock()

    async def install_guard(_browser_context: Any, _validator: Any, *, family: Any) -> list[str]:
        refused_lists.append([])
        return refused_lists[-1]

    crawler = MagicMock()
    crawler.router = MagicMock()
    crawler.router.default_handler = lambda f: f
    crawler.pre_navigation_hook = lambda f: captured.setdefault("pre_nav", f)
    crawler.error_handler = lambda f: captured.setdefault("error_handler", f)

    async def fake_run(_urls: list[str]) -> FinalStatistics:
        for _attempt in range(_CRAWLEE_ATTEMPTS):
            await captured["pre_nav"](fake_context)
            fetches.append(_URL)
            if refuse:
                refused_lists[-1].append("http://169.254.169.254/")
            await captured["error_handler"](MagicMock(), RuntimeError("net::ERR_BLOCKED_BY_CLIENT"))
            if crawler.stop.called:
                break
        return final_statistics(0)

    crawler.run = AsyncMock(side_effect=fake_run)

    return crawler, install_guard


@pytest.mark.asyncio
async def test_refused_navigation_is_fetched_once_and_never_retried() -> None:
    """A navigation the guard refused stops the crawl, so crawlee sends no retry to the site."""
    # given
    fetches: list[str] = []
    crawler, install_guard = _retrying_crawler(fetches, refuse=True)

    # when
    with (
        patch(_CRAWLER_FACTORY_PATH, return_value=crawler),
        _hermetic(),
        patch("src.reader.strategies.crawlee_strategy.install_browser_guard", new=install_guard),
        pytest.raises(UnsafeUriError),
    ):
        await CrawleeStrategy(MagicMock()).get_html(_URL)

    # then
    assert fetches == [_URL]
    crawler.stop.assert_called_once()


@pytest.mark.asyncio
async def test_transient_navigation_failure_keeps_crawlee_retries() -> None:
    """A failure the guard did not cause is still retried by crawlee."""
    # given
    fetches: list[str] = []
    crawler, install_guard = _retrying_crawler(fetches, refuse=False)

    # when
    with (
        patch(_CRAWLER_FACTORY_PATH, return_value=crawler),
        _hermetic(),
        patch("src.reader.strategies.crawlee_strategy.install_browser_guard", new=install_guard),
        pytest.raises(ExtractionFailedError),
    ):
        await CrawleeStrategy(MagicMock()).get_html(_URL)

    # then
    assert fetches == [_URL] * _CRAWLEE_ATTEMPTS
    crawler.stop.assert_not_called()


@pytest.mark.asyncio
async def test_crawl_runs_one_task_at_a_time_so_a_stop_lands_before_any_retry() -> None:
    """A second worker would fetch the requeued request before the stop is seen."""
    # given
    captured: dict[str, Any] = {}

    def fake_crawler_factory(**kwargs: Any) -> MagicMock:
        captured.update(kwargs)

        async def fake_run(_urls: list[str]) -> FinalStatistics:
            return final_statistics(1)

        return _fake_crawler(fake_run)

    # when
    with patch(_CRAWLER_FACTORY_PATH, side_effect=fake_crawler_factory), _hermetic():
        await CrawleeStrategy(MagicMock()).get_html(_URL)

    # then
    settings = captured["concurrency_settings"]
    assert (settings.max_concurrency, settings.desired_concurrency) == (1, 1)
