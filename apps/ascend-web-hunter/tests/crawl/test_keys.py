import re

from fakeredis.aioredis import FakeRedis

from src.crawl.frontier import Frontier, claim_entry
from src.crawl.keys import (
    RUNNABLE_KEY,
    claims_key,
    inflight_key,
    job_key,
    next_fetch_key,
    pages_key,
    queue_key,
    recrawl_key,
    runnable_member,
    seen_key,
)
from src.crawl.models import CrawlRequest
from src.crawl.result_store import recrawl_scope


def test_key_builders_follow_d13() -> None:
    # then every builder equals its D13 pattern
    assert job_key("acme", "j") == "crawl_job:acme:j"
    assert queue_key("acme", "j", "example.com") == "crawl_queue:acme:j:example.com"
    assert seen_key("acme", "j") == "crawl_seen:acme:j"
    assert inflight_key("acme", "j", "example.com") == "crawl_inflight:acme:j:example.com"
    assert next_fetch_key("acme", "j", "example.com") == "crawl_next_fetch:acme:j:example.com"
    assert claims_key("acme", "j") == "crawl_claims:acme:j"
    assert pages_key("acme", "j") == "crawl_pages:acme:j"
    assert recrawl_key("acme", "scope") == "crawl_recrawl:acme:scope"
    assert RUNNABLE_KEY == "crawl_runnable"
    assert runnable_member("acme", "j") == "acme:j"


async def test_job_writes_only_own_tenant_keys() -> None:
    # given a frontier over a fake Redis
    redis = FakeRedis(decode_responses=True)
    frontier = Frontier(redis)

    # when a job of tenant acme runs submit, claim and finish
    job_json = (
        '{"job_id": "j1", "state": "waiting", "counts": {"queued": 1, "fetched": 0, '
        '"unchanged": 0, "failed": 0, "skipped_unsafe": 0}, "claim_expiries": {}, '
        '"domains": ["example.com"], "pending": 1, "updated_at": "t"}'
    )
    groups = '[{"domain": "example.com", "urls": [{"u": "https://example.com/", "d": 0}]}]'
    await frontier.submit(
        job_key=job_key("acme", "j1"),
        seen_key=seen_key("acme", "j1"),
        runnable_key=RUNNABLE_KEY,
        job_json=job_json,
        retention=604800,
        submitted_ms=1,
        member=runnable_member("acme", "j1"),
        tenant_id="acme",
        job_id="j1",
        groups_json=groups,
    )
    await frontier.claim(
        job_key=job_key("acme", "j1"),
        queue_key=queue_key("acme", "j1", "example.com"),
        inflight_key=inflight_key("acme", "j1", "example.com"),
        claims_key=claims_key("acme", "j1"),
        next_fetch_key=next_fetch_key("acme", "j1", "example.com"),
        runnable_key=RUNNABLE_KEY,
        now_ms=1000,
        lease_ms=120000,
        page_budget=10,
        domain_cap=2,
        delay_ms=0,
        retention=604800,
        member=runnable_member("acme", "j1"),
        max_expiries=2,
        updated_at="2026-10-19T00:00:00+00:00",
        tenant_id="acme",
        job_id="j1",
        domain="example.com",
        robots_skip_factor=10,
    )
    await frontier.finish(
        job_key=job_key("acme", "j1"),
        seen_key=seen_key("acme", "j1"),
        claims_key=claims_key("acme", "j1"),
        pages_key=pages_key("acme", "j1"),
        runnable_key=RUNNABLE_KEY,
        entry=claim_entry(0, "example.com", "https://example.com/"),
        outcome="ok",
        page_line='{"url": "https://example.com/"}',
        max_depth=2,
        retention=604800,
        skipped_delta=0,
        tenant_id="acme",
        job_id="j1",
        domain="example.com",
        links_json="[]",
        updated_at="2026-10-19T00:00:00+00:00",
        member=runnable_member("acme", "j1"),
        robots_skip_factor=10,
    )

    # then every key matches the tenant pattern and equals a D13 shape
    names = [key async for key in redis.scan_iter(match="*")]
    tenant_names = [name for name in names if name != RUNNABLE_KEY]
    assert tenant_names, "expected tenant keys"
    for name in tenant_names:
        assert re.fullmatch(r"crawl_[a-z_]+:acme:.*", name) is not None, name
    shapes = {
        r"crawl_job:acme:j1",
        r"crawl_queue:acme:j1:example\.com",
        r"crawl_seen:acme:j1",
        r"crawl_inflight:acme:j1:example\.com",
        r"crawl_claims:acme:j1",
        r"crawl_next_fetch:acme:j1:example\.com",
        r"crawl_pages:acme:j1",
    }
    for name in tenant_names:
        assert any(re.fullmatch(shape, name) for shape in shapes), name
    request = CrawlRequest(seeds=["https://example.com/"])  # type: ignore[list-item]
    assert re.fullmatch(r"[0-9a-f]{64}", recrawl_scope(request)) is not None
