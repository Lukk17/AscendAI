"""The scored verdict reads up to CHALLENGE_SHAPE_MAX_BYTES of hostile markup, off the event loop."""

import threading
from collections.abc import Iterator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.reader import web_reader
from src.reader.cloudflare.challenge_signals import ChallengeVerdict, assess
from src.reader.strategies import browser_read, curl_cffi_fetcher, novnc_strategy

_PAGE = "<html><body><p>" + "word " * 200 + "</p></body></html>"


@pytest.fixture
def assess_threads(request: pytest.FixtureRequest) -> Iterator[list[threading.Thread]]:
    threads: list[threading.Thread] = []

    def recording(*args: Any, **kwargs: Any) -> ChallengeVerdict:
        threads.append(threading.current_thread())

        return assess(*args, **kwargs)

    with patch(request.param, new=recording):
        yield threads


@pytest.mark.parametrize("assess_threads", ["src.reader.strategies.curl_cffi_fetcher.assess"], indirect=True)
async def test_a_curl_cffi_verdict_runs_off_the_event_loop(assess_threads: list[threading.Thread]) -> None:
    # given
    response = MagicMock()
    response.status_code = 200
    response.url = "https://example.com/page"
    response.headers = {}

    # when
    await curl_cffi_fetcher._judged_body(response, _PAGE, "test", "https://example.com/page")

    # then
    assert assess_threads
    assert assess_threads[0] is not threading.current_thread()


@pytest.mark.parametrize("assess_threads", ["src.reader.strategies.browser_read.assess"], indirect=True)
async def test_a_browser_verdict_runs_off_the_event_loop(assess_threads: list[threading.Thread]) -> None:
    # given
    responses = MagicMock()
    responses.status_and_headers = AsyncMock(return_value=(200, {}))
    page = MagicMock()
    page.context.cookies = AsyncMock(return_value=[])

    # when
    await browser_read.assess_content(page, "https://example.com/", responses, _PAGE, tier="test")

    # then
    assert assess_threads
    assert assess_threads[0] is not threading.current_thread()


@pytest.mark.parametrize("assess_threads", ["src.reader.strategies.novnc_strategy.assess"], indirect=True)
async def test_a_novnc_verdict_runs_off_the_event_loop(assess_threads: list[threading.Thread]) -> None:
    # given
    responses = MagicMock()
    responses.status_and_headers = AsyncMock(return_value=(200, {}))

    # when
    flow = MagicMock()
    flow.url = "https://example.com/"
    await novnc_strategy._assess_page(_PAGE, responses, {}, flow, MagicMock())

    # then
    assert assess_threads
    assert assess_threads[0] is not threading.current_thread()


@pytest.mark.parametrize("assess_threads", ["src.reader.web_reader.assess"], indirect=True)
async def test_the_second_look_runs_off_the_event_loop(assess_threads: list[threading.Thread]) -> None:
    # when
    await web_reader._second_look(_PAGE, "https://example.com/")

    # then
    assert assess_threads
    assert assess_threads[0] is not threading.current_thread()
