"""The crawlee tier leaves the process logging as the service configured it."""

import logging
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from crawlee.crawlers import AdaptivePlaywrightCrawler

from src.api.exceptions import ChallengeDetectedException, ExtractionFailedError
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from tests.reader.crawlee_test_support import final_statistics

_CRAWLER_FACTORY_PATH = (
    "src.reader.strategies.crawlee_strategy.AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser"
)

_CRAWLER_TEMP_DIR_WARNING = "ignore:Implicitly cleaning up:ResourceWarning"

_WATCHED_LOGGER_NAMES = ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx")


@dataclass(frozen=True)
class _LoggerState:
    handlers: tuple[logging.Handler, ...]
    formatters: tuple[logging.Formatter | None, ...]
    level: int
    propagate: bool


def _state_of(logger: logging.Logger) -> _LoggerState:
    return _LoggerState(
        handlers=tuple(logger.handlers),
        formatters=tuple(handler.formatter for handler in logger.handlers),
        level=logger.level,
        propagate=logger.propagate,
    )


def _process_logging() -> dict[str, _LoggerState]:
    states = {name: _state_of(logging.getLogger(name)) for name in _WATCHED_LOGGER_NAMES}
    states["root"] = _state_of(logging.getLogger())

    return states


class _ListHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def service_handler() -> Iterator[_ListHandler]:
    handler = _ListHandler()
    root = logging.getLogger()
    root.addHandler(handler)
    yield handler
    root.removeHandler(handler)


async def _read_with_a_real_crawler() -> Any:
    built: dict[str, Any] = {}
    real_factory = AdaptivePlaywrightCrawler.with_beautifulsoup_static_parser

    def build_real_crawler(**kwargs: Any) -> Any:
        crawler = real_factory(**kwargs)
        crawler.run = AsyncMock(return_value=final_statistics(1))  # type: ignore[method-assign]
        built["crawler"] = crawler

        return crawler

    with (
        patch(_CRAWLER_FACTORY_PATH, side_effect=build_real_crawler),
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch("src.reader.strategies.crawlee_strategy.check_fetch_uri", new=AsyncMock()),
    ):
        await CrawleeStrategy(MagicMock()).get_html("https://example.com/article")

    return built["crawler"]


@pytest.mark.asyncio
@pytest.mark.filterwarnings(_CRAWLER_TEMP_DIR_WARNING)
async def test_a_crawlee_read_leaves_the_root_and_uvicorn_loggers_unchanged(
    service_handler: _ListHandler,
) -> None:
    # given
    before = _process_logging()

    # when
    await _read_with_a_real_crawler()

    # then
    assert _process_logging() == before


@pytest.mark.asyncio
@pytest.mark.filterwarnings(_CRAWLER_TEMP_DIR_WARNING)
async def test_crawlee_log_records_reach_the_service_handlers(service_handler: _ListHandler) -> None:
    # given
    crawler = await _read_with_a_real_crawler()

    # when
    crawler.log.warning("crawlee record for the service handler")

    # then
    assert "crawlee record for the service handler" in service_handler.messages


_USER_INFO_URL = "https://reader:hunter2@www.example.com/page?X-Amz-Signature=secret"


def _crawler_reporting(requests_finished: int, page: MagicMock | None = None) -> Any:
    captured: dict[str, Any] = {}

    def fake_crawler_factory(**_kwargs: Any) -> MagicMock:
        crawler = MagicMock()
        crawler.router.default_handler = lambda f: captured.setdefault("default", f)
        crawler.pre_navigation_hook = lambda f: f

        async def fake_run(_urls: list[str]) -> Any:
            if page is not None:
                crawl_context = MagicMock()
                crawl_context.page = page
                await captured["default"](crawl_context)

            return final_statistics(requests_finished)

        crawler.run = AsyncMock(side_effect=fake_run)

        return crawler

    return fake_crawler_factory


def _hermetic_read() -> Any:
    return (
        patch(
            "src.reader.strategies.crawlee_strategy.cookie_manager.get_storage_state",
            new=AsyncMock(return_value=None),
        ),
        patch("src.reader.strategies.crawlee_strategy.check_fetch_uri", new=AsyncMock()),
    )


async def test_a_crawl_that_handled_nothing_names_the_read_without_its_user_info(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    seed_storage, seed_check = _hermetic_read()

    # when
    with (
        patch(_CRAWLER_FACTORY_PATH, side_effect=_crawler_reporting(0)),
        seed_storage,
        seed_check,
        pytest.raises(ExtractionFailedError) as exc,
    ):
        await CrawleeStrategy(MagicMock()).get_html(_USER_INFO_URL)

    # then
    assert "https://www.example.com/page" in str(exc.value)
    assert "hunter2" not in str(exc.value)
    assert "X-Amz-Signature" not in str(exc.value)
    assert "https://www.example.com/page" in caplog.text
    assert "hunter2" not in caplog.text
    assert "X-Amz-Signature" not in caplog.text


async def test_a_wall_read_logs_the_read_without_its_user_info(caplog: pytest.LogCaptureFixture) -> None:
    # given
    page = MagicMock()
    page.content = AsyncMock(return_value="<html><body><div id='cf-challenge-running'></div></body></html>")
    page.url = _USER_INFO_URL
    seed_storage, seed_check = _hermetic_read()
    caplog.set_level(logging.DEBUG)

    # when
    with (
        patch(_CRAWLER_FACTORY_PATH, side_effect=_crawler_reporting(1, page)),
        seed_storage,
        seed_check,
        pytest.raises(ChallengeDetectedException),
    ):
        await CrawleeStrategy(MagicMock()).get_html(_USER_INFO_URL)

    # then
    assert "WAF/Cloudflare block detected on https://www.example.com/page" in caplog.text
    assert "hunter2" not in caplog.text
    assert "X-Amz-Signature" not in caplog.text
