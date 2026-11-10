import asyncio
import base64
import json
from collections.abc import Awaitable, Callable
from itertools import pairwise
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError, check_fetch_uri
from fakeredis.aioredis import FakeRedis

from src.config.config import settings
from src.crawl import worker as worker_module
from src.crawl.fetcher import CRAWL_USER_AGENT, ConditionalProbe, RobotsFetch
from src.crawl.frontier import ALL_PAGES_FAILED_ERROR, Frontier, claim_entry
from src.crawl.job_service import CrawlJobService
from src.crawl.keys import RUNNABLE_KEY, job_key, next_fetch_key, runnable_member, seen_key
from src.crawl.models import CrawlRequest, JobRecord
from src.crawl.result_store import RecrawlStore, ResultStore, page_object_key, recrawl_scope
from src.crawl.robots import ROBOTS_SKIP_REASON, RobotsStore, SitemapAllowance, _CachedRules
from src.crawl.worker import Worker, seed_domains
from src.reader.extraction import extract_structured, extract_tables
from src.reader.strategies.base_strategy import FetchedHtml
from src.reader.web_reader import TIER_ORDER, OutputFormat, PageResult, TierName, WebReader, _cache_key

NOW = 1_000_000


def _req(**kwargs: Any) -> CrawlRequest:
    fields: dict[str, Any] = {"seeds": ["https://example.com/"]}
    fields.update(kwargs)
    return CrawlRequest(**fields)


async def _stored(redis: FakeRedis, job_id: str) -> JobRecord:
    raw = await redis.get(job_key("acme", job_id))
    assert raw is not None
    return JobRecord.model_validate_json(raw)


class FakeReader(WebReader):
    def __init__(self, pages: dict[str, dict[str, Any]] | None = None) -> None:
        super().__init__()
        self.pages = pages or {}
        self.headers: dict[str, dict[str, str]] = {}
        self.calls: list[str] = []
        self.cache_uses: list[bool] = []

    def page_result(self, url: str, answer: dict[str, Any]) -> PageResult:
        return PageResult(answer, FetchedHtml(str(answer.get("content", "")), self.headers.get(url, {})))

    async def read_linked_page(
        self,
        url: str,
        link_filter: str | None = None,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        *,
        allow_human_tier: bool = True,
        use_read_cache: bool = True,
    ) -> PageResult:
        self.calls.append(url)
        self.cache_uses.append(use_read_cache)
        if url in self.pages:
            return self.page_result(url, self.pages[url])
        return self.page_result(url, {"content": f"content of {url}", "links": {}, "status": "success"})

    async def read_page(
        self,
        url: str,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        extraction_schema: dict[str, Any] | None = None,
        *,
        allow_human_tier: bool = True,
        use_read_cache: bool = True,
    ) -> PageResult:
        self.calls.append(f"read:{url}")
        self.cache_uses.append(use_read_cache)
        return self.page_result(url, {"content": f"formatted {url}", "status": "success", "mode": "test"})


class FakeResults(ResultStore):
    def __init__(self) -> None:
        self.text: dict[str, str] = {}
        self.index_writes: list[tuple[str, list[dict[str, Any]]]] = []
        self.copy_calls: list[tuple[str, str]] = []
        self.copy_mode: str = "ok"
        self.exists_mode: str = "real"
        self.deleted: list[str] = []

    async def write_page(self, key: str, content: str) -> None:
        self.text[key] = content

    async def delete_page(self, key: str) -> None:
        self.deleted.append(key)
        self.text.pop(key, None)

    async def read_page(self, key: str) -> str | None:
        return self.text.get(key)

    async def page_exists(self, key: str) -> bool:
        if self.exists_mode == "vanished":
            self.exists_mode = "gone"
            return True
        if self.exists_mode == "gone":
            return False
        return key in self.text

    async def copy_page_forward(self, source_key: str, dest_key: str) -> None:
        self.copy_calls.append((source_key, dest_key))
        if self.copy_mode == "vanished":
            self.copy_mode = "gone"
            raise KeyError(source_key)
        if self.copy_mode == "gone":
            raise KeyError(source_key)
        if self.copy_mode == "boom":
            raise RuntimeError("copy failed")
        self.text[dest_key] = self.text[source_key]

    async def write_index(self, key: str, lines: list[dict[str, Any]]) -> None:
        self.index_writes.append((key, lines))


async def _allow_guard(url: str, policy: Any) -> Any:
    from ascend_python_common.uri_guard import FetchTarget

    if "127.0.0.1" in url or "10.0.0.1" in url or url.startswith("ftp://"):
        raise UnsafeUriError("non-public")
    return FetchTarget(url=url, host=None, port=None)


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture
def reader() -> FakeReader:
    return FakeReader()


@pytest.fixture
def results() -> FakeResults:
    return FakeResults()


class WorkerHarness(Worker):
    probe_mock: AsyncMock


@pytest.fixture
def worker(
    redis: FakeRedis, reader: FakeReader, results: FakeResults, monkeypatch: pytest.MonkeyPatch
) -> WorkerHarness:
    return _make_worker(redis, reader, results, monkeypatch)


def _make_worker(
    redis: FakeRedis,
    reader: WebReader,
    results: FakeResults,
    monkeypatch: pytest.MonkeyPatch,
) -> WorkerHarness:
    monkeypatch.setattr(worker_module, "check_fetch_uri", _allow_guard)
    monkeypatch.setattr("src.crawl.job_service.check_fetch_uri", _allow_guard)
    ticks = {"now": NOW}

    def clock() -> int:
        ticks["now"] += 2000
        return ticks["now"]

    probe = AsyncMock(return_value=ConditionalProbe(None, None, None))
    robots = RobotsStore(_no_robots_file, _empty_robots)
    w = WorkerHarness(
        redis,
        reader=reader,
        robots=robots,
        results=results,
        recrawl=RecrawlStore(redis),
        probe=probe,
        clock_ms=clock,
    )
    w.probe_mock = probe
    return w


async def _empty_robots(url: str, profile: str | None) -> str:
    return ""


async def _no_robots_file(url: str, profile: str | None) -> RobotsFetch:
    return RobotsFetch(404)


def _serve_robots(worker: Worker, fetch: Callable[[str], Awaitable[str]]) -> None:
    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(200, await fetch(url))

    async def sitemap_fetch(url: str, profile: str | None) -> str:
        return await fetch(url)

    worker._robots._fetch = robots_fetch
    worker._robots._sitemap_fetch = sitemap_fetch


async def _submit(redis: FakeRedis, seeds: list[str], **overrides: Any) -> tuple[CrawlJobService, JobRecord]:
    svc = CrawlJobService()
    svc._client = redis
    fields: dict[str, Any] = {"seeds": seeds}
    fields.update(overrides)
    with patch("src.crawl.job_service.check_fetch_uri", new=_allow_guard):
        record = await svc.submit_job("acme", CrawlRequest(**fields))
    return svc, record


async def _drain(worker: WorkerHarness, limit: int = 20) -> int:
    runs = 0
    while runs < limit and await worker.run_once():
        runs += 1
    return runs


async def test_run_once_idle_when_no_runnable(worker: WorkerHarness) -> None:
    assert await worker.run_once() is False


async def test_full_job_reaches_succeeded_and_writes_index_once(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a two page job on two domains
    _, record = await _submit(redis, ["https://example.com/", "https://example.org/"])

    # when the worker drains it
    assert await _drain(worker) == 2

    # then the job succeeds, the index is written once and the keys are gone
    stored = await _stored(redis, record.job_id)
    assert stored.state == "succeeded"
    assert stored.counts.fetched == 2
    assert stored.pages_ndjson_key == f"tenant/acme/crawl-results/{record.job_id}/pages.ndjson"
    assert len(results.index_writes) == 1
    assert len(results.index_writes[0][1]) == 2
    assert await redis.exists(job_key("acme", record.job_id)) == 1
    assert [key async for key in redis.scan_iter(match="crawl_queue:*")] == []
    assert [key async for key in redis.scan_iter(match="crawl_seen:*")] == []
    assert await worker._frontier.list_runnable() == []


async def test_discovered_private_link_dropped_and_counted(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a page linking a private address, another domain and an off-pattern path
    reader.pages["https://example.com/"] = {
        "content": "home",
        "links": {
            1: "http://127.0.0.1/admin",
            2: "https://other.com/",
            3: "https://example.com/archive/old",
        },
        "status": "success",
    }
    _, record = await _submit(redis, ["https://example.com/"], include_patterns=["/guide/*", "/"])

    # when
    await _drain(worker)

    # then the private link is counted unsafe and never fetched
    stored = await _stored(redis, record.job_id)
    assert stored.counts.skipped_unsafe == 1
    assert stored.state == "succeeded"
    assert "http://127.0.0.1/admin" not in reader.calls
    assert "https://other.com/" not in reader.calls
    assert "https://example.com/archive/old" not in reader.calls


async def test_disallowed_path_is_not_fetched(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a robots.txt that disallows /private/
    async def fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "User-agent: *\nDisallow: /private/\n"
        return ""

    _serve_robots(worker, fetch)
    reader.pages["https://example.com/"] = {
        "content": "home",
        "links": {1: "https://example.com/private/x"},
        "status": "success",
    }
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True)

    # when
    await _drain(worker)

    # then the disallowed path is never read and the index records it as skipped for robots.txt
    assert "https://example.com/private/x" not in reader.calls
    stored = await _stored(redis, record.job_id)
    assert stored.state == "succeeded"
    lines = {line["url"]: line for line in results.index_writes[0][1]}
    assert lines["https://example.com/private/x"] == {
        "url": "https://example.com/private/x",
        "status": "skipped",
        "reason": ROBOTS_SKIP_REASON,
    }
    assert lines["https://example.com/"]["status"] == "fetched"


async def test_seed_given_twice_is_read_once_and_the_job_ends_with_overlapping_claims(
    redis: FakeRedis, results: FakeResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given two workers that claim at once and a read that keeps the first claim in flight
    monkeypatch.setattr(settings, "CRAWL_DEFAULT_DELAY_SECONDS", 0.0)

    class SlowReader(FakeReader):
        async def read_linked_page(self, url: str, *args: Any, **kwargs: Any) -> PageResult:
            await asyncio.sleep(0.02)

            return await super().read_linked_page(url, *args, **kwargs)

    reader = SlowReader()
    first = _make_worker(redis, reader, results, monkeypatch)
    second = _make_worker(redis, reader, results, monkeypatch)
    _, record = await _submit(redis, ["https://example.com/a", "https://example.com/a"])

    # when
    await asyncio.gather(first.run_once(), second.run_once())
    await _drain(first)

    # then
    stored = await _stored(redis, record.job_id)
    assert reader.calls == ["https://example.com/a"]
    assert stored.state == "succeeded"
    assert stored.pending == 0


async def test_links_a_robots_file_disallows_end_the_job_at_the_skip_ceiling(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a budget of 2 and a seed page with 100 links robots.txt disallows
    async def fetch(url: str) -> str:
        return "User-agent: *\nDisallow: /private/\n" if url.endswith("/robots.txt") else ""

    _serve_robots(worker, fetch)
    reader.pages["https://example.com/"] = {
        "content": "home",
        "links": {index: f"https://example.com/private/{index}" for index in range(1, 101)},
        "status": "success",
    }
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True, page_budget=2)

    # when
    await _drain(worker, limit=300)

    # then the job ended at 10 skips per budget page and the rest stayed unread
    stored = await _stored(redis, record.job_id)
    assert stored.state == "succeeded"
    assert stored.counts.robots_skipped == 2 * settings.CRAWL_ROBOTS_SKIP_FACTOR
    assert reader.calls == ["https://example.com/"]


@pytest.mark.parametrize("reason", ["login_required", "all_tiers_failed", "budget_exhausted"])
async def test_page_whose_read_failed_with_a_reason_carries_it_into_the_index(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults, reason: str
) -> None:
    # given one seed whose read fails with a reason and one that reads
    reader.pages["https://example.com/account"] = {
        "content": "",
        "status": "error",
        "reason": reason,
        "error": "the read failed",
    }
    _, record = await _submit(redis, ["https://example.com/account", "https://example.org/"])

    # when
    await _drain(worker)

    # then the failed page counts as failed and its index line names the reason of the read
    stored = await _stored(redis, record.job_id)
    assert stored.state == "succeeded"
    assert stored.counts.failed == 1
    lines = {line["url"]: line for line in results.index_writes[0][1]}
    assert lines["https://example.com/account"] == {
        "url": "https://example.com/account",
        "status": "failed",
        "reason": reason,
    }
    assert lines["https://example.org/"]["status"] == "fetched"


async def test_page_whose_read_failed_without_a_reason_writes_no_index_line(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given one seed whose read fails with no reason and one that reads
    reader.pages["https://example.com/broken"] = {"content": "", "status": "error", "reason": 7}
    _, record = await _submit(redis, ["https://example.com/broken", "https://example.org/"])

    # when
    await _drain(worker)

    # then the failed page counts as failed and leaves no line in the index
    stored = await _stored(redis, record.job_id)
    assert stored.counts.failed == 1
    assert [line["url"] for line in results.index_writes[0][1]] == ["https://example.org/"]


@pytest.mark.parametrize("status", [None, 429, 500, 503])
async def test_seed_whose_robots_txt_is_unreachable_is_skipped_with_the_robots_reason(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults, status: int | None
) -> None:
    # given one seed on an origin whose robots.txt cannot be read and one on an origin without a file
    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        if url == "https://down.example.org/robots.txt":
            return RobotsFetch(status)
        return RobotsFetch(404)

    worker._robots._fetch = robots_fetch
    _, record = await _submit(
        redis, ["https://down.example.org/", "https://example.com/"], respect_robots=True
    )

    # when
    await _drain(worker)

    # then the refused seed is never read and the index names robots.txt as the reason
    assert "https://down.example.org/" not in reader.calls
    stored = await _stored(redis, record.job_id)
    assert stored.state == "succeeded"
    lines = {line["url"]: line for line in results.index_writes[0][1]}
    assert lines["https://down.example.org/"] == {
        "url": "https://down.example.org/",
        "status": "skipped",
        "reason": ROBOTS_SKIP_REASON,
    }
    assert lines["https://example.com/"]["status"] == "fetched"


async def test_seed_whose_robots_txt_answers_404_is_fetched(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a seed whose robots.txt is missing
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True)

    # when
    await _drain(worker)

    # then
    assert "https://example.com/" in reader.calls
    assert (await _stored(redis, record.job_id)).counts.fetched == 1


async def test_crawl_delay_honoured(worker: WorkerHarness, redis: FakeRedis) -> None:
    # given a robots.txt with a 5 second crawl delay
    async def fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "User-agent: *\nCrawl-delay: 5\n"
        return ""

    _serve_robots(worker, fetch)
    _, record = await _submit(redis, ["https://example.com/a", "https://example.com/b"], respect_robots=True)

    # when the first page is claimed
    assert await worker.run_once() is True

    # then the next fetch time carries the robots delay
    from src.crawl.keys import next_fetch_key

    value = await redis.get(next_fetch_key("acme", record.job_id, "example.com"))
    assert int(value or "0") >= NOW + 5000


async def test_sitemap_urls_seed_frontier(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a robots.txt naming a sitemap
    async def fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
        if url.endswith("sitemap.xml"):
            return "<urlset><url><loc>https://example.com/from-sitemap</loc></url></urlset>"
        return ""

    _serve_robots(worker, fetch)
    await _submit(redis, ["https://example.com/"], respect_robots=True)

    # when
    await _drain(worker)

    # then the sitemap URL is fetched too
    assert "https://example.com/from-sitemap" in reader.calls


async def test_default_crawl_reads_a_page_robots_txt_disallows(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a robots.txt that disallows every page and a request that names no respect_robots
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        return "User-agent: *\nDisallow: /\n"

    _serve_robots(worker, fetch)
    _, record = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the page is read, counted as fetched and the robots file is asked for once, for its sitemaps
    assert "https://example.com/" in reader.calls
    assert (await _stored(redis, record.job_id)).counts.fetched == 1
    assert calls == ["https://example.com/robots.txt"]


async def test_ignored_robots_keeps_the_default_delay_and_drops_crawl_delay(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a robots.txt asking for a delay above the setting and a request that names no respect_robots
    monkeypatch.setattr(worker, "_clock_ms", lambda: NOW)

    async def fetch(url: str) -> str:
        return "User-agent: *\nCrawl-delay: 5\n"

    _serve_robots(worker, fetch)
    _, record = await _submit(redis, ["https://example.com/a", "https://example.com/b"])

    # when the first page is claimed
    assert await worker.run_once() is True

    # then the next fetch time carries the setting alone
    value = await redis.get(next_fetch_key("acme", record.job_id, "example.com"))
    assert int(value or "0") == NOW + int(settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000)


async def test_respect_false_skips_robots(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a robots.txt that disallows every page and a request with respect off
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        return "User-agent: *\nDisallow: /\n"

    _serve_robots(worker, fetch)
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=False)

    # when
    await _drain(worker)

    # then the robots file is read once, for its sitemaps, and the page is fetched
    assert calls == ["https://example.com/robots.txt"]
    assert "https://example.com/" in reader.calls
    assert (await _stored(redis, record.job_id)).counts.fetched == 1


ROBOTS_URL = "https://example.com/robots.txt"
SITEMAP_URL = "https://example.com/sitemap.xml"
SITEMAP_PAGE_URL = "https://example.com/from-sitemap"
DISALLOW_ALL_WITH_SITEMAP = f"User-agent: *\nDisallow: /\nCrawl-delay: 5\nSitemap: {SITEMAP_URL}\n"
ONE_PAGE_SITEMAP = f"<urlset><url><loc>{SITEMAP_PAGE_URL}</loc></url></urlset>"


def _serve_disallowing_robots_with_a_sitemap(worker: Worker) -> list[str]:
    fetched: list[str] = []

    async def fetch(url: str) -> str:
        fetched.append(url)
        return DISALLOW_ALL_WITH_SITEMAP if url == ROBOTS_URL else ONE_PAGE_SITEMAP

    _serve_robots(worker, fetch)
    return fetched


async def test_crawl_ignoring_robots_seeds_its_sitemaps_and_reads_pages_robots_txt_disallows(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a robots.txt that disallows every page and names a sitemap, and a request with respect off
    fetched = _serve_disallowing_robots_with_a_sitemap(worker)
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=False)

    # when
    await _drain(worker)

    # then robots.txt and the sitemap are fetched once and both disallowed pages are read
    assert fetched == [ROBOTS_URL, SITEMAP_URL]
    assert reader.calls.count("https://example.com/") == 1
    assert reader.calls.count(SITEMAP_PAGE_URL) == 1
    assert (await _stored(redis, record.job_id)).counts.fetched == 2


async def test_rules_read_for_sitemaps_reach_neither_the_verdict_nor_the_delay_when_robots_is_ignored(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given a job with respect off whose robots.txt was already read for its sitemaps
    fetched = _serve_disallowing_robots_with_a_sitemap(worker)
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=False)
    await worker._seed_sitemaps("acme", record.job_id, record, "https://example.com/", 0)

    # when
    disallowed = await worker._is_disallowed(record, "https://example.com/private")
    delay_ms = await worker._domain_delay_ms(record, "https://example.com/private")

    # then the rules were read, yet no page is skipped and the delay stays at the setting
    assert fetched == [ROBOTS_URL, SITEMAP_URL]
    assert disallowed is False
    assert delay_ms == int(settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000)


@pytest.mark.parametrize("status", [500, 503, 429, None])
async def test_default_crawl_reads_its_pages_when_robots_txt_cannot_be_loaded(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, status: int | None
) -> None:
    # given a robots.txt that answers a server error, a 429 or no answer at all
    asked: list[str] = []

    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        asked.append(url)
        return RobotsFetch(status)

    worker._robots._fetch = robots_fetch
    _, record = await _submit(redis, ["https://example.com/", "https://example.com/b"])

    # when
    await _drain(worker)

    # then robots.txt was asked for once and every page is still read
    stored = await _stored(redis, record.job_id)
    assert asked == [ROBOTS_URL]
    assert sorted(reader.calls) == ["https://example.com/", "https://example.com/b"]
    assert (stored.counts.fetched, stored.counts.failed) == (2, 0)


async def test_default_crawl_reads_its_page_when_the_robots_fetch_raises(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, caplog: pytest.LogCaptureFixture
) -> None:
    # given a robots.txt fetch that raises
    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        raise RuntimeError("robots down")

    worker._robots._fetch = robots_fetch
    _, record = await _submit(redis, ["https://example.com/"])

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        await _drain(worker)

    # then the failure is only logged and the page is read
    assert "crawl: sitemap seed failed for https://example.com/: robots down" in caplog.text
    assert reader.calls == ["https://example.com/"]
    assert (await _stored(redis, record.job_id)).counts.fetched == 1


async def test_default_crawl_reads_its_page_when_a_sitemap_cannot_be_loaded(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, caplog: pytest.LogCaptureFixture
) -> None:
    # given a robots.txt naming a sitemap whose fetch raises
    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        return RobotsFetch(200, f"User-agent: *\nSitemap: {SITEMAP_URL}\n")

    async def sitemap_fetch(url: str, profile: str | None) -> str:
        raise RuntimeError("sitemap down")

    worker._robots._fetch = robots_fetch
    worker._robots._sitemap_fetch = sitemap_fetch
    _, record = await _submit(redis, ["https://example.com/"])

    # when
    with caplog.at_level("WARNING", logger="src.crawl.robots"):
        await _drain(worker)

    # then the failure is only logged and the page is read
    assert f"crawl: sitemap fetch of {SITEMAP_URL} failed: sitemap down" in caplog.text
    assert reader.calls == ["https://example.com/"]
    assert (await _stored(redis, record.job_id)).counts.fetched == 1


async def test_sitemap_address_the_guard_chokes_on_only_logs_and_the_page_is_read(
    worker: WorkerHarness,
    redis: FakeRedis,
    reader: FakeReader,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given a sitemap address whose host makes the guard raise something other than a refusal
    _serve_disallowing_robots_with_a_sitemap(worker)

    async def choking_guard(url: str, policy: Any) -> Any:
        if url == SITEMAP_PAGE_URL:
            raise UnicodeError("label empty or too long")
        return await _allow_guard(url, policy)

    monkeypatch.setattr(worker_module, "check_fetch_uri", choking_guard)
    _, record = await _submit(redis, ["https://example.com/"])

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        await _drain(worker)

    # then the failure is only logged and the page is read
    assert "crawl: sitemap seed failed for https://example.com/: label empty or too long" in caplog.text
    assert reader.calls == ["https://example.com/"]
    assert (await _stored(redis, record.job_id)).counts.fetched == 1


async def _run_job_twice(worker: WorkerHarness, redis: FakeRedis) -> tuple[JobRecord, JobRecord]:
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    _, second = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    stored_first = await _stored(redis, first.job_id)
    stored_second = await _stored(redis, second.job_id)
    return stored_first, stored_second


async def _set_stored_validators(redis: FakeRedis, etag: str | None, last_modified: str | None) -> None:
    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(_req())
    entry = await recrawl.read("acme", scope, "https://example.com/")
    assert entry is not None
    entry["etag"] = etag
    entry["last_modified"] = last_modified
    await recrawl.write("acme", scope, "https://example.com/", entry)


async def _stored_validators(redis: FakeRedis) -> tuple[str | None, str | None]:
    entry = await RecrawlStore(redis).read("acme", recrawl_scope(_req()), "https://example.com/")
    assert entry is not None
    return entry["etag"], entry["last_modified"]


async def test_304_copies_forward_without_read(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a completed job and a 304 probe on the identical recrawl that carries new validators
    await _run_job_twice(worker, redis)
    assert len(reader.calls) == 2
    await _set_stored_validators(redis, '"v0"', "Mon")
    copies_before = len(results.copy_calls)
    probe = worker.probe_mock
    probe.return_value = ConditionalProbe(304, '"v1"', "Tue")
    _, third = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then no new read happens, the page counts as unchanged and the 304's validators are stored
    assert len(reader.calls) == 2
    stored = await _stored(redis, third.job_id)
    assert stored.counts.unchanged == 1
    assert stored.counts.fetched == 0
    assert len(results.copy_calls) == copies_before + 1
    assert await _stored_validators(redis) == ('"v1"', "Tue")


async def test_304_carrying_only_an_etag_keeps_the_stored_last_modified(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a stored page with both validators and a 304 that names only a new ETag
    await _run_job_twice(worker, redis)
    await _set_stored_validators(redis, '"v0"', "Mon")
    worker.probe_mock.return_value = ConditionalProbe(304, '"v1"', None)
    _, third = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the new ETag is stored and the Last-Modified of the unchanged content is kept
    assert (await _stored(redis, third.job_id)).counts.unchanged == 1
    assert await _stored_validators(redis) == ('"v1"', "Mon")


async def test_304_carrying_no_validators_keeps_the_stored_ones(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a stored page with both validators and a 304 that carries none
    await _run_job_twice(worker, redis)
    await _set_stored_validators(redis, '"v0"', "Mon")
    worker.probe_mock.return_value = ConditionalProbe(304, None, None)
    _, third = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the stored validators stay as they were
    assert (await _stored(redis, third.job_id)).counts.unchanged == 1
    assert await _stored_validators(redis) == ('"v0"', "Mon")


async def test_equal_hash_copies_forward(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a completed job and a 200 probe with the same content under a new ETag
    await _run_job_twice(worker, redis)
    await _set_stored_validators(redis, '"v0"', "Mon")
    probe = worker.probe_mock
    probe.return_value = ConditionalProbe(200, '"v2"', None)
    reader.headers["https://example.com/"] = {"etag": '"r2"', "last-modified": "Tue"}
    writes_before = len(results.text)
    _, third = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the read happens, the file is copied, not re-uploaded, and the read's validators are stored
    stored = await _stored(redis, third.job_id)
    assert stored.counts.unchanged == 1
    assert len(results.copy_calls) >= 1
    assert len(results.text) == writes_before + 1
    assert await _stored_validators(redis) == ('"r2"', "Tue")

    # and the next recrawl's conditional request sends them
    await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    assert probe.await_args is not None
    assert probe.await_args.kwargs == {"etag": '"r2"', "last_modified": "Tue", "profile": None}


async def test_missing_earlier_file_reads_unconditionally(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a recrawl entry with old validators whose page file is gone
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    await _set_stored_validators(redis, '"old"', "Mon")
    probe = worker.probe_mock
    calls_before = probe.await_count
    _, second = await _submit(redis, ["https://example.com/"])
    from src.crawl.result_store import RecrawlStore, recrawl_scope

    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(_req())
    entry = await recrawl.read("acme", scope, "https://example.com/")
    assert entry is not None
    results.text.pop(entry["page_key"])
    reader.headers["https://example.com/"] = {"etag": '"new"', "last-modified": "Tue"}

    # when
    await _drain(worker)

    # then no conditional probe runs, the page is written new with the validators of its own read
    assert probe.await_count == calls_before
    stored = await _stored(redis, second.job_id)
    assert stored.counts.fetched == 1
    assert stored.counts.unchanged == 0
    assert "https://example.com/" in reader.calls
    assert await _stored_validators(redis) == ('"new"', "Tue")


async def test_vanished_source_between_head_and_copy_reads_unconditionally(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a copy that fails because the source vanished
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    results.copy_mode = "vanished"
    results.exists_mode = "vanished"
    probe = worker.probe_mock
    probe.return_value = ConditionalProbe(304, '"v1"', None)
    _, second = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the page is fetched once more and written as a file
    stored = await _stored(redis, second.job_id)
    assert stored.counts.fetched == 1
    assert stored.counts.unchanged == 0


async def test_copy_failure_marks_page_failed(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a copy that keeps failing while the source still exists
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    results.copy_mode = "boom"
    probe = worker.probe_mock
    probe.return_value = ConditionalProbe(304, '"v1"', None)
    _, second = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the page counts as failed and the job with no page read ends failed
    stored = await _stored(redis, second.job_id)
    assert stored.counts.failed == 1
    assert stored.state == "failed"


async def test_cancelled_finish_writes_nothing(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a claimed page of a job cancelled by another instance
    svc, record = await _submit(redis, ["https://example.com/"])
    frontier = Frontier(redis)
    from src.crawl.keys import claims_key, inflight_key, next_fetch_key, queue_key

    await frontier.claim(
        job_key=job_key("acme", record.job_id),
        queue_key=queue_key("acme", record.job_id, "example.com"),
        inflight_key=inflight_key("acme", record.job_id, "example.com"),
        claims_key=claims_key("acme", record.job_id),
        next_fetch_key=next_fetch_key("acme", record.job_id, "example.com"),
        runnable_key=RUNNABLE_KEY,
        now_ms=NOW,
        lease_ms=120000,
        page_budget=100,
        domain_cap=2,
        delay_ms=0,
        retention=settings.CRAWL_JOB_RETENTION_SECONDS,
        member=runnable_member("acme", record.job_id),
        max_expiries=2,
        updated_at="2026-10-19T00:00:00+00:00",
        tenant_id="acme",
        job_id=record.job_id,
        domain="example.com",
        robots_skip_factor=10,
    )
    await svc.cancel_job("acme", record.job_id)

    # when the late page finishes
    await worker._finish(
        "acme",
        record.job_id,
        runnable_member("acme", record.job_id),
        record,
        "example.com",
        claim_entry(0, "example.com", "https://example.com/"),
        outcome="ok",
        page_line='{"url": "x"}',
        links=[],
        skipped=0,
    )

    # then nothing is written
    assert results.index_writes == []
    assert results.text == {}


async def test_max_two_pages_read_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    # given six ready URLs on six domains and two worker tasks
    redis = FakeRedis(decode_responses=True)
    monkeypatch.setattr(settings, "CRAWL_WORKER_IDLE_SECONDS", 0.01)
    active = {"now": 0, "peak": 0, "done": 0}
    release = asyncio.Event()
    peaked = asyncio.Event()
    drained = asyncio.Event()

    class BlockingReader(FakeReader):
        async def read_linked_page(
            self,
            url: str,
            link_filter: str | None = None,
            heavy_mode: bool = False,
            profile: str | None = None,
            output_format: OutputFormat | None = None,
            tier: TierName | None = None,
            *,
            allow_human_tier: bool = True,
            use_read_cache: bool = True,
        ) -> PageResult:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
            if active["peak"] >= 2:
                peaked.set()
            await release.wait()
            active["now"] -= 1
            active["done"] += 1
            if active["done"] >= 6:
                drained.set()
            return self.page_result(url, {"content": f"c {url}", "links": {}, "status": "success"})

    reader = BlockingReader()
    with patch("src.crawl.job_service.check_fetch_uri", new=_allow_guard):
        with patch("src.crawl.worker.check_fetch_uri", new=_allow_guard):
            svc = CrawlJobService()
            svc._client = redis
            await svc.submit_job(
                "acme",
                _req(
                    seeds=[
                        "https://a-one.com/",
                        "https://b-two.com/",
                        "https://c-three.com/",
                        "https://d-four.com/",
                        "https://e-five.com/",
                        "https://f-six.com/",
                    ]
                ),
            )
    worker = Worker(
        redis, reader=reader, robots=RobotsStore(_no_robots_file, _empty_robots), clock_ms=lambda: NOW
    )

    # when two tasks sweep together
    stop = asyncio.Event()
    first = asyncio.create_task(worker.run_forever(stop))
    second = asyncio.create_task(worker.run_forever(stop))
    await asyncio.wait_for(peaked.wait(), timeout=10)
    release.set()
    await asyncio.wait_for(drained.wait(), timeout=10)
    stop.set()
    await asyncio.gather(first, second)

    # then at most two pages were read at once
    assert active["peak"] == 2
    assert first.done()
    assert second.done()


async def test_run_forever_waits_idle_between_sweeps(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a short idle wait
    monkeypatch.setattr(settings, "CRAWL_WORKER_IDLE_SECONDS", 0.05)
    stamps: list[float] = []
    real_list = worker._frontier.list_runnable

    async def timed() -> list[str]:
        stamps.append(asyncio.get_event_loop().time())
        return await real_list()

    monkeypatch.setattr(worker._frontier, "list_runnable", timed)

    # when the loop runs briefly
    stop = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.22)
        stop.set()

    await asyncio.gather(worker.run_forever(stop), stopper())

    # then consecutive sweeps wait the idle time
    assert len(stamps) >= 2
    gaps = [later - earlier for earlier, later in pairwise(stamps)]
    assert max(gaps) >= 0.04


async def test_run_once_survives_broken_redis(worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    # given a client that fails every read
    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._frontier, "list_runnable", boom)

    # when / then no raise
    assert await worker.run_once() is False


async def test_run_forever_survives_sweep_error(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a sweep that fails once
    calls = {"n": 0}

    async def flaky() -> bool:
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return False

    monkeypatch.setattr(worker, "run_once", flaky)
    monkeypatch.setattr(settings, "CRAWL_WORKER_IDLE_SECONDS", 0.01)
    stop = asyncio.Event()

    async def stopper() -> None:
        await asyncio.sleep(0.05)
        stop.set()

    # when / then no raise
    await asyncio.gather(worker.run_forever(stop), stopper())
    assert calls["n"] >= 2


async def test_a_stored_job_with_an_old_bad_profile_is_removed_from_the_sweep(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given
    svc = CrawlJobService()
    svc._client = redis
    with patch("src.crawl.job_service.check_fetch_uri", new=_allow_guard):
        record = await svc.submit_job("acme", _req())
    raw = await redis.get(job_key("acme", record.job_id))
    assert raw is not None
    stored = json.loads(raw)
    stored["request"]["profile"] = "a\nb"
    await redis.set(job_key("acme", record.job_id), json.dumps(stored))

    # when
    assert await worker.run_once() is False

    # then
    assert await worker._frontier.list_runnable() == []


async def test_drain_member_removes_gone_corrupt_terminal_and_bad_members(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given a missing job, a corrupt record, a terminal job and bad members
    await worker._frontier._client.zadd(RUNNABLE_KEY, {"acme:gone": 1})
    await worker._frontier._client.set(job_key("acme", "bad"), "not json")
    await worker._frontier._client.zadd(RUNNABLE_KEY, {"acme:bad": 1})
    svc = CrawlJobService()
    svc._client = redis
    with patch("src.crawl.job_service.check_fetch_uri", new=_allow_guard):
        record = await svc.submit_job("acme", _req())
    raw_state = await redis.get(job_key("acme", record.job_id))
    assert raw_state is not None
    await worker._frontier._client.set(
        job_key("acme", record.job_id),
        JobRecord.model_validate_json(raw_state).model_copy(update={"state": "succeeded"}).model_dump_json(),
    )
    await worker._frontier._client.zadd(RUNNABLE_KEY, {"no-colon": 1, ":empty": 1})

    # when
    assert await worker.run_once() is False

    # then every dead member is gone
    assert await worker._frontier.list_runnable() == []


async def test_drain_member_survives_job_read_error(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a client whose reads fail
    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._client, "get", boom)
    await worker._frontier._client.zadd(RUNNABLE_KEY, {"acme:x": 1})

    # when / then no raise and the member stays for the next sweep
    assert await worker._drain_member("acme:x") is False
    assert await worker._frontier.list_runnable() == ["acme:x"]


async def test_try_domain_survives_claim_error(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a frontier whose claims fail
    _, record = await _submit(redis, ["https://example.com/"])

    async def boom(**kwargs: Any) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._frontier, "claim", boom)

    # when / then no raise
    assert await worker.run_once() is False


async def test_finish_error_is_logged(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a claimed page and a frontier whose finish fails
    _, record = await _submit(redis, ["https://example.com/"])
    assert await worker.run_once() is True

    async def boom(**kwargs: Any) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._frontier, "finish", boom)
    await worker._finish(
        "acme",
        record.job_id,
        "m",
        record,
        "example.com",
        "0\thttps://example.com/",
        outcome="ok",
        page_line="{}",
        links=[],
        skipped=0,
    )


async def test_finalize_on_vanished_job_drops_caches(worker: WorkerHarness) -> None:
    # given seeded caches for a job that no longer exists
    worker._seeded.add(("gone", "https://example.com:443"))

    # when / then no raise
    await worker._finalize("acme", "gone", "acme:gone")
    assert ("gone", "https://example.com:443") not in worker._seeded


async def test_finalize_failure_is_logged_and_still_drops_caches(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a job whose frontier keys cannot be deleted
    _, record = await _submit(redis, ["https://example.com/"])
    worker._seeded.add((record.job_id, "https://example.com:443"))

    async def explode(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("redis down")

    monkeypatch.setattr(worker._frontier, "delete_frontier", explode)

    # when / then no raise
    await worker._finalize("acme", record.job_id, f"acme:{record.job_id}")
    assert (record.job_id, "https://example.com:443") not in worker._seeded


async def test_sitemap_entry_that_cannot_be_parsed_is_not_followed(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given a job and a sitemap entry with a broken address
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True)

    # when / then
    assert worker._follows(record, "https://[broken/page", 1) is False


async def test_process_claim_error_finishes_failed(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a first job that leaves recrawl state, then a probe that explodes
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)

    async def boom(url: str, **kwargs: Any) -> ConditionalProbe:
        raise RuntimeError("down")

    worker._probe = boom
    _, record = await _submit(redis, ["https://example.com/"])

    # when
    assert await worker.run_once() is True

    # then the page counts as failed and the job with no page read ends failed
    stored = await _stored(redis, record.job_id)
    assert stored.counts.failed == 1
    assert stored.state == "failed"


async def test_extract_failure_modes(worker: WorkerHarness, redis: FakeRedis, reader: FakeReader) -> None:
    # given pages with failing reads
    reader.pages["https://example.com/error-status"] = {"content": "", "links": {}, "status": "error"}
    reader.pages["https://example.com/no-content"] = {"links": {}, "status": "success"}
    reader.pages["https://example.com/bad-links"] = {
        "content": "x",
        "links": {"a": 1, "b": "https://example.com/ok"},
        "status": "success",
    }

    class BoomReader(FakeReader):
        async def read_linked_page(
            self,
            url: str,
            link_filter: str | None = None,
            heavy_mode: bool = False,
            profile: str | None = None,
            output_format: OutputFormat | None = None,
            tier: TierName | None = None,
            *,
            allow_human_tier: bool = True,
            use_read_cache: bool = True,
        ) -> PageResult:
            if "boom" in url:
                raise RuntimeError("down")
            return await super().read_linked_page(url, link_filter, heavy_mode, profile, output_format, tier)

    worker._reader = BoomReader(reader.pages)
    _, record = await _submit(
        redis,
        [
            "https://example.com/error-status",
            "https://example.com/boom",
            "https://example.com/no-content",
            "https://example.com/bad-links",
        ],
    )

    # when
    await _drain(worker)

    # then every bad read counts as failed and only good pages are fetched
    stored = await _stored(redis, record.job_id)
    assert stored.counts.failed == 3
    assert stored.counts.fetched == 2


def _novnc_only_strategies() -> dict[str, Any]:
    strategies: dict[str, Any] = {}
    for name in TIER_ORDER:
        winner = name == "6-novnc"
        stub = MagicMock()
        stub.get_html = AsyncMock(return_value=_NOVNC_ONLY_HTML if winner else "")
        stub.screenshot_page = AsyncMock(return_value=(_NOVNC_ONLY_HTML, b"\x89PNG") if winner else None)
        strategies[name] = stub
    return strategies


_NOVNC_ONLY_HTML = (
    "<html><head><title>Article</title></head><body><article><p>"
    "This is a genuine paragraph of article content with more than ten words in it. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    "</p><table><tr><th>Product name</th><th>Quarterly revenue</th></tr>"
    "<tr><td>Red Widget</td><td>Nineteen thousand dollars in the first quarter</td></tr></table>"
    "</article></body></html>"
)


@pytest.mark.parametrize("output_format", ["structured", "schema", "tables", "screenshot"])
async def test_formatted_crawl_read_never_reaches_the_human_tier(
    redis: FakeRedis,
    results: FakeResults,
    monkeypatch: pytest.MonkeyPatch,
    output_format: OutputFormat,
) -> None:
    # given a crawl whose formatted read finds content only at 6-novnc
    stubs = _novnc_only_strategies()
    crawl = _make_worker(redis, FakeReader(), results, monkeypatch)
    crawl._reader = WebReader()
    schema = {"type": "object"} if output_format == "schema" else None
    _, record = await _submit(
        redis, ["https://example.com/"], output_format=output_format, extraction_schema=schema
    )

    # when
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
    ):
        await _drain(crawl)

    # then no human-help window was opened and the page counts as failed
    stubs["6-novnc"].get_html.assert_not_awaited()
    stubs["6-novnc"].screenshot_page.assert_not_awaited()
    stored = await _stored(redis, record.job_id)
    assert stored.counts.failed == 1
    assert stored.counts.fetched == 0


_FORMATTED_PAGE_HTML = (
    "<html><head><title>Report</title></head><body><article><p>"
    "This quarterly report explains how the red widget sold in every region during the year. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    '</p><a href="/next">next report</a>'
    "<table><tr><th>Product name</th><th>Quarterly revenue</th></tr>"
    "<tr><td>Red Widget</td><td>Nineteen thousand dollars in the first quarter</td></tr></table>"
    "</article></body></html>"
)


def _expected_formatted_content(output_format: OutputFormat) -> str:
    if output_format == "structured":
        content = extract_structured(_FORMATTED_PAGE_HTML)["content"]
        assert isinstance(content, str)
        return content
    tables = extract_tables(_FORMATTED_PAGE_HTML)
    return " ".join(cell for table in tables for row in table for cell in row)


@pytest.mark.parametrize("output_format", ["structured", "tables"])
async def test_formatted_crawl_reads_the_page_once_and_stores_content_and_validators_of_that_read(
    redis: FakeRedis, results: FakeResults, monkeypatch: pytest.MonkeyPatch, output_format: OutputFormat
) -> None:
    # given a formatted crawl and a tier whose one answer carried ETag and Last-Modified
    reader = WebReader()
    tier_reads: list[str] = []
    page = FetchedHtml(_FORMATTED_PAGE_HTML, {"etag": '"f1"', "last-modified": "Fri"})

    async def tier_html(name: str, strategy: Any, url: str) -> str:
        tier_reads.append(name)
        return page

    monkeypatch.setattr(reader, "_novnc_or_tier_html", tier_html)
    monkeypatch.setattr(reader.validator, "validate", lambda text: True)
    monkeypatch.setattr("src.reader.web_reader.tier_memory.get", AsyncMock(return_value=None))
    crawl = _make_worker(redis, reader, results, monkeypatch)
    _, record = await _submit(redis, ["https://example.com/"], output_format=output_format)

    # when
    assert await crawl.run_once() is True

    # then one tier read served the content, the links and the validators
    assert tier_reads == ["1-beautifulsoup"]
    key = page_object_key("acme", record.job_id, "https://example.com/", output_format)
    assert results.text[key] == _expected_formatted_content(output_format)
    entry = await RecrawlStore(redis).read(
        "acme", recrawl_scope(_req(output_format=output_format)), "https://example.com/"
    )
    assert entry is not None
    assert (entry["etag"], entry["last_modified"]) == ('"f1"', "Fri")
    assert entry["links"] == ["https://example.com/next"]


async def test_screenshot_crawl_takes_links_and_validators_from_the_one_capture(
    redis: FakeRedis, results: FakeResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a screenshot crawl whose first browser capture carried ETag and Last-Modified
    page = FetchedHtml(_FORMATTED_PAGE_HTML, {"etag": '"s1"', "last-modified": "Sat"})
    stubs: dict[str, Any] = {}
    for name in TIER_ORDER:
        stub = MagicMock()
        stub.get_html = AsyncMock(return_value=_FORMATTED_PAGE_HTML)
        stub.screenshot_page = AsyncMock(return_value=(page, b"\x89PNG"))
        stubs[name] = stub
    reader = WebReader()
    monkeypatch.setattr(reader, "_build_strategies", lambda profile=None: stubs)
    monkeypatch.setattr("src.reader.web_reader.tier_memory.get", AsyncMock(return_value=None))
    crawl = _make_worker(redis, reader, results, monkeypatch)
    _, record = await _submit(redis, ["https://example.com/"], output_format="screenshot")

    # when
    assert await crawl.run_once() is True

    # then the one capture served the stored image, the links and the validators
    captures = [stub.screenshot_page.await_count for stub in stubs.values()]
    assert captures == [1] + [0] * (len(TIER_ORDER) - 1)
    assert all(stub.get_html.await_count == 0 for stub in stubs.values())
    key = page_object_key("acme", record.job_id, "https://example.com/", "screenshot")
    assert results.text[key] == base64.b64encode(b"\x89PNG").decode("ascii")
    entry = await RecrawlStore(redis).read(
        "acme", recrawl_scope(_req(output_format="screenshot")), "https://example.com/"
    )
    assert entry is not None
    assert (entry["etag"], entry["last_modified"]) == ('"s1"', "Sat")
    assert entry["links"] == ["https://example.com/next"]


async def test_extract_format_modes(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a schema crawl and stubbed formatted reads
    async def schema_ok(
        url: str,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        extraction_schema: dict[str, Any] | None = None,
        *,
        allow_human_tier: bool = True,
        use_read_cache: bool = True,
    ) -> PageResult:
        if "plain" in url:
            return PageResult({"content": "formatted body", "status": "success"})
        if "wrapped" in url:
            return PageResult({"content": {"name": "Red Widget"}, "status": "success"})
        return PageResult({"title": "t", "status": "success"})

    async def schema_bad(
        url: str,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        extraction_schema: dict[str, Any] | None = None,
        *,
        allow_human_tier: bool = True,
        use_read_cache: bool = True,
    ) -> PageResult:
        if "raises" in url:
            raise RuntimeError("down")
        return PageResult({"status": "error"})

    monkeypatch.setattr(reader, "read_page", schema_ok)
    _, record = await _submit(
        redis,
        ["https://example.com/plain", "https://example.com/wrapped", "https://example.com/dump"],
        output_format="schema",
        extraction_schema={"type": "object"},
    )

    # when
    await _drain(worker)

    # then all three pages are stored: flat content, wrapped content, and a dump
    stored = await _stored(redis, record.job_id)
    assert stored.counts.fetched == 3

    # when formatted reads fail
    monkeypatch.setattr(reader, "read_page", schema_bad)
    _, other = await _submit(
        redis,
        ["https://example.com/raises", "https://example.com/err"],
        output_format="schema",
        extraction_schema={"type": "object"},
    )
    await _drain(worker)
    stored_other = await _stored(redis, other.job_id)
    assert stored_other.counts.failed == 2


async def test_domain_delay_variants(worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    record = _req(respect_robots=True)

    class Rules:
        def __init__(self, delay: float | None) -> None:
            self._delay = delay

        def crawl_delay(self, agent: str) -> float | None:
            return self._delay

    # when respect is off the floor applies without any fetch
    robots_fetch = AsyncMock(return_value=RobotsFetch(200, "User-agent: *\nCrawl-delay: 30\n"))
    worker._robots._fetch = robots_fetch
    ignoring = JobRecord(job_id="j", tenant_id="a", request=_req(respect_robots=False))
    assert await worker._domain_delay_ms(ignoring, "https://example.com/") == int(
        settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000
    )
    robots_fetch.assert_not_awaited()

    # when rules are missing or carry no delay the floor applies
    async def none_rules(job_id: str, url: str, *, profile: str | None) -> Any:
        return None

    monkeypatch.setattr(worker._robots, "rules", none_rules)
    job = JobRecord(job_id="j", tenant_id="a", request=record)
    got = await worker._domain_delay_ms(job, "https://example.com/")
    assert got == int(settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000)

    async def boom(job_id: str, url: str, *, profile: str | None) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._robots, "rules", boom)
    got = await worker._domain_delay_ms(job, "https://example.com/")
    assert got == int(settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000)

    async def no_delay(job_id: str, url: str, *, profile: str | None) -> Any:
        return Rules(None)

    monkeypatch.setattr(worker._robots, "rules", no_delay)
    got = await worker._domain_delay_ms(job, "https://example.com/")
    assert got == int(settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000)

    async def slow(job_id: str, url: str, *, profile: str | None) -> Any:
        return Rules(30.0)

    monkeypatch.setattr(worker._robots, "rules", slow)
    assert await worker._domain_delay_ms(job, "https://example.com/") == 30000


async def test_write_recrawl_error_is_logged(worker: WorkerHarness, redis: FakeRedis) -> None:
    # given a recrawl store whose writes fail
    from src.crawl.result_store import RecrawlStore

    class BoomRecrawl(RecrawlStore):
        async def write(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError("down")

    worker._recrawl = BoomRecrawl(redis)
    _, record = await _submit(redis, ["https://example.com/"])

    # when / then no raise and the page still counts as fetched
    await _drain(worker)
    stored = await _stored(redis, record.job_id)
    assert stored.counts.fetched == 1


async def test_write_recrawl_error_logs_no_query_of_the_page_or_the_exception(
    worker: WorkerHarness, redis: FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    # given a recrawl store whose failure names the signed page address
    from src.crawl.result_store import RecrawlStore

    url = "https://example.com/?X-Amz-Signature=secret"

    class BoomRecrawl(RecrawlStore):
        async def write(self, *args: Any, **kwargs: Any) -> str:
            raise RuntimeError(f"down for {url}")

    worker._recrawl = BoomRecrawl(redis)
    await _submit(redis, [url])

    # when
    await _drain(worker)

    # then
    messages = [record.getMessage() for record in caplog.records]
    lines = [message for message in messages if "recrawl write failed" in message]
    assert lines
    assert all("X-Amz-Signature" not in line for line in lines)
    assert "https://example.com/" in lines[0]


async def test_corrupt_recrawl_entry_reads_unconditionally(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a corrupt recrawl entry with a non-string key and validators
    from src.crawl.result_store import RecrawlStore, recrawl_scope

    _, record = await _submit(redis, ["https://example.com/"])
    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(_req())
    await recrawl.write(
        "acme",
        scope,
        "https://example.com/",
        {"hash": "x", "page_key": 5, "etag": 6, "last_modified": 7},
    )
    probe = worker.probe_mock
    calls_before = probe.await_count

    # when
    await _drain(worker)

    # then the entry is ignored and the page is written new
    assert probe.await_count == calls_before
    stored = await _stored(redis, record.job_id)
    assert stored.counts.fetched == 1


async def test_filter_link_modes() -> None:
    # given
    request = _req(
        seeds=["https://example.com/"],
        include_patterns=["/guide/*"],
        exclude_patterns=["*/secret/*"],
        max_depth=1,
    )
    record = JobRecord(job_id="j", tenant_id="acme", request=request)
    worker = Worker.__new__(Worker)

    # when / then
    assert worker._filter_link(record, "https://example.com/guide/a", 1) is not None
    assert worker._filter_link(record, "https://example.com/other", 1) is None
    assert worker._filter_link(record, "https://example.com/guide/secret/x", 1) is None
    assert worker._filter_link(record, "https://other.com/guide/a", 1) is None
    assert worker._filter_link(record, "https://example.com/guide/a", 2) is None


async def test_links_for_skips_unparseable_url(worker: WorkerHarness) -> None:
    # given a page linking an unparseable URL
    record = JobRecord(job_id="j", tenant_id="acme", request=_req(seeds=["https://e.com/"]))

    # when / then it is dropped without a guard call
    kept, skipped = await worker._links_for(record, ["http://[::1/"], 0)
    assert (kept, skipped) == ([], 0)


async def test_a_link_whose_host_cannot_be_encoded_is_dropped_and_counted_by_the_real_guard(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a link with a host label longer than the name system allows
    monkeypatch.setattr(worker_module, "check_fetch_uri", check_fetch_uri)
    record = JobRecord(job_id="j", tenant_id="acme", request=_req(same_domain_only=False))
    link = "https://" + "a" * 64 + ".example.com/x"

    # when
    kept, skipped = await worker._links_for(record, [link], 0)

    # then the guard refusal reaches the handler instead of raising a UnicodeError
    assert (kept, skipped) == ([], 1)


async def test_same_domain_off_keeps_foreign_links() -> None:
    # given
    record = JobRecord(
        job_id="j",
        tenant_id="acme",
        request=_req(seeds=["https://example.com/"], same_domain_only=False),
    )
    worker = Worker.__new__(Worker)

    # when / then
    assert worker._filter_link(record, "https://other.com/x", 1) == "https://other.com/x"


def test_seed_domains_groups_by_registrable_domain() -> None:
    assert seed_domains(_req(seeds=["https://a.example.com/", "https://example.org/"])) == [
        "example.com",
        "example.org",
    ]


async def test_is_disallowed_error_disallows(worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch) -> None:
    # given rules that fail
    async def boom(job_id: str, url: str, *, profile: str | None) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._robots, "rules", boom)
    record = JobRecord(job_id="j", tenant_id="a", request=_req(seeds=["https://e.com/"], respect_robots=True))

    # when / then
    assert await worker._is_disallowed(record, "https://e.com/x") is True


async def test_second_page_same_domain_skips_reseed(worker: WorkerHarness, redis: FakeRedis) -> None:
    # given a sitemap counted once
    fetches: list[str] = []

    async def fetch(url: str) -> str:
        fetches.append(url)
        if url.endswith("/robots.txt"):
            return "User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
        if url.endswith("sitemap.xml"):
            return "<urlset><url><loc>https://example.com/s</loc></url></urlset>"
        return ""

    _serve_robots(worker, fetch)
    await _submit(redis, ["https://example.com/", "https://example.com/b"], respect_robots=True)

    # when
    await _drain(worker)

    # then the sitemap document is fetched once for the whole job
    assert fetches.count("https://example.com/sitemap.xml") == 1


async def test_queue_new_skips_unparseable_filtered_and_unsafe(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given
    _, record = await _submit(redis, ["https://example.com/"], include_patterns=["/keep/*"])

    # when sitemap URLs mix an unparseable, an unsafe, a filtered and a good URL
    skipped = await worker._queue_new(
        "acme",
        record.job_id,
        record,
        ["http://[::1/", "http://127.0.0.1/x", "https://example.com/drop", "https://example.com/keep/a"],
        1,
    )

    # then only the unsafe one is counted and only the good one is queued
    assert skipped == 1
    from src.crawl.keys import queue_key as _q

    assert await redis.lrange(_q("acme", record.job_id, "example.com"), 0, -1) == [
        "0\thttps://example.com/",
        "1\thttps://example.com/keep/a",
    ]


async def test_queue_new_empty_returns_skipped(worker: WorkerHarness, redis: FakeRedis) -> None:
    # given
    _, record = await _submit(redis, ["https://example.com/"])

    # when / then no write happens
    assert await worker._queue_new("acme", record.job_id, record, [], 1) == 0


async def test_seed_sitemaps_survives_write_error(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a sitemap with one good URL and a failing frontier write
    async def fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
        return "<urlset><url><loc>https://example.com/s</loc></url></urlset>"

    _serve_robots(worker, fetch)
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True)

    async def boom(**kwargs: Any) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._frontier, "add_urls", boom)

    # when / then no raise and the unsafe count is zero
    assert await worker._seed_sitemaps("acme", record.job_id, record, "https://example.com/", 0) == 0


async def test_seed_sitemaps_survives_fetch_error(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given sitemap seeding that fails
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True)

    async def boom(job_id: str, url: str, **kwargs: Any) -> list[str]:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._robots, "sitemap_seed_urls", boom)

    # when / then no raise
    assert await worker._seed_sitemaps("acme", record.job_id, record, "https://example.com/", 0) == 0


async def test_try_domain_removes_member_on_gone_claim(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a listed member whose record vanished after listing
    _, record = await _submit(redis, ["https://example.com/"])

    async def stale_load(tenant_id: str, job_id: str) -> JobRecord | None:
        return record

    monkeypatch.setattr(worker, "_load_record", stale_load)
    await redis.delete(job_key("acme", record.job_id))

    # when / then the claim answers gone and the member is removed
    assert await worker.run_once() is False
    assert await worker._frontier.list_runnable() == []


async def test_try_domain_removes_member_on_cancel_race(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a record loaded as running but cancelled before the claim
    svc, record = await _submit(redis, ["https://example.com/"])

    async def stale_load(tenant_id: str, job_id: str) -> JobRecord | None:
        return record

    monkeypatch.setattr(worker, "_load_record", stale_load)
    await svc.cancel_job("acme", record.job_id)
    # the cancel removes the member; another instance lists it just before
    await redis.zadd(RUNNABLE_KEY, {f"acme:{record.job_id}": 1})

    # when / then the idle answer removes the member
    assert await worker.run_once() is False
    assert await worker._frontier.list_runnable() == []


@pytest.mark.parametrize("status", ["capped", "budget", "wait", "empty", "idle"])
async def test_try_domain_backs_off_without_progress(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch, status: str
) -> None:
    # given a claim that answers anything but claimed
    _, record = await _submit(redis, ["https://example.com/"])

    async def answer(**kwargs: Any) -> list[str]:
        return [status]

    monkeypatch.setattr(worker._frontier, "claim", answer)

    # when / then no page is read and the member stays for the next sweep
    assert await worker.run_once() is False
    assert await worker._frontier.list_runnable() == [f"acme:{record.job_id}"]


async def test_read_without_links_key(worker: WorkerHarness, redis: FakeRedis, reader: FakeReader) -> None:
    # given a page without a links map
    reader.pages["https://example.com/"] = {"content": "hello", "status": "success"}
    _, record = await _submit(redis, ["https://example.com/"])

    # when / then the page is still stored
    await _drain(worker)
    stored = await _stored(redis, record.job_id)
    assert stored.counts.fetched == 1


async def test_str_validators_survive_recrawl(worker: WorkerHarness, redis: FakeRedis) -> None:
    # given a prior entry with string validators
    from src.crawl.result_store import RecrawlStore, recrawl_scope

    _, record = await _submit(redis, ["https://example.com/"])
    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(_req())
    seen: dict[str, Any] = {}

    async def capture(url: str, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return ConditionalProbe(200, None, None)

    worker._probe = capture
    await _drain(worker)

    # when the next job recrawls with etag-carrying state
    entry = await recrawl.read("acme", scope, "https://example.com/")
    assert entry is not None
    entry["etag"] = '"abc"'
    entry["last_modified"] = "Wed"
    await recrawl.write("acme", scope, "https://example.com/", entry)
    _, second = await _submit(redis, ["https://example.com/"])
    await _drain(worker)

    # then the probe carries the stored validators
    assert seen == {"etag": '"abc"', "last_modified": "Wed", "profile": None}
    stored = await _stored(redis, second.job_id)
    assert stored.counts.unchanged == 1


async def test_second_copy_miss_writes_new_file(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a source that vanishes after a non-304 probe
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    results.exists_mode = "vanished"
    results.copy_mode = "vanished"
    probe = worker.probe_mock
    probe.return_value = ConditionalProbe(200, None, None)
    _, second = await _submit(redis, ["https://example.com/"])

    # when / then the page is written new
    await _drain(worker)
    stored = await _stored(redis, second.job_id)
    assert stored.counts.fetched == 1
    assert stored.counts.unchanged == 0


async def test_fresh_write_captures_the_validators_of_the_read(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given the read answers validators on a fresh crawl
    from src.crawl.result_store import RecrawlStore, recrawl_scope

    reader.pages["https://example.com/"] = {"content": "hello", "links": {}, "status": "success"}
    reader.headers["https://example.com/"] = {"etag": '"h"', "last-modified": "Wed"}
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)

    # then the recrawl entry carries them
    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(_req())
    entry = await recrawl.read("acme", scope, "https://example.com/")
    assert entry is not None
    assert entry["etag"] == '"h"'
    assert entry["last_modified"] == "Wed"

    # and the next job's probe sends them
    seen: dict[str, Any] = {}

    async def capture(url: str, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return ConditionalProbe(304, '"h"', "Wed")

    worker._probe = capture
    _, second = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    assert seen == {"etag": '"h"', "last_modified": "Wed", "profile": None}
    stored = await _stored(redis, second.job_id)
    assert stored.counts.unchanged == 1


def _refuse_crawl_fetches(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    sessions = MagicMock(side_effect=AssertionError("the crawl fetcher opened a session"))
    monkeypatch.setattr("src.crawl.fetcher.check_fetch_uri", _allow_guard)
    monkeypatch.setattr("src.crawl.fetcher.requests.AsyncSession", sessions)
    return sessions


async def test_first_crawl_stores_the_validators_of_the_read_and_sends_no_head(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a page whose GET answer carried ETag and Last-Modified
    reader.pages["https://example.com/"] = {"content": "hello", "links": {}, "status": "success"}
    reader.headers["https://example.com/"] = {
        "etag": '"r1"',
        "last-modified": "Thu, 01 Oct 2026 10:00:00 GMT",
    }
    sessions = _refuse_crawl_fetches(monkeypatch)
    _, record = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then no second request went to the site and the recrawl state holds the read's validators
    entry = await RecrawlStore(redis).read("acme", recrawl_scope(_req()), "https://example.com/")
    assert entry is not None
    assert (entry["etag"], entry["last_modified"]) == ('"r1"', "Thu, 01 Oct 2026 10:00:00 GMT")
    sessions.assert_not_called()
    assert (await _stored(redis, record.job_id)).counts.fetched == 1


@pytest.mark.parametrize("output_format", ["text", "structured"])
async def test_crawl_read_skips_a_read_cache_another_read_filled_and_leaves_nothing_in_it(
    redis: FakeRedis, results: FakeResults, monkeypatch: pytest.MonkeyPatch, output_format: OutputFormat
) -> None:
    # given a read cache that an earlier read of another caller filled for the seed
    url = "https://example.com/"
    reader = WebReader()
    tier_reads = 0
    html = FetchedHtml("<html><body><p>" + "fresh words " * 20 + "</p></body></html>", {})

    async def tier_read(name: Any, strategy: Any, url_: Any, *, escalate_failures: bool = False) -> str:
        nonlocal tier_reads
        tier_reads += 1
        return html

    async def tier_html(name: Any, strategy: Any, url_: Any) -> str:
        nonlocal tier_reads
        tier_reads += 1
        return html

    stale = {"content": "cached words of another tenant", "links": {}, "status": "success", "mode": "1"}
    prefilled = {
        _cache_key(url, False, True, None, None): (stale, float("inf")),
        _cache_key(url, False, False, None, output_format, None, ""): (stale, float("inf")),
    }
    reader._memory_cache.update(prefilled)
    monkeypatch.setattr(reader, "_execute_html_strategy", tier_read)
    monkeypatch.setattr(reader, "_novnc_or_tier_html", tier_html)
    monkeypatch.setattr(reader.validator, "validate", lambda _text: True)
    worker = _make_worker(redis, reader, results, monkeypatch)
    _, record = await _submit(redis, [url], output_format=output_format)

    # when
    await _drain(worker)

    # then the crawl fetched the page itself, stored what it fetched and wrote nothing to the cache
    stored_page = results.text[page_object_key("acme", record.job_id, url, output_format)]
    assert tier_reads == 1
    assert "fresh words" in stored_page
    assert "another tenant" not in stored_page
    assert reader._memory_cache == prefilled
    assert (await _stored(redis, record.job_id)).counts.fetched == 1


async def test_recrawl_of_a_changed_page_stores_the_validators_of_the_read_not_of_the_probe(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a stored page with validators and a recrawl whose conditional GET answers 200 with new ones
    url = "https://example.com/"
    scope = recrawl_scope(_req())
    await _submit(redis, [url])
    await _drain(worker)
    recrawl = RecrawlStore(redis)
    entry = await recrawl.read("acme", scope, url)
    assert entry is not None
    entry["etag"] = '"p1"'
    entry["last_modified"] = "Mon"
    await recrawl.write("acme", scope, url, entry)
    worker.probe_mock.return_value = ConditionalProbe(200, '"p2"', "Tue")
    reader.pages[url] = {"content": "changed", "links": {}, "status": "success"}
    reader.headers[url] = {"etag": '"r2"'}
    _, second = await _submit(redis, [url])

    # when
    await _drain(worker)

    # then the probe sent the stored validators and the read that produced the content gave the stored ones
    assert worker.probe_mock.await_args is not None
    assert worker.probe_mock.await_args.kwargs == {"etag": '"p1"', "last_modified": "Mon", "profile": None}
    stored_entry = await recrawl.read("acme", scope, url)
    assert stored_entry is not None
    assert (stored_entry["etag"], stored_entry["last_modified"]) == ('"r2"', None)
    assert (await _stored(redis, second.job_id)).counts.fetched == 1


async def test_recrawl_whose_probe_failed_stores_the_validators_of_the_read(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a stored page and a recrawl whose conditional GET got no answer
    url = "https://example.com/"
    await _submit(redis, [url])
    await _drain(worker)
    worker.probe_mock.return_value = ConditionalProbe(None, None, None)
    reader.pages[url] = {"content": "changed", "links": {}, "status": "success"}
    reader.headers[url] = {"etag": '"r3"', "last-modified": "Wed"}
    sessions = _refuse_crawl_fetches(monkeypatch)
    await _submit(redis, [url])

    # when
    await _drain(worker)

    # then
    entry = await RecrawlStore(redis).read("acme", recrawl_scope(_req()), url)
    assert entry is not None
    assert (entry["etag"], entry["last_modified"]) == ('"r3"', "Wed")
    sessions.assert_not_called()


async def test_recrawl_probe_carries_the_profile_of_the_job(worker: WorkerHarness, redis: FakeRedis) -> None:
    # given a profile crawl that left recrawl state
    await _submit(redis, ["https://example.com/"], profile="alice")
    await _drain(worker)
    worker.probe_mock.return_value = ConditionalProbe(304, None, None)

    # when the same profile crawl recrawls
    await _submit(redis, ["https://example.com/"], profile="alice")
    await _drain(worker)

    # then the conditional request is sent for that profile
    assert worker.probe_mock.await_args is not None
    assert worker.probe_mock.await_args.kwargs["profile"] == "alice"


async def test_304_after_a_legacy_entry_without_links_stores_the_validators_of_the_read(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a legacy entry with validators and no stored links, and a 304 that names only an ETag
    await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(_req())
    entry = await recrawl.read("acme", scope, "https://example.com/")
    assert entry is not None
    entry.pop("links", None)
    entry["etag"] = '"v0"'
    entry["last_modified"] = "Mon"
    await recrawl.write("acme", scope, "https://example.com/", entry)
    worker.probe_mock.return_value = ConditionalProbe(304, '"v1"', None)
    reader.headers["https://example.com/"] = {"etag": '"r1"', "last-modified": "Tue"}
    await _submit(redis, ["https://example.com/"])

    # when the page falls back to a full read
    await _drain(worker)

    # then the validators of that read are stored, not the 304's ETag without a Last-Modified
    assert await _stored_validators(redis) == ('"r1"', "Tue")


async def test_recrawl_304_requeues_seed_links(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a first crawl where the seed links a child page
    reader.pages["https://example.com/"] = {
        "content": "home",
        "links": {1: "https://example.com/child"},
        "status": "success",
    }
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    stored_first = await _stored(redis, first.job_id)
    assert stored_first.counts.fetched == 2
    worker.probe_mock.return_value = ConditionalProbe(304, '"v1"', None)
    _, second = await _submit(redis, ["https://example.com/"])

    # when the identical scope recrawls with 304 on every page
    await _drain(worker)

    # then the seed copy-forward requeues the child instead of ending discovery
    stored = await _stored(redis, second.job_id)
    assert stored.counts.unchanged == 2
    assert stored.counts.fetched == 0


async def test_recrawl_legacy_entry_without_links_falls_back_to_fetch(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a first crawl and a legacy recrawl entry without stored links
    from src.crawl.result_store import RecrawlStore, recrawl_scope

    reader.pages["https://example.com/"] = {
        "content": "home",
        "links": {1: "https://example.com/child"},
        "status": "success",
    }
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(_req())
    entry = await recrawl.read("acme", scope, "https://example.com/")
    assert entry is not None
    entry.pop("links", None)
    await recrawl.write("acme", scope, "https://example.com/", entry)
    copies_before = len(results.copy_calls)
    worker.probe_mock.return_value = ConditionalProbe(304, '"v1"', None)
    _, second = await _submit(redis, ["https://example.com/"])

    # when the seed recrawls with a 304 but no stored links
    await _drain(worker)

    # then the seed falls back to a full fetch yet still discovers the child
    stored = await _stored(redis, second.job_id)
    assert stored.counts.fetched == 1
    assert stored.counts.unchanged == 1
    assert len(results.copy_calls) == copies_before + 1


async def test_budget_with_non_empty_frontier_finalizes_instead_of_stalling(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given three seeds with a page budget of one
    _, record = await _submit(
        redis,
        [
            "https://example.com/",
            "https://example.com/a",
            "https://example.com/b",
        ],
        page_budget=1,
    )

    # when the worker drains the job
    await _drain(worker, limit=10)

    # then the job reaches succeeded instead of stalling in running
    stored = await _stored(redis, record.job_id)
    assert stored.state == "succeeded"
    assert stored.counts.fetched == 1
    assert await worker._frontier.list_runnable() == []
    assert len(results.index_writes) == 1


async def test_budget_succeeded_claim_finalizes_job(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a job already at its budget with queued URLs and no claims
    _, record = await _submit(
        redis,
        ["https://example.com/", "https://example.com/a"],
        page_budget=1,
    )
    raw = await redis.get(job_key("acme", record.job_id))
    assert raw is not None
    payload: dict[str, Any] = json.loads(raw)
    payload["counts"]["fetched"] = 1
    await redis.set(job_key("acme", record.job_id), json.dumps(payload))

    # when the worker sweeps and the claim finds the budget bound
    assert await worker.run_once() is False

    # then the job finalizes instead of stalling in running
    stored = await _stored(redis, record.job_id)
    assert stored.state == "succeeded"
    assert await worker._frontier.list_runnable() == []
    assert len(results.index_writes) == 1


async def test_every_page_failed_ends_job_failed_without_index(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a job whose only page cannot be read
    reader.pages["https://example.com/"] = {"content": "", "links": {}, "status": "error"}
    _, record = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the job ends failed, writes no index and drops its frontier keys
    stored = await _stored(redis, record.job_id)
    assert stored.state == "failed"
    assert stored.error == ALL_PAGES_FAILED_ERROR
    assert stored.pages_ndjson_key is None
    assert results.index_writes == []
    assert [key async for key in redis.scan_iter(match="crawl_seen:*")] == []
    assert [key async for key in redis.scan_iter(match="crawl_queue:*")] == []
    assert await worker._frontier.list_runnable() == []


async def test_robots_is_read_per_origin(worker: WorkerHarness, redis: FakeRedis, reader: FakeReader) -> None:
    # given two origins of one registrable domain with different robots.txt rules
    fetched: list[str] = []

    async def fetch(url: str) -> str:
        fetched.append(url)
        if url == "http://docs.example.com:8080/robots.txt":
            return "User-agent: *\nDisallow: /a\n"
        return ""

    _serve_robots(worker, fetch)
    _, record = await _submit(
        redis, ["http://docs.example.com:8080/a", "https://example.com/a"], respect_robots=True
    )

    # when
    await _drain(worker)

    # then each origin's own file decides for its pages
    assert "http://docs.example.com:8080/robots.txt" in fetched
    assert "https://example.com/robots.txt" in fetched
    assert "http://docs.example.com:8080/a" not in reader.calls
    assert "https://example.com/a" in reader.calls


async def test_sitemaps_are_seeded_per_origin(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a sitemap named only by the robots.txt of the docs origin
    async def fetch(url: str) -> str:
        if url == "https://docs.example.com/robots.txt":
            return "User-agent: *\nSitemap: https://docs.example.com/sitemap.xml\n"
        if url == "https://docs.example.com/sitemap.xml":
            return "<urlset><url><loc>https://docs.example.com/from-sitemap</loc></url></urlset>"
        return ""

    _serve_robots(worker, fetch)
    await _submit(redis, ["https://docs.example.com/"], respect_robots=True)

    # when
    await _drain(worker)

    # then the docs origin's sitemap seeds the frontier
    assert "https://docs.example.com/from-sitemap" in reader.calls


async def test_crawl_delay_comes_from_the_claimed_url_origin(worker: WorkerHarness, redis: FakeRedis) -> None:
    # given a delay set only by the robots.txt of the slow origin
    async def fetch(url: str) -> str:
        if url == "https://slow.example.com/robots.txt":
            return "User-agent: *\nCrawl-delay: 7\n"
        return ""

    _serve_robots(worker, fetch)
    _, record = await _submit(
        redis, ["https://slow.example.com/x", "https://slow.example.com/y"], respect_robots=True
    )

    # when the first page is claimed
    assert await worker.run_once() is True

    # then the next fetch time carries the slow origin's delay
    value = await redis.get(next_fetch_key("acme", record.job_id, "example.com"))
    assert int(value or "0") >= NOW + 7000


async def test_delay_is_extended_when_the_claim_pops_another_origin(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a queue head that changes between the peek and the claim
    async def fetch(url: str) -> str:
        if url == "https://slow.example.com/robots.txt":
            return "User-agent: *\nCrawl-delay: 7\n"
        return ""

    _serve_robots(worker, fetch)
    _, record = await _submit(
        redis, ["https://slow.example.com/x", "https://slow.example.com/y"], respect_robots=True
    )

    async def stale_peek(key: str, index: int) -> str:
        return "0\thttps://fast.example.com/"

    monkeypatch.setattr(redis, "lindex", stale_peek)

    # when the claim pops the slow origin's URL
    assert await worker.run_once() is True

    # then the next fetch time still carries the slow origin's delay
    value = await redis.get(next_fetch_key("acme", record.job_id, "example.com"))
    assert int(value or "0") >= NOW + 7000


async def test_delay_is_kept_when_the_claimed_origin_asks_less(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a peeked origin with a long delay and a claimed origin with none
    async def fetch(url: str) -> str:
        if url == "https://slow.example.com/robots.txt":
            return "User-agent: *\nCrawl-delay: 7\n"
        return ""

    _serve_robots(worker, fetch)
    _, record = await _submit(
        redis, ["https://fast.example.com/x", "https://fast.example.com/y"], respect_robots=True
    )

    async def stale_peek(key: str, index: int) -> str:
        return "0\thttps://slow.example.com/"

    monkeypatch.setattr(redis, "lindex", stale_peek)

    # when the claim pops the fast origin's URL
    assert await worker.run_once() is True

    # then the longer delay set at the claim stays
    value = await redis.get(next_fetch_key("acme", record.job_id, "example.com"))
    assert int(value or "0") >= NOW + 7000


async def test_sitemap_collection_is_bounded_by_the_page_budget(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given a sitemap index naming five sitemaps of one page each and a budget of two
    fetched: list[str] = []

    async def fetch(url: str) -> str:
        fetched.append(url)
        if url.endswith("/robots.txt"):
            return "User-agent: *\nSitemap: https://example.com/index.xml\n"
        if url.endswith("/index.xml"):
            return (
                "<sitemapindex>"
                + "".join(f"<sitemap><loc>https://example.com/s{n}.xml</loc></sitemap>" for n in range(5))
                + "</sitemapindex>"
            )
        name = url.rsplit("/", 1)[1].removesuffix(".xml")
        return f"<urlset><url><loc>https://example.com/{name}</loc></url></urlset>"

    _serve_robots(worker, fetch)
    _, record = await _submit(redis, ["https://example.com/"], page_budget=2, respect_robots=True)

    # when the seed is read and seeds the sitemaps
    assert await worker.run_once() is True

    # then collection stops at the budget instead of reading every sitemap
    sitemap_documents = [url for url in fetched if url.endswith(".xml") and not url.endswith("index.xml")]
    assert len(sitemap_documents) == 2
    assert await redis.scard(seen_key("acme", record.job_id)) == 3


async def test_sitemap_bound_counts_only_urls_the_job_follows(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given a sitemap whose first entries fall outside the include pattern
    async def fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "User-agent: *\nSitemap: https://example.com/sitemap.xml\n"
        return (
            "<urlset>"
            "<url><loc>https://example.com/skip/1</loc></url>"
            "<url><loc>https://example.com/skip/2</loc></url>"
            "<url><loc>https://example.com/keep/1</loc></url>"
            "</urlset>"
        )

    _serve_robots(worker, fetch)
    _, record = await _submit(
        redis,
        ["https://example.com/"],
        include_patterns=["/", "/keep/*"],
        page_budget=2,
        respect_robots=True,
    )

    # when
    assert await worker.run_once() is True

    # then the followed entry is still collected
    assert await redis.sismember(seen_key("acme", record.job_id), "https://example.com/keep/1")


async def test_page_finished_after_cancel_writes_no_object_and_no_recrawl_state(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a page whose job is cancelled by another instance while it is read
    svc, record = await _submit(redis, ["https://example.com/"])

    class CancellingReader(FakeReader):
        async def read_linked_page(
            self,
            url: str,
            link_filter: str | None = None,
            heavy_mode: bool = False,
            profile: str | None = None,
            output_format: OutputFormat | None = None,
            tier: TierName | None = None,
            *,
            allow_human_tier: bool = True,
            use_read_cache: bool = True,
        ) -> PageResult:
            await svc.cancel_job("acme", record.job_id)
            return self.page_result(url, {"content": "late content", "links": {}, "status": "success"})

    worker._reader = CancellingReader()

    # when
    assert await worker.run_once() is True

    # then no page object and no recrawl hash were written
    assert results.text == {}
    assert [key async for key in redis.scan_iter(match="crawl_recrawl:*")] == []
    assert (await _stored(redis, record.job_id)).state == "cancelled"


async def test_unchanged_page_after_cancel_is_not_copied(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given an earlier job and a recrawl cancelled while its 304 probe runs
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    copies_before = len(results.copy_calls)
    svc, second = await _submit(redis, ["https://example.com/"])

    async def cancelling_probe(url: str, **kwargs: Any) -> ConditionalProbe:
        await svc.cancel_job("acme", second.job_id)
        return ConditionalProbe(304, '"v1"', None)

    worker._probe = cancelling_probe

    # when
    assert await worker.run_once() is True

    # then nothing is copied and the recrawl state still names the first job's file
    assert len(results.copy_calls) == copies_before
    entry = await RecrawlStore(redis).read("acme", recrawl_scope(_req()), "https://example.com/")
    assert entry is not None
    assert first.job_id in entry["page_key"]


@pytest.mark.parametrize(
    "changed",
    [
        {"exclude_patterns": ["/never/*"]},
        {"output_format": "structured"},
        {"profile": "work"},
    ],
)
async def test_recrawl_never_reuses_results_across_result_options(
    worker: WorkerHarness, redis: FakeRedis, changed: dict[str, Any]
) -> None:
    # given a completed job
    await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    probes_before = worker.probe_mock.await_count

    # when a job differing in an option that shapes the stored result runs
    _, second = await _submit(redis, ["https://example.com/"], **changed)
    await _drain(worker)

    # then it sends no conditional probe and writes its own page
    assert worker.probe_mock.await_count == probes_before
    stored = await _stored(redis, second.job_id)
    assert stored.counts.fetched == 1
    assert stored.counts.unchanged == 0


async def test_reused_links_pass_the_link_filter(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a first crawl across domains whose seed links a foreign page
    reader.pages["https://example.com/"] = {
        "content": "home",
        "links": {1: "https://other.com/page"},
        "status": "success",
    }
    await _submit(redis, ["https://example.com/"], same_domain_only=False)
    await _drain(worker)
    assert reader.calls.count("https://other.com/page") == 1
    worker.probe_mock.return_value = ConditionalProbe(304, '"v1"', None)

    # when a same-domain recrawl copies the seed forward
    _, second = await _submit(redis, ["https://example.com/"], same_domain_only=True)
    await _drain(worker)

    # then the stored foreign link is filtered out instead of queued
    assert reader.calls.count("https://other.com/page") == 1
    stored = await _stored(redis, second.job_id)
    assert stored.counts.unchanged == 1
    assert stored.counts.queued == 0


async def test_reused_links_take_the_depth_of_the_current_page(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a first crawl whose seed links a child page
    reader.pages["https://example.com/"] = {
        "content": "home",
        "links": {1: "https://example.com/child"},
        "status": "success",
    }
    await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    worker.probe_mock.return_value = ConditionalProbe(304, '"v1"', None)
    _, second = await _submit(redis, ["https://example.com/"])
    seen: list[int] = []
    real_links_for = worker._links_for

    async def spy(record: JobRecord, urls: list[str], depth: int) -> tuple[list[dict[str, object]], int]:
        kept, skipped = await real_links_for(record, urls, depth)
        seen.extend(int(str(item["d"])) for item in kept)
        return kept, skipped

    worker._links_for = spy  # type: ignore[method-assign]

    # when the seed is copied forward at depth 0
    assert await worker.run_once() is True

    # then its reused link sits at depth 1
    assert seen == [1]


async def test_worker_guard_uses_the_shared_fetch_policy(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a shared policy and a guard that records the policy it receives
    sentinel = object()
    policies: list[object] = []

    async def recording_guard(url: str, policy: Any) -> Any:
        policies.append(policy)
        return await _allow_guard(url, policy)

    monkeypatch.setattr(worker_module, "web_hunter_fetch_policy", lambda: sentinel)
    monkeypatch.setattr(worker_module, "check_fetch_uri", recording_guard)
    reader.pages["https://example.com/"] = {
        "content": "home",
        "links": {1: "https://example.com/child"},
        "status": "success",
    }
    await _submit(redis, ["https://example.com/"])

    # when
    assert await worker.run_once() is True

    # then the link guard ran with the shared policy
    assert policies == [sentinel]


async def test_page_only_the_human_tier_could_read_counts_as_failed(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given a real reader whose only working tier is the 6-novnc human-help tier
    article = "<html><body><article><p>" + "real words " * 40 + "</p></article></body></html>"
    stubs: dict[str, Any] = {}
    for name in TIER_ORDER:
        stub = MagicMock()
        stub.get_html = AsyncMock(return_value=article if name == "6-novnc" else "")
        stubs[name] = stub
    worker._reader = WebReader()
    _, record = await _submit(redis, ["https://example.com/"])

    # when the worker reads the page
    with (
        patch.object(WebReader, "_build_strategies", return_value=stubs),
        patch("src.validator.content_validator.ContentValidator.validate", return_value=True),
        patch("src.reader.web_reader.tier_memory.get", new=AsyncMock(return_value=None)),
    ):
        assert await worker.run_once() is True

    # then the human tier never opened and the page counts as failed
    stubs["6-novnc"].get_html.assert_not_awaited()
    stubs["5-crawlee_adaptive"].get_html.assert_awaited_once()
    stored = await _stored(redis, record.job_id)
    assert stored.counts.failed == 1
    assert stored.counts.fetched == 0
    assert stored.state == "failed"


async def test_apply_result_expiry_applies_the_rule_of_its_result_store(
    worker: WorkerHarness, results: FakeResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    applied = AsyncMock()
    monkeypatch.setattr(results, "apply_expiry_rule", applied)

    # when
    await worker.apply_result_expiry()

    # then
    applied.assert_awaited_once_with()


class _CancellingWriteResults(FakeResults):
    def __init__(self) -> None:
        super().__init__()
        self.cancel: Any = None

    async def write_page(self, key: str, content: str) -> None:
        if self.cancel is not None:
            await self.cancel()
        await super().write_page(key, content)


async def _recrawl_keys(redis: FakeRedis) -> list[str]:
    return [key async for key in redis.scan_iter(match="crawl_recrawl:*")]


async def test_cancel_during_page_write_removes_the_page_and_the_recrawl_state(
    redis: FakeRedis, reader: FakeReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a job that another instance cancels while its page object is written
    results = _CancellingWriteResults()
    worker = _make_worker(redis, reader, results, monkeypatch)
    svc, record = await _submit(redis, ["https://example.com/"])
    results.cancel = lambda: svc.cancel_job("acme", record.job_id)

    # when
    assert await worker.run_once() is True

    # then the page object and the recrawl state just written are gone
    assert results.text == {}
    assert results.deleted == [page_object_key("acme", record.job_id, "https://example.com/", "text")]
    assert await _recrawl_keys(redis) == []
    assert (await _stored(redis, record.job_id)).state == "cancelled"


async def test_cancel_during_recrawl_state_write_removes_the_page_and_the_recrawl_state(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a job that another instance cancels while the recrawl state is written
    svc, record = await _submit(redis, ["https://example.com/"])
    write = worker._recrawl.write

    async def cancelling_write(*args: Any, **kwargs: Any) -> str:
        await svc.cancel_job("acme", record.job_id)
        return await write(*args, **kwargs)

    monkeypatch.setattr(worker._recrawl, "write", cancelling_write)

    # when
    assert await worker.run_once() is True

    # then the page object and the recrawl state just written are gone
    assert results.text == {}
    assert await _recrawl_keys(redis) == []
    assert (await _stored(redis, record.job_id)).state == "cancelled"


async def test_cancel_during_recrawl_write_restores_the_earlier_recrawl_state(
    redis: FakeRedis, reader: FakeReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a finished job and a recrawl cancelled while its changed page is written
    results = _CancellingWriteResults()
    worker = _make_worker(redis, reader, results, monkeypatch)
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    scope = recrawl_scope(_req())
    before = await RecrawlStore(redis).read("acme", scope, "https://example.com/")
    assert before is not None
    first_pages = dict(results.text)
    worker.probe_mock.return_value = ConditionalProbe(200, '"v2"', None)
    reader.pages["https://example.com/"] = {"content": "changed", "links": {}, "status": "success"}
    svc, second = await _submit(redis, ["https://example.com/"])
    results.cancel = lambda: svc.cancel_job("acme", second.job_id)

    # when
    assert await worker.run_once() is True

    # then the recrawl's page is deleted and the first job's page and state are left as they were
    assert results.text == first_pages
    assert await RecrawlStore(redis).read("acme", scope, "https://example.com/") == before
    assert first.job_id in before["page_key"]


async def test_cancel_during_copy_forward_removes_the_copy_and_restores_the_recrawl_state(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a finished job and a recrawl cancelled while its unchanged page is copied
    await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    scope = recrawl_scope(_req())
    before = await RecrawlStore(redis).read("acme", scope, "https://example.com/")
    first_pages = dict(results.text)
    worker.probe_mock.return_value = ConditionalProbe(304, '"v1"', None)
    svc, second = await _submit(redis, ["https://example.com/"])
    copy = FakeResults.copy_page_forward

    async def cancelling_copy(self: FakeResults, source_key: str, dest_key: str) -> None:
        await svc.cancel_job("acme", second.job_id)
        await copy(self, source_key, dest_key)

    monkeypatch.setattr(FakeResults, "copy_page_forward", cancelling_copy)

    # when
    assert await worker.run_once() is True

    # then the copy is deleted and the recrawl state still names the first job's file
    assert len(results.copy_calls) == 1
    assert results.text == first_pages
    assert await RecrawlStore(redis).read("acme", scope, "https://example.com/") == before


async def test_failed_cleanup_after_cancel_is_logged_and_not_raised(
    worker: WorkerHarness,
    redis: FakeRedis,
    results: FakeResults,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given a job cancelled after its page write and a store that refuses the delete
    svc, record = await _submit(redis, ["https://example.com/"])
    write = worker._recrawl.write

    async def cancelling_write(*args: Any, **kwargs: Any) -> str:
        await svc.cancel_job("acme", record.job_id)
        return await write(*args, **kwargs)

    async def refusing_delete(key: str) -> None:
        raise RuntimeError("delete refused")

    monkeypatch.setattr(worker._recrawl, "write", cancelling_write)
    monkeypatch.setattr(results, "delete_page", refusing_delete)

    # when
    assert await worker.run_once() is True

    # then the failure is logged with the page key and the job stays cancelled
    assert any("delete refused" in message for message in caplog.messages)
    assert (await _stored(redis, record.job_id)).state == "cancelled"


async def test_cancel_after_a_failed_recrawl_write_removes_only_the_page(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a job cancelled after its page write whose recrawl write fails
    svc, record = await _submit(redis, ["https://example.com/"])
    revert = AsyncMock()

    async def failing_write(*args: Any, **kwargs: Any) -> str:
        await svc.cancel_job("acme", record.job_id)
        raise RuntimeError("down")

    monkeypatch.setattr(worker._recrawl, "write", failing_write)
    monkeypatch.setattr(worker._recrawl, "revert", revert)

    # when
    assert await worker.run_once() is True

    # then the page object is deleted and no recrawl entry is reverted
    assert results.text == {}
    assert len(results.deleted) == 1
    revert.assert_not_awaited()


@pytest.mark.parametrize("output_format", ["text", "structured"])
async def test_crawl_reads_ask_the_reader_to_skip_the_read_cache(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, output_format: OutputFormat
) -> None:
    # given
    await _submit(redis, ["https://example.com/"], output_format=output_format)

    # when
    await _drain(worker)

    # then every page read of the crawl skipped the read cache
    assert reader.cache_uses == [False]


async def test_every_robots_ask_runs_inside_the_crawl_proxy_context(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a crawl proxy and a robots fetch that records the proxy each ask would use
    from src.proxy.proxy_provider import proxy_provider

    monkeypatch.setattr(settings, "CRAWL_PROXY_URL", "http://crawl-proxy:8080")
    proxies: list[dict[str, str] | None] = []

    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        proxies.append(proxy_provider.for_curl_cffi())
        return RobotsFetch(200, "User-agent: *\nCrawl-delay: 2\n")

    worker._robots._fetch = robots_fetch
    await _submit(redis, ["https://example.com/", "https://example.org/"], respect_robots=True)

    # when
    await _drain(worker)

    # then the robots.txt of each origin was fetched through the crawl proxy, the first one before its claim
    assert proxies == [{"http": "http://crawl-proxy:8080", "https": "http://crawl-proxy:8080"}] * 2


async def test_robots_and_sitemap_fetches_carry_the_job_profile(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given
    profiles: list[tuple[str, str | None]] = []

    async def robots_fetch(url: str, profile: str | None) -> RobotsFetch:
        profiles.append((url, profile))
        return RobotsFetch(200, "User-agent: *\nSitemap: https://example.com/sitemap.xml\n")

    async def sitemap_fetch(url: str, profile: str | None) -> str:
        profiles.append((url, profile))
        return "<urlset/>"

    worker._robots._fetch = robots_fetch
    worker._robots._sitemap_fetch = sitemap_fetch
    await _submit(redis, ["https://example.com/"], profile="alice", respect_robots=True)

    # when
    await _drain(worker)

    # then
    assert profiles == [
        ("https://example.com/robots.txt", "alice"),
        ("https://example.com/sitemap.xml", "alice"),
    ]


def _remember_robots(worker: WorkerHarness, job_id: str) -> None:
    worker._robots._cache[(job_id, None, "https://example.com:443")] = _CachedRules(None, 0)
    worker._seeded.add((job_id, "https://example.com:443"))


def _remembers_robots(worker: WorkerHarness, job_id: str) -> bool:
    return any(key[0] == job_id for key in worker._robots._cache) or any(
        key[0] == job_id for key in worker._seeded
    )


async def test_instance_that_sees_a_finished_job_drops_its_robots_memory(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given a job another instance finished while this one still remembers its robots verdicts
    svc, record = await _submit(redis, ["https://example.com/"], respect_robots=True)
    _remember_robots(worker, record.job_id)
    await svc.cancel_job("acme", record.job_id)

    # when
    await worker.run_once()

    # then
    assert not _remembers_robots(worker, record.job_id)


async def test_instance_that_sees_a_gone_job_drops_its_robots_memory(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given a job whose record expired
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True)
    _remember_robots(worker, record.job_id)
    await redis.delete(job_key("acme", record.job_id))

    # when
    await worker.run_once()

    # then
    assert not _remembers_robots(worker, record.job_id)


@pytest.mark.parametrize("answer", [["gone"], ["idle", "cancelled"]])
async def test_claim_that_finds_the_job_ended_drops_its_robots_memory(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch, answer: list[str]
) -> None:
    # given a claim that answers the job is gone or no longer claimable
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True)
    _remember_robots(worker, record.job_id)
    monkeypatch.setattr(worker._frontier, "claim", AsyncMock(return_value=answer))

    # when
    claimed = await worker._try_domain(
        "acme", record.job_id, runnable_member("acme", record.job_id), record, "example.com"
    )

    # then
    assert claimed is False
    assert not _remembers_robots(worker, record.job_id)


async def test_claim_that_finds_nothing_to_claim_keeps_the_robots_memory(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a claim of a live job that finds nothing ready
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True)
    _remember_robots(worker, record.job_id)
    monkeypatch.setattr(worker._frontier, "claim", AsyncMock(return_value=["idle"]))

    # when
    await worker._try_domain(
        "acme", record.job_id, runnable_member("acme", record.job_id), record, "example.com"
    )

    # then
    assert _remembers_robots(worker, record.job_id)


async def test_robots_read_failure_log_carries_no_userinfo(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given rules that fail for a URL with userinfo
    async def boom(job_id: str, url: str, *, profile: str | None) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._robots, "rules", boom)
    record = JobRecord(job_id="j", tenant_id="a", request=_req(seeds=["https://e.com/"], respect_robots=True))

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        await worker._is_disallowed(record, "https://user:secret@e.com/x")
        await worker._domain_delay_ms(record, "https://user:secret@e.com/x")

    # then
    assert caplog.text.count("e.com/x") == 2
    assert "secret" not in caplog.text


async def _submit_at(redis: FakeRedis, seed: str, score: int, **overrides: Any) -> JobRecord:
    _, record = await _submit(redis, [seed], **overrides)
    await redis.zadd(RUNNABLE_KEY, {runnable_member("acme", record.job_id): score})
    return record


@pytest.mark.parametrize("delay", ["1e306", "1000000000", "61"])
async def test_a_huge_crawl_delay_is_cut_to_the_maximum(
    worker: WorkerHarness, redis: FakeRedis, delay: str
) -> None:
    # given
    async def fetch(url: str) -> str:
        return f"User-agent: *\nCrawl-delay: {delay}\n"

    _serve_robots(worker, fetch)
    job = JobRecord(job_id="j", tenant_id="a", request=_req(respect_robots=True))

    # when
    delay_ms = await worker._domain_delay_ms(job, "https://example.com/")

    # then
    assert delay_ms == int(settings.CRAWL_MAX_DELAY_SECONDS * 1000)


async def test_the_delay_cut_never_goes_below_the_one_second_floor_setting(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a floor above the maximum
    monkeypatch.setattr(settings, "CRAWL_DEFAULT_DELAY_SECONDS", 90.0)

    async def fetch(url: str) -> str:
        return "User-agent: *\nCrawl-delay: 1000\n"

    _serve_robots(worker, fetch)
    job = JobRecord(job_id="j", tenant_id="a", request=_req(respect_robots=True))

    # when / then
    assert await worker._domain_delay_ms(job, "https://example.com/") == 90_000


async def test_a_job_with_an_unusable_crawl_delay_does_not_stop_the_sweep(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given a first job on a site with a crawl delay too large for an integer and a later job
    async def fetch(url: str) -> str:
        return "User-agent: *\nCrawl-delay: 1e306\n" if "hostile" in url else ""

    _serve_robots(worker, fetch)
    await _submit_at(redis, "https://hostile.example/", 1, respect_robots=True)
    await _submit_at(redis, "https://example.org/", 2)

    # when both are swept
    assert await _drain(worker) >= 2

    # then both pages are read
    assert set(reader.calls) == {"https://hostile.example/", "https://example.org/"}


async def test_a_failing_job_does_not_stop_a_later_job_from_being_claimed(
    worker: WorkerHarness,
    redis: FakeRedis,
    reader: FakeReader,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given a first job whose processing raises and a later job
    bad = await _submit_at(redis, "https://bad.example/", 1)
    good = await _submit_at(redis, "https://example.org/", 2)
    real_try_domain = worker._try_domain

    async def try_domain(tenant_id: str, job_id: str, member: str, record: JobRecord, domain: str) -> bool:
        if job_id == bad.job_id:
            raise RuntimeError("bad job at https://bad.example/x?token=secret")
        return await real_try_domain(tenant_id, job_id, member, record, domain)

    monkeypatch.setattr(worker, "_try_domain", try_domain)

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        claimed = await worker.run_once()

    # then the later job's page was claimed and read, and the failure is logged without the query
    assert claimed is True
    assert reader.calls == ["https://example.org/"]
    assert (await _stored(redis, good.job_id)).counts.fetched == 1
    assert runnable_member("acme", bad.job_id) in caplog.text
    assert "token=secret" not in caplog.text


@pytest.mark.parametrize(
    ("robots_body", "read"),
    [
        (f"User-agent: {CRAWL_USER_AGENT}\nDisallow: /\n\nUser-agent: *\nAllow: /\n", False),
        (f"User-agent: *\nDisallow: /\n\nUser-agent: {CRAWL_USER_AGENT}\nAllow: /\n", True),
    ],
)
async def test_a_group_that_names_the_crawler_decides_over_the_star_group(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, robots_body: str, read: bool
) -> None:
    # given
    async def fetch(url: str) -> str:
        return robots_body

    _serve_robots(worker, fetch)
    await _submit(redis, ["https://example.com/"], respect_robots=True)

    # when
    await _drain(worker)

    # then
    assert ("https://example.com/" in reader.calls) is read


async def test_the_crawl_delay_of_a_group_that_names_the_crawler_applies(
    worker: WorkerHarness,
) -> None:
    # given
    async def fetch(url: str) -> str:
        return f"User-agent: *\nCrawl-delay: 3\n\nUser-agent: {CRAWL_USER_AGENT}\nCrawl-delay: 9\n"

    _serve_robots(worker, fetch)
    job = JobRecord(job_id="j", tenant_id="a", request=_req(respect_robots=True))

    # when / then
    assert await worker._domain_delay_ms(job, "https://example.com/") == 9000


async def test_a_sweep_drops_the_caches_of_a_job_no_longer_runnable_and_keeps_a_live_one(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a live job and a job ended by another instance, its member already gone
    _, live = await _submit(redis, ["https://example.com/"])
    _remember_robots(worker, live.job_id)
    _remember_robots(worker, "ended-elsewhere")
    worker._robots._allowances["ended-elsewhere-sitemaps"] = SitemapAllowance(documents=1, urls=1)
    monkeypatch.setattr(worker, "_drain_member", AsyncMock(return_value=False))

    # when
    await worker.run_once()

    # then
    assert _remembers_robots(worker, live.job_id)
    assert worker._robots.job_ids() == {live.job_id}
    assert {key[0] for key in worker._seeded} == {live.job_id}


async def test_a_sweep_keeps_the_caches_when_the_runnable_set_cannot_be_read(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    _remember_robots(worker, "j1")
    monkeypatch.setattr(worker._frontier, "list_runnable", AsyncMock(side_effect=RuntimeError("down")))

    # when
    assert await worker.run_once() is False

    # then
    assert _remembers_robots(worker, "j1")


async def test_a_page_skipped_for_robots_spends_no_page_budget(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a budget of one page and a first seed robots.txt disallows
    async def fetch(url: str) -> str:
        return "User-agent: *\nDisallow: /private\n" if url.endswith("robots.txt") else ""

    _serve_robots(worker, fetch)
    _, record = await _submit(
        redis,
        ["https://example.com/private", "https://example.com/open"],
        respect_robots=True,
        page_budget=1,
    )

    # when
    await _drain(worker)

    # then the skipped page did not take the budget from the open page
    assert reader.calls == ["https://example.com/open"]
    stored = await _stored(redis, record.job_id)
    assert stored.state == "succeeded"
    assert stored.counts.fetched == 1
    assert stored.counts.failed == 0
    assert stored.counts.robots_skipped == 1
    lines = {line["url"]: line for line in results.index_writes[0][1]}
    assert lines["https://example.com/private"]["reason"] == ROBOTS_SKIP_REASON


async def test_a_job_with_every_page_skipped_for_robots_ends_failed(
    worker: WorkerHarness, redis: FakeRedis
) -> None:
    # given
    async def fetch(url: str) -> str:
        return "User-agent: *\nDisallow: /\n"

    _serve_robots(worker, fetch)
    _, record = await _submit(redis, ["https://example.com/"], respect_robots=True)

    # when
    await _drain(worker)

    # then
    stored = await _stored(redis, record.job_id)
    assert stored.state == "failed"
    assert stored.counts.failed == 0
    assert stored.counts.robots_skipped == 1


async def test_a_sitemap_filter_computes_the_seed_set_once_per_request(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a sitemap of 200 addresses, a job with 20 seeds and a counter of domain lookups
    sitemap = "<urlset>" + "".join(f"<url><loc>https://example.com/p{n}</loc></url>" for n in range(200))
    sitemap += "</urlset>"

    async def fetch(url: str) -> str:
        return f"Sitemap: {SITEMAP_URL}\n" if url == ROBOTS_URL else sitemap

    _serve_robots(worker, fetch)
    record = _req(seeds=[f"https://s{n}.example.net/" for n in range(20)], page_budget=500)
    job = JobRecord(job_id="j", tenant_id="acme", request=record)
    from src.reader.cloudflare.cookie_manager import cookie_manager

    real = cookie_manager.registrable_domain
    lookups: list[str] = []

    def counting(url: str) -> str:
        lookups.append(url)
        return real(url)

    monkeypatch.setattr(cookie_manager, "registrable_domain", counting)

    # when
    await worker._seed_sitemaps("acme", "j", job, "https://example.com/", 0)

    # then twenty seed lookups happen once, not once per address
    assert len([url for url in lookups if ".example.net" in url]) == 20


async def test_a_seed_domain_set_is_read_from_the_seeds_of_the_request() -> None:
    # given
    request = _req(seeds=["https://www.example.com/a", "https://blog.example.org/"])

    # when / then
    assert request.seed_domains == frozenset({"example.com", "example.org"})
    assert seed_domains(request) == ["example.com", "example.org"]


async def test_a_job_on_its_seeds_passes_the_seed_domains_to_the_sitemap_seeding(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given
    seen: list[frozenset[str] | None] = []

    async def seed_urls(
        job_id: str, page_url: str, *, seed_domains: frozenset[str] | None = None, **kwargs: Any
    ) -> list[str]:
        seen.append(seed_domains)
        return []

    monkeypatch.setattr(worker._robots, "sitemap_seed_urls", seed_urls)
    on_seeds = JobRecord(job_id="j1", tenant_id="acme", request=_req(same_domain_only=True))
    free = JobRecord(job_id="j2", tenant_id="acme", request=_req(same_domain_only=False))

    # when
    await worker._seed_sitemaps("acme", "j1", on_seeds, "https://example.com/", 0)
    await worker._seed_sitemaps("acme", "j2", free, "https://example.com/", 0)

    # then
    assert seen == [frozenset({"example.com"}), None]


async def test_a_sitemap_seed_over_its_deadline_is_logged_and_the_page_is_still_read(
    worker: WorkerHarness,
    redis: FakeRedis,
    reader: FakeReader,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given sitemap work that never ends and a short deadline
    monkeypatch.setattr(settings, "CRAWL_SITEMAP_TIMEOUT_SECONDS", 0.01)

    async def never(*_args: Any, **_kwargs: Any) -> list[str]:
        await asyncio.Event().wait()
        return []

    monkeypatch.setattr(worker._robots, "sitemap_seed_urls", never)
    _, record = await _submit(redis, ["https://example.com/"])

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        await _drain(worker)

    # then
    assert reader.calls == ["https://example.com/"]
    assert (await _stored(redis, record.job_id)).counts.fetched == 1
    assert "sitemap seed failed" in caplog.text


async def test_the_sitemap_deadline_also_covers_queueing_the_addresses(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given addresses whose guard check never ends and a short deadline
    monkeypatch.setattr(settings, "CRAWL_SITEMAP_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(
        worker._robots, "sitemap_seed_urls", AsyncMock(return_value=["https://example.com/a"])
    )

    async def never(*_args: Any, **_kwargs: Any) -> None:
        await asyncio.Event().wait()

    monkeypatch.setattr(worker_module, "check_fetch_uri", never)
    job = JobRecord(job_id="j", tenant_id="acme", request=_req())

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        skipped = await worker._seed_sitemaps("acme", "j", job, "https://example.com/", 0)

    # then
    assert skipped == 0
    assert "sitemap seed failed" in caplog.text


_ADDRESS_WITH_QUERY = "https://example.com/page?token=address-secret"
_ERROR_WITH_QUERY = RuntimeError("failed at https://example.com/x?token=error-secret")


def _assert_no_secret(caplog: pytest.LogCaptureFixture) -> None:
    assert "https://example.com/page" in caplog.text
    assert "token=" not in caplog.text
    assert "secret" not in caplog.text


async def test_a_robots_failure_in_the_delay_logs_no_query(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    monkeypatch.setattr(worker._robots, "rules", AsyncMock(side_effect=_ERROR_WITH_QUERY))
    job = JobRecord(job_id="j", tenant_id="a", request=_req(respect_robots=True))

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        await worker._domain_delay_ms(job, _ADDRESS_WITH_QUERY)

    # then
    _assert_no_secret(caplog)


async def test_a_robots_failure_on_the_page_logs_no_query(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    monkeypatch.setattr(worker._robots, "rules", AsyncMock(side_effect=_ERROR_WITH_QUERY))
    job = JobRecord(job_id="j", tenant_id="a", request=_req(respect_robots=True))

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        disallowed = await worker._is_disallowed(job, _ADDRESS_WITH_QUERY)

    # then
    assert disallowed is True
    _assert_no_secret(caplog)


async def test_a_failed_page_processing_logs_no_query(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    monkeypatch.setattr(worker, "_read_page", AsyncMock(side_effect=_ERROR_WITH_QUERY))
    monkeypatch.setattr(worker, "_finish", AsyncMock())
    job = JobRecord(job_id="j", tenant_id="acme", request=_req())

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        await worker._process_claim("acme", "j", "acme:j", job, "example.com", _ADDRESS_WITH_QUERY, 0)

    # then
    _assert_no_secret(caplog)


async def test_a_failed_sitemap_seed_logs_no_query(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    monkeypatch.setattr(worker._robots, "sitemap_seed_urls", AsyncMock(side_effect=_ERROR_WITH_QUERY))
    job = JobRecord(job_id="j", tenant_id="acme", request=_req())

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        await worker._seed_sitemaps("acme", "j", job, _ADDRESS_WITH_QUERY, 0)

    # then
    _assert_no_secret(caplog)


async def test_a_failed_read_logs_no_query(
    worker: WorkerHarness,
    reader: FakeReader,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    # given
    monkeypatch.setattr(reader, "read_linked_page", AsyncMock(side_effect=_ERROR_WITH_QUERY))
    job = JobRecord(job_id="j", tenant_id="acme", request=_req())

    # when
    with caplog.at_level("WARNING", logger="src.crawl.worker"):
        await worker._extract(job, _ADDRESS_WITH_QUERY)

    # then
    _assert_no_secret(caplog)
