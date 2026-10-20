import asyncio
from itertools import pairwise
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError
from fakeredis.aioredis import FakeRedis

from src.config.config import settings
from src.crawl import worker as worker_module
from src.crawl.fetcher import ConditionalProbe
from src.crawl.frontier import Frontier
from src.crawl.job_service import CrawlJobService
from src.crawl.keys import RUNNABLE_KEY, job_key, runnable_member
from src.crawl.models import CrawlRequest, JobRecord
from src.crawl.result_store import RecrawlStore, ResultStore
from src.crawl.robots import RobotsStore
from src.crawl.worker import Worker, seed_domains
from src.reader.web_reader import OutputFormat, TierName, WebReader

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
        self.calls: list[str] = []

    async def read_with_links(
        self,
        url: str,
        link_filter: str | None = None,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
    ) -> dict[str, Any]:
        self.calls.append(url)
        if url in self.pages:
            return self.pages[url]
        return {"content": f"content of {url}", "links": {}, "status": "success"}

    async def read(
        self,
        url: str,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        extraction_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self.calls.append(f"read:{url}")
        return {"content": f"formatted {url}", "status": "success", "mode": "test"}


class FakeResults(ResultStore):
    def __init__(self) -> None:
        self.text: dict[str, str] = {}
        self.index_writes: list[tuple[str, list[dict[str, Any]]]] = []
        self.copy_calls: list[tuple[str, str]] = []
        self.copy_mode: str = "ok"
        self.exists_mode: str = "real"

    async def write_page(self, key: str, content: str) -> None:
        self.text[key] = content

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
    reader: FakeReader,
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
    monkeypatch.setattr(
        "src.crawl.worker.fetcher.head_validators", AsyncMock(return_value=(None, None))
    )
    robots = RobotsStore(_empty_robots)
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


async def _empty_robots(url: str) -> str:
    return ""


async def _submit(
    redis: FakeRedis, seeds: list[str], **overrides: Any
) -> tuple[CrawlJobService, JobRecord]:
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
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given a robots.txt that disallows /private/
    async def fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "User-agent: *\nDisallow: /private/\n"
        return ""

    monkeypatch.setattr(worker._robots, "_fetch", fetch)
    reader.pages["https://example.com/"] = {
        "content": "home",
        "links": {1: "https://example.com/private/x"},
        "status": "success",
    }
    _, record = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the disallowed path is never read
    assert "https://example.com/private/x" not in reader.calls
    stored = await _stored(redis, record.job_id)
    assert stored.state == "succeeded"


async def test_crawl_delay_honoured(worker: WorkerHarness, redis: FakeRedis) -> None:
    # given a robots.txt with a 5 second crawl delay
    async def fetch(url: str) -> str:
        if url.endswith("/robots.txt"):
            return "User-agent: *\nCrawl-delay: 5\n"
        return ""

    worker._robots._fetch = fetch
    _, record = await _submit(redis, ["https://example.com/a", "https://example.com/b"])

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
            return (
                "<urlset><url><loc>https://example.com/from-sitemap</loc></url></urlset>"
            )
        return ""

    worker._robots._fetch = fetch
    await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the sitemap URL is fetched too
    assert "https://example.com/from-sitemap" in reader.calls


async def test_respect_false_skips_robots(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given an opt-out domain with respect off
    monkeypatch.setattr(settings, "CRAWL_ROBOTS_OPT_OUT_DOMAINS", ("example.com",))
    calls: list[str] = []

    async def fetch(url: str) -> str:
        calls.append(url)
        return "User-agent: *\nDisallow: /\n"

    worker._robots._fetch = fetch
    await _submit(redis, ["https://example.com/"], respect_robots=False)

    # when
    await _drain(worker)

    # then no robots file is read and the page is fetched
    assert calls == []


async def _run_job_twice(worker: WorkerHarness, redis: FakeRedis) -> tuple[JobRecord, JobRecord]:
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    _, second = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    stored_first = await _stored(redis, first.job_id)
    stored_second = await _stored(redis, second.job_id)
    return stored_first, stored_second


async def test_304_copies_forward_without_read(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a completed job and a 304 probe on the identical recrawl
    await _run_job_twice(worker, redis)
    assert len(reader.calls) == 2
    copies_before = len(results.copy_calls)
    probe = worker.probe_mock
    probe.return_value = ConditionalProbe(304, '"v1"', None)
    _, third = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then no new read happens and the page counts as unchanged
    assert len(reader.calls) == 2
    stored = await _stored(redis, third.job_id)
    assert stored.counts.unchanged == 1
    assert stored.counts.fetched == 0
    assert len(results.copy_calls) == copies_before + 1


async def test_equal_hash_copies_forward(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a completed job and a 200 probe with the same content
    await _run_job_twice(worker, redis)
    probe = worker.probe_mock
    probe.return_value = ConditionalProbe(200, '"v2"', None)
    writes_before = len(results.text)
    _, third = await _submit(redis, ["https://example.com/"])

    # when
    await _drain(worker)

    # then the read happens but the file is copied, not re-uploaded
    stored = await _stored(redis, third.job_id)
    assert stored.counts.unchanged == 1
    assert len(results.copy_calls) >= 1
    assert len(results.text) == writes_before + 1


async def test_missing_earlier_file_reads_unconditionally(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader, results: FakeResults
) -> None:
    # given a recrawl entry whose page file is gone
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)
    probe = worker.probe_mock
    calls_before = probe.await_count
    _, second = await _submit(redis, ["https://example.com/"])
    from src.crawl.result_store import RecrawlStore, recrawl_scope

    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(["https://example.com/"], [])
    entry = await recrawl.read("acme", scope, "https://example.com/")
    assert entry is not None
    results.text.pop(entry["page_key"])

    # when
    await _drain(worker)

    # then no conditional probe runs and the page is written new
    assert probe.await_count == calls_before
    stored = await _stored(redis, second.job_id)
    assert stored.counts.fetched == 1
    assert stored.counts.unchanged == 0
    assert "https://example.com/" in reader.calls


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

    # then the page counts as failed and the job still ends
    stored = await _stored(redis, second.job_id)
    assert stored.counts.failed == 1
    assert stored.state == "succeeded"


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
    )
    await svc.cancel_job("acme", record.job_id)

    # when the late page finishes
    await worker._finish(
        "acme",
        record.job_id,
        runnable_member("acme", record.job_id),
        record,
        "example.com",
        "0\thttps://example.com/",
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
        async def read_with_links(
            self,
            url: str,
            link_filter: str | None = None,
            heavy_mode: bool = False,
            profile: str | None = None,
            output_format: OutputFormat | None = None,
            tier: TierName | None = None,
        ) -> dict[str, Any]:
            active["now"] += 1
            active["peak"] = max(active["peak"], active["now"])
            if active["peak"] >= 2:
                peaked.set()
            await release.wait()
            active["now"] -= 1
            active["done"] += 1
            if active["done"] >= 6:
                drained.set()
            return {"content": f"c {url}", "links": {}, "status": "success"}

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
        redis, reader=reader, robots=RobotsStore(_empty_robots), clock_ms=lambda: NOW
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


async def test_run_once_survives_broken_redis(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
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
        "acme", record.job_id, "m", record, "example.com", "0\thttps://example.com/",
        outcome="ok", page_line="{}", links=[], skipped=0,
    )


async def test_finalize_on_vanished_job_drops_caches(worker: WorkerHarness) -> None:
    # given seeded caches for a job that no longer exists
    worker._seeded.add(("gone", "example.com"))

    # when / then no raise
    await worker._finalize("acme", "gone", "acme:gone")
    assert ("gone", "example.com") not in worker._seeded


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

    # then the page counts as failed and the job still ends
    stored = await _stored(redis, record.job_id)
    assert stored.counts.failed == 1
    assert stored.state == "succeeded"


async def test_extract_failure_modes(
    worker: WorkerHarness, redis: FakeRedis, reader: FakeReader
) -> None:
    # given pages with failing reads
    reader.pages["https://example.com/error-status"] = {"content": "", "links": {}, "status": "error"}
    reader.pages["https://example.com/no-content"] = {"links": {}, "status": "success"}
    reader.pages["https://example.com/bad-links"] = {
        "content": "x",
        "links": {"a": 1, "b": "https://example.com/ok"},
        "status": "success",
    }

    class BoomReader(FakeReader):
        async def read_with_links(
            self,
            url: str,
            link_filter: str | None = None,
            heavy_mode: bool = False,
            profile: str | None = None,
            output_format: OutputFormat | None = None,
            tier: TierName | None = None,
        ) -> dict[str, Any]:
            if "boom" in url:
                raise RuntimeError("down")
            return await super().read_with_links(url, link_filter, heavy_mode, profile, output_format, tier)

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
    ) -> dict[str, Any]:
        if "plain" in url:
            return {"content": "formatted body", "status": "success"}
        return {"title": "t", "status": "success"}

    async def schema_bad(
        url: str,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        extraction_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if "raises" in url:
            raise RuntimeError("down")
        return {"status": "error"}

    monkeypatch.setattr(reader, "read", schema_ok)
    _, record = await _submit(
        redis,
        ["https://example.com/plain", "https://example.com/dump"],
        output_format="schema",
        extraction_schema={"type": "object"},
    )

    # when
    await _drain(worker)

    # then both pages are stored, one from content and one dumped
    stored = await _stored(redis, record.job_id)
    assert stored.counts.fetched == 2

    # when formatted reads fail
    monkeypatch.setattr(reader, "read", schema_bad)
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
    record = _req()

    class Rules:
        def __init__(self, delay: float | None) -> None:
            self._delay = delay

        def crawl_delay(self, agent: str) -> float | None:
            return self._delay

    # when respect is off the floor applies without any fetch
    assert await worker._domain_delay_ms(
        JobRecord(job_id="j", tenant_id="a", request=record), "example.com"
    ) >= 0

    # when rules are missing or carry no delay the floor applies
    async def none_rules(job_id: str, url: str) -> Any:
        return None

    monkeypatch.setattr(worker._robots, "rules", none_rules)
    job = JobRecord(job_id="j", tenant_id="a", request=record)
    got = await worker._domain_delay_ms(job, "example.com")
    assert got == int(settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000)

    async def boom(job_id: str, url: str) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._robots, "rules", boom)
    got = await worker._domain_delay_ms(job, "example.com")
    assert got == int(settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000)

    async def no_delay(job_id: str, url: str) -> Any:
        return Rules(None)

    monkeypatch.setattr(worker._robots, "rules", no_delay)
    got = await worker._domain_delay_ms(job, "example.com")
    assert got == int(settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000)

    async def slow(job_id: str, url: str) -> Any:
        return Rules(30.0)

    monkeypatch.setattr(worker._robots, "rules", slow)
    assert await worker._domain_delay_ms(job, "example.com") == 30000


async def test_write_recrawl_error_is_logged(worker: WorkerHarness, redis: FakeRedis) -> None:
    # given a recrawl store whose writes fail
    from src.crawl.result_store import RecrawlStore

    class BoomRecrawl(RecrawlStore):
        async def write(self, *args: Any, **kwargs: Any) -> None:
            raise RuntimeError("down")

    worker._recrawl = BoomRecrawl(redis)
    _, record = await _submit(redis, ["https://example.com/"])

    # when / then no raise and the page still counts as fetched
    await _drain(worker)
    stored = await _stored(redis, record.job_id)
    assert stored.counts.fetched == 1


async def test_corrupt_recrawl_entry_reads_unconditionally(
    worker: WorkerHarness, redis: FakeRedis, results: FakeResults
) -> None:
    # given a corrupt recrawl entry with a non-string key and validators
    from src.crawl.result_store import RecrawlStore, recrawl_scope

    _, record = await _submit(redis, ["https://example.com/"])
    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(["https://example.com/"], [])
    await recrawl.write(
        "acme", scope, "https://example.com/",
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
    content, kept, skipped = await worker._links_for(record, ["http://[::1/"], 0, "c")
    assert (content, kept, skipped) == ("c", [], 0)


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


async def test_is_disallowed_error_allows(
    worker: WorkerHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given rules that fail
    async def boom(job_id: str, url: str) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._robots, "rules", boom)
    record = JobRecord(job_id="j", tenant_id="a", request=_req(seeds=["https://e.com/"]))

    # when / then
    assert await worker._is_disallowed(record, "https://e.com/x") is False


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

    worker._robots._fetch = fetch
    await _submit(redis, ["https://example.com/", "https://example.com/b"])

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

    monkeypatch.setattr(worker._robots, "_fetch", fetch)
    _, record = await _submit(redis, ["https://example.com/"])

    async def boom(**kwargs: Any) -> Any:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._frontier, "add_urls", boom)

    # when / then no raise and the unsafe count is zero
    assert await worker._seed_sitemaps("acme", record.job_id, record, "example.com", 0) == 0


async def test_seed_sitemaps_survives_fetch_error(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given sitemap seeding that fails
    _, record = await _submit(redis, ["https://example.com/"])

    async def boom(job_id: str, url: str) -> list[str]:
        raise RuntimeError("down")

    monkeypatch.setattr(worker._robots, "sitemap_seed_urls", boom)

    # when / then no raise
    assert await worker._seed_sitemaps("acme", record.job_id, record, "example.com", 0) == 0


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
    scope = recrawl_scope(["https://example.com/"], [])
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
    assert seen == {"etag": '"abc"', "last_modified": "Wed"}
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


async def test_fresh_write_captures_head_validators(
    worker: WorkerHarness, redis: FakeRedis, monkeypatch: pytest.MonkeyPatch
) -> None:
    # given HEAD answers validators on a fresh crawl
    from src.crawl.result_store import RecrawlStore, recrawl_scope

    monkeypatch.setattr(
        "src.crawl.worker.fetcher.head_validators", AsyncMock(return_value=('"h"', "Wed"))
    )
    _, first = await _submit(redis, ["https://example.com/"])
    await _drain(worker)

    # then the recrawl entry carries them
    recrawl = RecrawlStore(redis)
    scope = recrawl_scope(["https://example.com/"], [])
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
    assert seen == {"etag": '"h"', "last_modified": "Wed"}
    stored = await _stored(redis, second.job_id)
    assert stored.counts.unchanged == 1
