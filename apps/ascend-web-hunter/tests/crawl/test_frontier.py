import json
from typing import Any

import pytest
import redis.asyncio as async_redis
from fakeredis.aioredis import FakeRedis

from src.config.config import settings
from src.crawl.frontier import ALL_PAGES_FAILED_ERROR, Frontier, claim_entry
from src.crawl.keys import (
    RUNNABLE_KEY,
    claims_key,
    inflight_key,
    job_key,
    next_fetch_key,
    pages_key,
    queue_key,
    runnable_member,
    seen_key,
)

TENANT = "acme"
JOB = "job1"
MEMBER = runnable_member(TENANT, JOB)
NOW = 1_000_000


def _job_json(**overrides: object) -> str:
    record = {
        "job_id": JOB,
        "tenant_id": TENANT,
        "state": "waiting",
        "counts": {"queued": 0, "fetched": 0, "unchanged": 0, "failed": 0, "skipped_unsafe": 0},
        "claim_expiries": {},
        "domains": ["example.com"],
        "pending": 0,
        "updated_at": "t",
    }
    record.update(overrides)
    return json.dumps(record)


def _groups(*urls: str) -> str:
    return json.dumps([{"domain": "example.com", "urls": [{"u": url, "d": 0} for url in urls]}])


def _request_with_patterns(**overrides: object) -> dict[str, object]:
    request: dict[str, object] = {
        "seeds": ["https://example.com/"],
        "include_patterns": [],
        "exclude_patterns": [],
        "max_depth": 2,
        "page_budget": 10,
        "same_domain_only": True,
        "respect_robots": True,
        "output_format": "text",
        "extraction_schema": None,
        "profile": None,
    }
    request.update(overrides)
    return request


async def _record(client: async_redis.Redis) -> dict[str, Any]:
    raw = await client.get(job_key(TENANT, JOB))
    assert isinstance(raw, str)
    loaded: dict[str, Any] = json.loads(raw)
    return loaded


async def _submit(
    frontier: Frontier,
    job_json: str | None = None,
    groups: str | None = None,
    job_id: str = JOB,
) -> None:
    payload = groups or _groups("https://example.com/")
    if job_json is None:
        total = sum(len(group["urls"]) for group in json.loads(payload))
        job_json = _job_json(
            counts={
                "queued": total,
                "fetched": 0,
                "unchanged": 0,
                "failed": 0,
                "skipped_unsafe": 0,
            },
            pending=total,
        )
    await frontier.submit(
        job_key=job_key(TENANT, job_id),
        seen_key=seen_key(TENANT, job_id),
        runnable_key=RUNNABLE_KEY,
        job_json=job_json or _job_json(),
        retention=settings.CRAWL_JOB_RETENTION_SECONDS,
        submitted_ms=NOW,
        member=runnable_member(TENANT, job_id),
        tenant_id=TENANT,
        job_id=job_id,
        groups_json=payload,
    )


def _claim_kwargs(frontier: Frontier, **overrides: object) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "job_key": job_key(TENANT, JOB),
        "queue_key": queue_key(TENANT, JOB, "example.com"),
        "inflight_key": inflight_key(TENANT, JOB, "example.com"),
        "claims_key": claims_key(TENANT, JOB),
        "next_fetch_key": next_fetch_key(TENANT, JOB, "example.com"),
        "runnable_key": RUNNABLE_KEY,
        "now_ms": NOW,
        "lease_ms": settings.CRAWL_CLAIM_LEASE_SECONDS * 1000,
        "page_budget": 10,
        "domain_cap": settings.CRAWL_DOMAIN_CONCURRENCY,
        "delay_ms": 0,
        "retention": settings.CRAWL_JOB_RETENTION_SECONDS,
        "member": MEMBER,
        "max_expiries": settings.CRAWL_CLAIM_MAX_EXPIRIES,
        "updated_at": "t",
        "tenant_id": TENANT,
        "job_id": JOB,
        "domain": "example.com",
        "robots_skip_factor": settings.CRAWL_ROBOTS_SKIP_FACTOR,
    }
    kwargs.update(overrides)
    return kwargs


def _domain_claim_kwargs(frontier: Frontier, domain: str, **overrides: object) -> dict[str, Any]:
    return _claim_kwargs(
        frontier,
        queue_key=queue_key(TENANT, JOB, domain),
        inflight_key=inflight_key(TENANT, JOB, domain),
        next_fetch_key=next_fetch_key(TENANT, JOB, domain),
        domain=domain,
        **overrides,
    )


def _finish_kwargs(**overrides: object) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "job_key": job_key(TENANT, JOB),
        "seen_key": seen_key(TENANT, JOB),
        "claims_key": claims_key(TENANT, JOB),
        "pages_key": pages_key(TENANT, JOB),
        "runnable_key": RUNNABLE_KEY,
        "entry": claim_entry(0, "example.com", "https://example.com/"),
        "outcome": "ok",
        "page_line": '{"url": "https://example.com/"}',
        "max_depth": 2,
        "retention": settings.CRAWL_JOB_RETENTION_SECONDS,
        "skipped_delta": 0,
        "tenant_id": TENANT,
        "job_id": JOB,
        "domain": "example.com",
        "links_json": "[]",
        "updated_at": "t",
        "member": MEMBER,
        "robots_skip_factor": settings.CRAWL_ROBOTS_SKIP_FACTOR,
    }
    kwargs.update(overrides)
    return kwargs


@pytest.fixture
def redis() -> FakeRedis:
    return FakeRedis(decode_responses=True)


@pytest.fixture
def frontier(redis: FakeRedis) -> Frontier:
    return Frontier(redis)


async def test_submit_writes_record_queues_seen_and_runnable(frontier: Frontier, redis: FakeRedis) -> None:
    # when
    await _submit(frontier)

    # then the record, both queues keys, the seen set and runnable exist together
    assert (await _record(redis))["state"] == "waiting"
    assert await redis.lrange(queue_key(TENANT, JOB, "example.com"), 0, -1) == ["0\thttps://example.com/"]
    assert await redis.sismember(seen_key(TENANT, JOB), "https://example.com/")
    assert await redis.zscore(RUNNABLE_KEY, MEMBER) == NOW
    assert await redis.ttl(job_key(TENANT, JOB)) > 0
    assert await redis.ttl(seen_key(TENANT, JOB)) > 0
    assert await redis.ttl(queue_key(TENANT, JOB, "example.com")) > 0


async def test_submit_normalizes_empty_map_patterns(frontier: Frontier, redis: FakeRedis) -> None:
    # given a record whose empty pattern lists already came back as maps
    await _submit(
        frontier,
        job_json=_job_json(request=_request_with_patterns(include_patterns={}, exclude_patterns={})),
    )

    # then the stored record carries the list shape again
    stored = await _record(redis)
    assert stored["request"]["include_patterns"] == []
    assert stored["request"]["exclude_patterns"] == []


async def test_first_claim_moves_job_to_running(frontier: Frontier, redis: FakeRedis) -> None:
    # given
    await _submit(frontier)

    # when
    answer = await frontier.claim(**_claim_kwargs(frontier))

    # then
    assert answer == ["claimed", "https://example.com/", "0"]
    assert (await _record(redis))["state"] == "running"


async def test_claim_heals_empty_map_patterns(frontier: Frontier, redis: FakeRedis) -> None:
    # given a submitted job whose record real Redis corrupted to maps
    await _submit(frontier)
    raw = await redis.get(job_key(TENANT, JOB))
    assert isinstance(raw, str)
    payload: dict[str, Any] = json.loads(raw)
    payload["request"] = _request_with_patterns(include_patterns={}, exclude_patterns={})
    await redis.set(job_key(TENANT, JOB), json.dumps(payload))

    # when it is claimed
    answer = await frontier.claim(**_claim_kwargs(frontier))

    # then the claim works and the record carries the list shape again
    assert answer == ["claimed", "https://example.com/", "0"]
    stored = await _record(redis)
    assert stored["request"]["include_patterns"] == []
    assert stored["request"]["exclude_patterns"] == []


async def test_claim_keeps_non_empty_patterns(frontier: Frontier, redis: FakeRedis) -> None:
    # given a submitted job with real pattern lists
    await _submit(
        frontier,
        job_json=_job_json(
            request=_request_with_patterns(include_patterns=["/keep/*"], exclude_patterns=["*/secret/*"])
        ),
    )

    # when it is claimed
    answer = await frontier.claim(**_claim_kwargs(frontier))

    # then the claim works and the lists are untouched
    assert answer == ["claimed", "https://example.com/", "0"]
    stored = await _record(redis)
    assert stored["request"]["include_patterns"] == ["/keep/*"]
    assert stored["request"]["exclude_patterns"] == ["*/secret/*"]


async def test_two_workers_never_claim_same_url(frontier: Frontier) -> None:
    # given one queued URL and two simulated instances
    await _submit(frontier, groups=_groups("https://example.com/only"))
    other = Frontier(frontier._client)

    # when both claim
    first = await frontier.claim(**_claim_kwargs(frontier))
    second = await other.claim(**_claim_kwargs(other))

    # then the second finds an empty queue
    assert first[0] == "claimed"
    assert second == ["empty"]


async def test_domain_cap_holds_for_both_instances_together(frontier: Frontier) -> None:
    # given two queued URLs of one domain and cap 1
    await _submit(frontier, groups=_groups("https://example.com/a", "https://example.com/b"))
    other = Frontier(frontier._client)

    # when both instances claim with cap 1
    first = await frontier.claim(**_claim_kwargs(frontier, domain_cap=1))
    second = await other.claim(**_claim_kwargs(other, domain_cap=1))

    # then the second is capped
    assert first[0] == "claimed"
    assert second == ["capped"]


async def test_crawl_delay_holds_through_next_fetch(frontier: Frontier) -> None:
    # given two queued URLs and a domain delay
    await _submit(frontier, groups=_groups("https://example.com/a", "https://example.com/b"))

    # when the first claim sets the next fetch time
    assert (await frontier.claim(**_claim_kwargs(frontier, delay_ms=5000)))[0] == "claimed"

    # then the second claim waits with the remaining delay
    assert await frontier.claim(**_claim_kwargs(frontier, delay_ms=5000)) == ["wait", "5000"]


async def test_page_budget_holds_for_both_instances_together(frontier: Frontier) -> None:
    # given a budget of 1 and two queued URLs
    await _submit(frontier, groups=_groups("https://example.com/a", "https://example.com/b"))

    # when the first page is claimed and finished
    assert (await frontier.claim(**_claim_kwargs(frontier, page_budget=1)))[0] == "claimed"
    entry = claim_entry(0, "example.com", "https://example.com/a")
    await frontier.finish(**_finish_kwargs(entry=entry))

    # then the second claim finds the budget bound and finalizes the job
    assert await frontier.claim(**_claim_kwargs(frontier, page_budget=1)) == [
        "budget",
        "succeeded",
    ]


async def test_budget_with_queued_remainder_finalizes_job_as_succeeded(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given a job already at its budget with queued URLs and no claims
    await _submit(
        frontier,
        job_json=_job_json(
            request=_request_with_patterns(page_budget=1),
            counts={
                "queued": 2,
                "fetched": 1,
                "unchanged": 0,
                "failed": 0,
                "skipped_unsafe": 0,
            },
            pending=2,
        ),
        groups=_groups("https://example.com/a", "https://example.com/b"),
    )

    # when the next claim finds the budget bound with a non-empty frontier
    answer = await frontier.claim(**_claim_kwargs(frontier, page_budget=1))

    # then the job finalizes instead of stalling in running
    assert answer == ["budget", "succeeded"]
    assert (await _record(redis))["state"] == "succeeded"
    assert await redis.zscore(RUNNABLE_KEY, MEMBER) is None


async def test_budget_with_inflight_claim_left_stays_on_budget(frontier: Frontier, redis: FakeRedis) -> None:
    # given a job at its budget while another claim is still in flight
    await _submit(
        frontier,
        job_json=_job_json(
            request=_request_with_patterns(page_budget=1),
            counts={
                "queued": 2,
                "fetched": 0,
                "unchanged": 0,
                "failed": 0,
                "skipped_unsafe": 0,
            },
            pending=2,
        ),
        groups=_groups("https://example.com/a", "https://example.com/b"),
    )
    assert (await frontier.claim(**_claim_kwargs(frontier, page_budget=10)))[0] == "claimed"
    raw = await redis.get(job_key(TENANT, JOB))
    assert isinstance(raw, str)
    payload: dict[str, Any] = json.loads(raw)
    payload["counts"]["fetched"] = 1
    await redis.set(job_key(TENANT, JOB), json.dumps(payload))

    # when the next claim finds the budget bound with a claim outstanding
    answer = await frontier.claim(**_claim_kwargs(frontier, page_budget=1))

    # then it backs off without finalizing
    assert answer == ["budget"]
    assert (await _record(redis))["state"] in ("waiting", "running")
    assert await redis.zscore(RUNNABLE_KEY, MEMBER) == NOW


async def test_finish_at_budget_with_queued_remainder_succeeds(frontier: Frontier, redis: FakeRedis) -> None:
    # given a budget of 1, two queued URLs and one claimed page
    await _submit(
        frontier,
        job_json=_job_json(
            request=_request_with_patterns(page_budget=1),
            counts={
                "queued": 2,
                "fetched": 0,
                "unchanged": 0,
                "failed": 0,
                "skipped_unsafe": 0,
            },
            pending=2,
        ),
        groups=_groups("https://example.com/a", "https://example.com/b"),
    )
    assert (await frontier.claim(**_claim_kwargs(frontier, page_budget=10)))[0] == "claimed"

    # when the claimed page finishes while one URL is still queued
    answer = await frontier.finish(
        **_finish_kwargs(entry=claim_entry(0, "example.com", "https://example.com/a"))
    )

    # then the job succeeds instead of stalling in running
    assert answer == ["succeeded"]
    assert (await _record(redis))["state"] == "succeeded"
    assert await redis.zscore(RUNNABLE_KEY, MEMBER) is None


async def test_finish_at_budget_with_inflight_left_stays_running(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given a budget of 1 with two claimed pages and one queued URL
    await _submit(
        frontier,
        job_json=_job_json(
            request=_request_with_patterns(page_budget=1),
            counts={
                "queued": 3,
                "fetched": 0,
                "unchanged": 0,
                "failed": 0,
                "skipped_unsafe": 0,
            },
            pending=3,
        ),
        groups=_groups("https://example.com/a", "https://example.com/b", "https://example.com/c"),
    )
    assert (await frontier.claim(**_claim_kwargs(frontier, page_budget=10)))[0] == "claimed"
    assert (await Frontier(redis).claim(**_claim_kwargs(frontier, page_budget=10)))[0] == "claimed"

    # when one of the two claims finishes at the budget
    answer = await frontier.finish(
        **_finish_kwargs(entry=claim_entry(0, "example.com", "https://example.com/a"))
    )

    # then the job stays running until the last claim drains
    assert answer == ["running"]
    assert (await _record(redis))["state"] in ("waiting", "running")


async def test_claim_on_missing_job_answers_gone(frontier: Frontier) -> None:
    assert await frontier.claim(**_claim_kwargs(frontier)) == ["gone"]


async def test_claim_on_cancelled_job_never_turns_back(frontier: Frontier) -> None:
    # given a cancelled job with a queued URL left behind
    await _submit(frontier, job_json=_job_json(state="cancelled"))

    # when
    answer = await frontier.claim(**_claim_kwargs(frontier))

    # then no claim happens
    assert answer == ["idle", "cancelled"]
    assert await frontier._client.llen(queue_key(TENANT, JOB, "example.com")) == 1


async def test_empty_queue_answers_empty(frontier: Frontier) -> None:
    # given a job with no queued URL
    await _submit(frontier, groups=json.dumps([{"domain": "example.com", "urls": []}]))
    record = _job_json()
    await frontier._client.set(job_key(TENANT, JOB), record)

    # when
    assert await frontier.claim(**_claim_kwargs(frontier)) == ["empty"]


async def test_expired_claim_returns_url_to_front_and_lowers_inflight(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given a claimed URL whose lease has passed
    await _submit(frontier, groups=_groups("https://example.com/a", "https://example.com/b"))
    assert (await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW, lease_ms=1000)))[0] == "claimed"
    assert await redis.get(inflight_key(TENANT, JOB, "example.com")) == "1"

    # when the next claim runs past the lease deadline
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 2000, lease_ms=1000))

    # then the same URL is claimed again and only one page is in flight
    assert answer == ["claimed", "https://example.com/a", "0"]
    assert await redis.get(inflight_key(TENANT, JOB, "example.com")) == "1"


async def test_claim_expiring_twice_counts_failed(frontier: Frontier, redis: FakeRedis) -> None:
    # given a claimed URL with the default of 2 expiries
    await _submit(frontier)
    assert (await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW, lease_ms=1000)))[0] == "claimed"

    # when the claim expires twice without a finish in between
    assert (await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 2000, lease_ms=1000)))[0] == "claimed"
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 4000, lease_ms=1000))

    # then the URL counts as failed and the job with nothing left ends failed
    assert answer == ["ended", "failed"]
    record = await _record(frontier._client)
    assert record["counts"]["failed"] == 1
    assert record["state"] == "failed"


async def test_setting_of_3_expiries_allows_third_claim(frontier: Frontier) -> None:
    # given a claim that already expired twice under a limit of 3
    await _submit(frontier)
    kwargs = _claim_kwargs(frontier, now_ms=NOW, lease_ms=1000, max_expiries=3)
    assert (await frontier.claim(**kwargs))[0] == "claimed"
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 2000, lease_ms=1000, max_expiries=3))
    assert answer[0] == "claimed"

    # when it expires a second time
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 4000, lease_ms=1000, max_expiries=3))

    # then the URL is requeued instead of failed
    assert answer[0] == "claimed"


def _two_domain_groups() -> str:
    return json.dumps(
        [
            {"domain": "example.com", "urls": [{"u": "https://example.com/a", "d": 0}]},
            {"domain": "other.org", "urls": [{"u": "https://other.org/b", "d": 0}]},
        ]
    )


async def _submit_two_domains(frontier: Frontier) -> None:
    await _submit(
        frontier,
        job_json=_job_json(
            domains=["example.com", "other.org"],
            counts={"queued": 2, "fetched": 0, "unchanged": 0, "failed": 0, "skipped_unsafe": 0},
            pending=2,
        ),
        groups=_two_domain_groups(),
    )


async def test_claim_entry_records_the_claimed_domain(frontier: Frontier, redis: FakeRedis) -> None:
    # given
    await _submit(frontier, groups=_groups("https://example.com/a"))

    # when
    await frontier.claim(**_claim_kwargs(frontier))

    # then the claim names the domain whose counter it raised
    assert await redis.zrange(claims_key(TENANT, JOB), 0, -1) == [
        claim_entry(0, "example.com", "https://example.com/a")
    ]


async def test_expired_claim_returns_to_its_own_domain(frontier: Frontier, redis: FakeRedis) -> None:
    # given a claim on other.org whose lease has passed
    await _submit_two_domains(frontier)
    claimed = await frontier.claim(**_domain_claim_kwargs(frontier, "other.org", now_ms=NOW, lease_ms=1000))
    assert claimed[0] == "claimed"

    # when a claim on example.com runs past that lease
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 2000, lease_ms=1000))

    # then the expired URL is back in the other.org queue with its counter lowered
    assert answer == ["claimed", "https://example.com/a", "0"]
    assert await redis.lrange(queue_key(TENANT, JOB, "other.org"), 0, -1) == ["0\thttps://other.org/b"]
    assert await redis.get(inflight_key(TENANT, JOB, "other.org")) == "0"
    assert await redis.get(inflight_key(TENANT, JOB, "example.com")) == "1"
    assert await redis.llen(queue_key(TENANT, JOB, "example.com")) == 0


async def test_claim_failed_by_expiry_lowers_its_own_domain_counter(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given a claim on other.org that may expire only once
    await _submit_two_domains(frontier)
    kwargs = _domain_claim_kwargs(frontier, "other.org", now_ms=NOW, lease_ms=1000, max_expiries=1)
    assert (await frontier.claim(**kwargs))[0] == "claimed"

    # when a claim on example.com runs past that lease
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 2000, lease_ms=1000, max_expiries=1))

    # then the URL counts failed, its counter is back to zero and the job runs on
    assert answer[0] == "claimed"
    assert await redis.get(inflight_key(TENANT, JOB, "other.org")) == "0"
    assert await redis.llen(queue_key(TENANT, JOB, "other.org")) == 0
    record = await _record(redis)
    assert record["counts"]["failed"] == 1
    assert record["pending"] == 1
    assert record["state"] == "running"


async def test_claim_ends_job_failed_when_its_last_url_fails_by_expiry(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given the only URL of a job claimed with a single allowed expiry
    await _submit(frontier, groups=_groups("https://example.com/a"))
    assert (await frontier.claim(**_claim_kwargs(frontier, lease_ms=1000, max_expiries=1)))[0] == "claimed"

    # when the next claim runs past the lease
    answer = await frontier.claim(
        **_claim_kwargs(frontier, now_ms=NOW + 2000, lease_ms=1000, max_expiries=1, updated_at="t2")
    )

    # then the job ends failed exactly as the finish script ends it
    assert answer == ["ended", "failed"]
    record = await _record(redis)
    assert record["state"] == "failed"
    assert record["error"] == ALL_PAGES_FAILED_ERROR
    assert record["pending"] == 0
    assert record["updated_at"] == "t2"
    assert await redis.get(inflight_key(TENANT, JOB, "example.com")) == "0"
    assert await redis.zscore(RUNNABLE_KEY, MEMBER) is None


async def test_claim_ends_job_succeeded_when_last_url_fails_after_a_fetched_page(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given one fetched page and one claimed URL left with a single allowed expiry
    await _submit(frontier, groups=_groups("https://example.com/a", "https://example.com/b"))
    assert (await frontier.claim(**_claim_kwargs(frontier)))[0] == "claimed"
    await frontier.finish(**_finish_kwargs(entry=claim_entry(0, "example.com", "https://example.com/a")))
    assert (await frontier.claim(**_claim_kwargs(frontier, lease_ms=1000, max_expiries=1)))[0] == "claimed"

    # when the next claim runs past the lease
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 2000, lease_ms=1000, max_expiries=1))

    # then the job ends succeeded
    assert answer == ["ended", "succeeded"]
    record = await _record(redis)
    assert record["state"] == "succeeded"
    assert record.get("error") is None


async def test_legacy_claim_entry_without_domain_returns_to_claiming_domain(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given a claim written before claims named their domain
    await _submit(frontier, groups=json.dumps([{"domain": "example.com", "urls": []}]))
    await redis.set(job_key(TENANT, JOB), _job_json(pending=1, state="running"))
    await redis.zadd(claims_key(TENANT, JOB), {"0\thttps://example.com/old": NOW - 1})
    await redis.set(inflight_key(TENANT, JOB, "example.com"), 1)

    # when the next claim takes it back
    answer = await frontier.claim(**_claim_kwargs(frontier))

    # then it is requeued and claimed again on the claiming domain
    assert answer == ["claimed", "https://example.com/old", "0"]
    assert await redis.get(inflight_key(TENANT, JOB, "example.com")) == "1"


async def test_concurrent_claims_never_exceed_page_budget(frontier: Frontier) -> None:
    # given three queued URLs, a budget of two and room for every claim
    await _submit(
        frontier,
        groups=_groups("https://example.com/a", "https://example.com/b", "https://example.com/c"),
    )
    other = Frontier(frontier._client)

    # when three claims arrive before any page finishes
    first = await frontier.claim(**_claim_kwargs(frontier, page_budget=2, domain_cap=5))
    second = await other.claim(**_claim_kwargs(other, page_budget=2, domain_cap=5))
    third = await frontier.claim(**_claim_kwargs(frontier, page_budget=2, domain_cap=5))

    # then the claims in flight count against the budget
    assert first[0] == "claimed"
    assert second[0] == "claimed"
    assert third == ["budget"]


async def test_claim_at_budget_with_every_page_failed_ends_failed(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given a job at its budget whose only finished page failed
    await _submit(
        frontier,
        job_json=_job_json(
            counts={"queued": 1, "fetched": 0, "unchanged": 0, "failed": 1, "skipped_unsafe": 0},
            pending=1,
        ),
        groups=_groups("https://example.com/b"),
    )

    # when the next claim finds the budget bound
    answer = await frontier.claim(**_claim_kwargs(frontier, page_budget=1))

    # then the job ends failed
    assert answer == ["budget", "failed"]
    assert (await _record(redis))["state"] == "failed"


def _skipped_job(robots_skipped: int, *, fetched: int = 1) -> str:
    return _job_json(
        counts={
            "queued": 1,
            "fetched": fetched,
            "unchanged": 0,
            "failed": 0,
            "skipped_unsafe": 0,
            "robots_skipped": robots_skipped,
        },
        pending=1,
    )


async def test_claim_at_the_robots_skip_ceiling_ends_the_job(frontier: Frontier, redis: FakeRedis) -> None:
    # given a budget of 2, a factor of 10 and 20 pages skipped for robots.txt
    await _submit(frontier, job_json=_skipped_job(20), groups=_groups("https://example.com/b"))

    # when
    answer = await frontier.claim(**_claim_kwargs(frontier, page_budget=2, robots_skip_factor=10))

    # then
    assert answer == ["budget", "succeeded"]
    assert (await _record(redis))["state"] == "succeeded"


async def test_claim_below_the_robots_skip_ceiling_goes_on(frontier: Frontier) -> None:
    # given
    await _submit(frontier, job_json=_skipped_job(19), groups=_groups("https://example.com/b"))

    # when
    answer = await frontier.claim(**_claim_kwargs(frontier, page_budget=2, robots_skip_factor=10))

    # then
    assert answer[0] == "claimed"


async def test_claim_at_the_robots_skip_ceiling_with_a_claim_in_flight_waits_for_it(
    frontier: Frontier,
) -> None:
    # given a job at the ceiling with one page still claimed
    await _submit(
        frontier,
        job_json=_skipped_job(20),
        groups=_groups("https://example.com/a", "https://example.com/b"),
    )
    assert (
        await frontier.claim(**_claim_kwargs(frontier, page_budget=5, domain_cap=5, robots_skip_factor=100))
    )[0] == "claimed"

    # when
    answer = await frontier.claim(
        **_claim_kwargs(frontier, page_budget=2, domain_cap=5, robots_skip_factor=10)
    )

    # then
    assert answer == ["budget"]


async def test_finish_reaching_the_robots_skip_ceiling_ends_the_job(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given 19 skips, a budget of 2 and queued links still waiting
    request = _request_with_patterns(page_budget=2)
    job = json.loads(_skipped_job(19))
    job["request"] = request
    job["pending"] = 5
    await _submit(frontier, job_json=json.dumps(job))
    assert (await frontier.claim(**_claim_kwargs(frontier, page_budget=2, robots_skip_factor=10)))[
        0
    ] == "claimed"

    # when the 20th skip finishes
    answer = await frontier.finish(**_finish_kwargs(outcome="robots_skipped", robots_skip_factor=10))

    # then
    assert answer == ["succeeded"]
    assert (await _record(redis))["counts"]["robots_skipped"] == 20


async def test_finish_below_the_robots_skip_ceiling_keeps_the_job_running(frontier: Frontier) -> None:
    # given
    job = json.loads(_skipped_job(18))
    job["request"] = _request_with_patterns(page_budget=2)
    job["pending"] = 5
    await _submit(frontier, job_json=json.dumps(job))
    assert (await frontier.claim(**_claim_kwargs(frontier, page_budget=2, robots_skip_factor=10)))[
        0
    ] == "claimed"

    # when
    answer = await frontier.finish(**_finish_kwargs(outcome="robots_skipped", robots_skip_factor=10))

    # then
    assert answer == ["running"]


@pytest.mark.parametrize("refusal", ["capped", "wait", "empty", "budget"])
async def test_refused_claim_keeps_the_job_record_lifetime(
    frontier: Frontier, redis: FakeRedis, refusal: str
) -> None:
    # given a job whose record has little lifetime left and a claim that will be refused
    await _submit(frontier, groups=_groups("https://example.com/a", "https://example.com/b"))
    overrides: dict[str, object] = {}
    if refusal == "capped":
        await redis.set(inflight_key(TENANT, JOB, "example.com"), 2)
        overrides["domain_cap"] = 2
    elif refusal == "wait":
        await redis.set(next_fetch_key(TENANT, JOB, "example.com"), NOW + 5000)
    elif refusal == "empty":
        await redis.delete(queue_key(TENANT, JOB, "example.com"))
    else:
        assert (await frontier.claim(**_claim_kwargs(frontier)))[0] == "claimed"
        overrides["page_budget"] = 1
    await redis.expire(job_key(TENANT, JOB), 100)

    # when the claim is refused
    answer = await frontier.claim(**_claim_kwargs(frontier, **overrides))

    # then the record is not renewed, so a job nobody can progress still expires
    assert answer[0] == refusal
    assert 0 < await redis.ttl(job_key(TENANT, JOB)) <= 100


async def test_refused_claim_that_took_back_a_claim_saves_the_record(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given an expired claim and a domain at its cap
    await _submit(frontier, groups=_groups("https://example.com/a", "https://example.com/b"))
    assert (await frontier.claim(**_claim_kwargs(frontier, lease_ms=1000)))[0] == "claimed"
    await redis.set(inflight_key(TENANT, JOB, "example.com"), 3)

    # when a capped claim runs past the lease
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 2000, lease_ms=1000, domain_cap=2))

    # then the take-back is saved in the record
    assert answer == ["capped"]
    record = await _record(redis)
    assert record["claim_expiries"] == {"https://example.com/a": 1}
    assert record["counts"]["queued"] == 2


async def test_claim_keeps_existing_expiry_counts(frontier: Frontier) -> None:
    # given a job whose URL already expired once under a limit of 3
    await _submit(frontier, job_json=_job_json(claim_expiries={"https://example.com/": 1}, pending=2))
    await frontier._client.rpush(queue_key(TENANT, JOB, "example.com"), "0\thttps://example.com/")

    # when it is claimed and expires again
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW, lease_ms=1000, max_expiries=3))
    assert answer[0] == "claimed"
    answer = await frontier.claim(**_claim_kwargs(frontier, now_ms=NOW + 2000, lease_ms=1000, max_expiries=3))

    # then the earlier count is kept and the URL is requeued, not failed
    assert answer[0] == "claimed"
    record = await _record(frontier._client)
    assert record["counts"]["failed"] == 0


async def test_finish_appends_page_and_counts_and_queues_only_unseen(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given a claimed URL
    await _submit(frontier, groups=_groups("https://example.com/a"))
    assert (await frontier.claim(**_claim_kwargs(frontier)))[0] == "claimed"

    # when it finishes with a new link and a seen link
    links = json.dumps(
        [
            {"u": "https://example.com/new", "d": 1, "domain": "example.com"},
            {"u": "https://example.com/a", "d": 1, "domain": "example.com"},
        ]
    )
    answer = await frontier.finish(
        **_finish_kwargs(entry=claim_entry(0, "example.com", "https://example.com/a"), links_json=links)
    )

    # then the page is appended, only the unseen link is queued and the job runs on
    assert answer == ["running"]
    assert await redis.lrange(pages_key(TENANT, JOB), 0, -1) == ['{"url": "https://example.com/"}']
    assert await redis.lrange(queue_key(TENANT, JOB, "example.com"), 0, -1) == ["1\thttps://example.com/new"]
    record = await _record(frontier._client)
    assert record["counts"] == {
        "queued": 1,
        "fetched": 1,
        "unchanged": 0,
        "failed": 0,
        "skipped_unsafe": 0,
    }
    assert record["pending"] == 1


async def test_finish_moves_to_succeeded_when_nothing_is_left(frontier: Frontier, redis: FakeRedis) -> None:
    # given the last claimed URL of a job
    await _submit(frontier)
    assert (await frontier.claim(**_claim_kwargs(frontier)))[0] == "claimed"

    # when it finishes with no new links
    answer = await frontier.finish(**_finish_kwargs())

    # then the job succeeds and leaves the runnable set
    assert answer == ["succeeded"]
    assert (await _record(redis))["state"] == "succeeded"
    assert await redis.zscore(RUNNABLE_KEY, MEMBER) is None


async def test_finish_ends_job_failed_when_every_page_failed(frontier: Frontier, redis: FakeRedis) -> None:
    # given the last claimed URL of a job
    await _submit(frontier)
    assert (await frontier.claim(**_claim_kwargs(frontier)))[0] == "claimed"

    # when it finishes failed with nothing left
    answer = await frontier.finish(**_finish_kwargs(outcome="failed", page_line=""))

    # then the job ends failed with its error and leaves the runnable set
    assert answer == ["failed"]
    record = await _record(redis)
    assert record["state"] == "failed"
    assert record["error"] == ALL_PAGES_FAILED_ERROR
    assert await redis.zscore(RUNNABLE_KEY, MEMBER) is None


async def test_finish_at_budget_with_every_page_failed_ends_failed(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given a budget of 1 with one URL still queued behind the claimed one
    await _submit(
        frontier,
        job_json=_job_json(
            request=_request_with_patterns(page_budget=1),
            counts={"queued": 2, "fetched": 0, "unchanged": 0, "failed": 0, "skipped_unsafe": 0},
            pending=2,
        ),
        groups=_groups("https://example.com/a", "https://example.com/b"),
    )
    assert (await frontier.claim(**_claim_kwargs(frontier, page_budget=10)))[0] == "claimed"

    # when the claimed page fails at the budget
    answer = await frontier.finish(
        **_finish_kwargs(
            entry=claim_entry(0, "example.com", "https://example.com/a"), outcome="failed", page_line=""
        )
    )

    # then the job ends failed
    assert answer == ["failed"]
    assert (await _record(redis))["state"] == "failed"


async def test_finish_heals_empty_map_patterns(frontier: Frontier, redis: FakeRedis) -> None:
    # given a claimed URL whose record real Redis corrupted to maps
    await _submit(frontier)
    assert (await frontier.claim(**_claim_kwargs(frontier)))[0] == "claimed"
    raw = await redis.get(job_key(TENANT, JOB))
    assert isinstance(raw, str)
    payload: dict[str, Any] = json.loads(raw)
    payload["request"] = _request_with_patterns(include_patterns={}, exclude_patterns={})
    await redis.set(job_key(TENANT, JOB), json.dumps(payload))

    # when it finishes with no new links
    answer = await frontier.finish(**_finish_kwargs())

    # then the job succeeds and the record carries the list shape again
    assert answer == ["succeeded"]
    stored = await _record(redis)
    assert stored["request"]["include_patterns"] == []
    assert stored["request"]["exclude_patterns"] == []


async def test_finish_counts_unchanged_failed_and_skipped(frontier: Frontier, redis: FakeRedis) -> None:
    # given a claimed URL with one more waiting behind it
    await _submit(frontier, groups=_groups("https://example.com/a", "https://example.com/b"))
    claimed = await frontier.claim(**_claim_kwargs(frontier))
    assert claimed[0] == "claimed"

    # when it finishes unchanged with two skipped unsafe links and no stored line
    entry = claim_entry(claimed[2], "example.com", claimed[1])
    answer = await frontier.finish(
        **_finish_kwargs(entry=entry, outcome="unchanged", page_line="", skipped_delta=2)
    )

    # then nothing is appended but the counts move
    assert answer == ["running"]
    assert await redis.llen(pages_key(TENANT, JOB)) == 0
    record = await _record(frontier._client)
    assert record["counts"]["unchanged"] == 1
    assert record["counts"]["skipped_unsafe"] == 2


async def test_finish_failed_outcome_counts_failed(frontier: Frontier, redis: FakeRedis) -> None:
    # given a claimed URL with one more waiting behind it
    await _submit(frontier, groups=_groups("https://example.com/a", "https://example.com/b"))
    claimed = await frontier.claim(**_claim_kwargs(frontier))
    assert claimed[0] == "claimed"

    # when it finishes failed
    answer = await frontier.finish(
        **_finish_kwargs(
            entry=claim_entry(claimed[2], "example.com", claimed[1]), outcome="failed", page_line=""
        )
    )

    # then the job fails the page and stays running on the empty frontier
    assert answer == ["running"]
    record = await _record(frontier._client)
    assert record["counts"]["failed"] == 1


async def test_finish_ignores_links_beyond_max_depth(frontier: Frontier, redis: FakeRedis) -> None:
    # given a claimed URL
    await _submit(frontier)
    assert (await frontier.claim(**_claim_kwargs(frontier)))[0] == "claimed"

    # when a link deeper than max_depth finishes with the page
    links = json.dumps([{"u": "https://example.com/deep", "d": 9, "domain": "example.com"}])
    await frontier.finish(**_finish_kwargs(links_json=links))

    # then it is never queued but the job still succeeds
    assert await redis.llen(queue_key(TENANT, JOB, "example.com")) == 0


async def test_finish_tracks_new_domains(frontier: Frontier, redis: FakeRedis) -> None:
    # given a claimed URL
    await _submit(frontier)
    assert (await frontier.claim(**_claim_kwargs(frontier)))[0] == "claimed"

    # when a link of a new domain finishes with the page
    links = json.dumps([{"u": "https://other.com/", "d": 1, "domain": "other.com"}])
    await frontier.finish(**_finish_kwargs(links_json=links))

    # then the new domain queue holds it and the job tracks the domain
    assert await redis.lrange(queue_key(TENANT, JOB, "other.com"), 0, -1) == ["1\thttps://other.com/"]
    record = await _record(frontier._client)
    assert "other.com" in record["domains"]


async def test_finish_on_missing_job_answers_gone(frontier: Frontier) -> None:
    assert await frontier.finish(**_finish_kwargs()) == ["gone"]


async def test_finish_on_cancelled_job_writes_nothing(frontier: Frontier, redis: FakeRedis) -> None:
    # given a cancelled job that still holds a claim
    await _submit(frontier, job_json=_job_json(state="cancelled"))
    await redis.zadd(
        claims_key(TENANT, JOB), {claim_entry(0, "example.com", "https://example.com/"): NOW + 1000}
    )

    # when the late page finishes
    answer = await frontier.finish(**_finish_kwargs())

    # then nothing is written
    assert answer == ["cancelled"]
    assert await redis.llen(pages_key(TENANT, JOB)) == 0


@pytest.mark.parametrize(
    "stored_claim",
    [
        claim_entry(0, "example.com", "https://example.com/"),
        "0\thttps://example.com/",
    ],
    ids=["three-field", "two-field-from-older-instance"],
)
async def test_finish_matches_claim_in_either_format(
    frontier: Frontier, redis: FakeRedis, stored_claim: str
) -> None:
    # given a running job whose only claim was written in the stored format
    await _submit(frontier)
    await redis.set(job_key(TENANT, JOB), _job_json(pending=1, state="running"))
    await redis.zadd(claims_key(TENANT, JOB), {stored_claim: NOW + 1000})
    await redis.set(inflight_key(TENANT, JOB, "example.com"), 1)

    # when a new worker finishes it with the three-field entry
    answer = await frontier.finish(**_finish_kwargs())

    # then the claim is released and the page is counted
    assert answer == ["succeeded"]
    assert await redis.zcard(claims_key(TENANT, JOB)) == 0
    assert await redis.get(inflight_key(TENANT, JOB, "example.com")) == "0"
    assert await redis.lrange(pages_key(TENANT, JOB), 0, -1) == ['{"url": "https://example.com/"}']
    assert (await _record(redis))["counts"]["fetched"] == 1


async def test_finish_on_succeeded_job_answers_stale(frontier: Frontier) -> None:
    # given
    await _submit(frontier, job_json=_job_json(state="succeeded"))

    # when / then
    assert await frontier.finish(**_finish_kwargs()) == ["stale", "succeeded"]


async def test_finish_without_claim_answers_stale(frontier: Frontier) -> None:
    # given a job with no claim on the finished URL
    await _submit(frontier)

    # when / then
    assert await frontier.finish(**_finish_kwargs()) == ["stale"]


async def test_concurrent_instances_lose_no_update(frontier: Frontier, redis: FakeRedis) -> None:
    # given one job with four URLs and two simulated instances
    await _submit(
        frontier,
        groups=_groups(
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
            "https://example.com/4",
        ),
    )
    other = Frontier(redis)
    instances = [frontier, other]

    # when the instances interleave claims and finishes
    for round_index in range(2):
        entries: list[str] = []
        for index in range(2):
            answer = await instances[index % 2].claim(**_claim_kwargs(instances[index % 2]))
            assert answer[0] == "claimed"
            entries.append(claim_entry(answer[2], "example.com", answer[1]))
        for position, entry in enumerate(entries):
            done = await instances[position % 2].finish(
                **_finish_kwargs(entry=entry, page_line=f'{{"n": {round_index}}}')
            )
            assert done == (["succeeded"] if round_index == 1 and position == 1 else ["running"])

    # then every page is counted exactly once
    record = await _record(frontier._client)
    assert record["counts"]["fetched"] == 4
    assert record["counts"]["queued"] == 0
    assert record["state"] == "succeeded"
    assert await redis.llen(pages_key(TENANT, JOB)) == 4


async def test_cancel_moves_to_cancelled_and_deletes_frontier_keys(
    frontier: Frontier, redis: FakeRedis
) -> None:
    # given a running job
    await _submit(frontier)
    await frontier.claim(**_claim_kwargs(frontier))

    # when it is cancelled through another instance
    answer = await Frontier(redis).cancel(
        job_key=job_key(TENANT, JOB),
        seen_key=seen_key(TENANT, JOB),
        claims_key=claims_key(TENANT, JOB),
        pages_key=pages_key(TENANT, JOB),
        runnable_key=RUNNABLE_KEY,
        updated_at="2026-10-19T00:00:00+00:00",
        retention=settings.CRAWL_JOB_RETENTION_SECONDS,
        tenant_id=TENANT,
        job_id=JOB,
        member=MEMBER,
    )

    # then the record is cancelled and every frontier key is gone
    assert answer == ["cancelled"]
    assert (await _record(redis))["state"] == "cancelled"
    assert (
        await redis.exists(
            queue_key(TENANT, JOB, "example.com"),
            inflight_key(TENANT, JOB, "example.com"),
            next_fetch_key(TENANT, JOB, "example.com"),
            seen_key(TENANT, JOB),
            claims_key(TENANT, JOB),
            pages_key(TENANT, JOB),
        )
        == 0
    )
    assert await redis.zscore(RUNNABLE_KEY, MEMBER) is None


async def test_cancel_on_missing_job_answers_gone(frontier: Frontier) -> None:
    answer = await frontier.cancel(
        job_key=job_key(TENANT, JOB),
        seen_key=seen_key(TENANT, JOB),
        claims_key=claims_key(TENANT, JOB),
        pages_key=pages_key(TENANT, JOB),
        runnable_key=RUNNABLE_KEY,
        updated_at="2026-10-19T00:00:00+00:00",
        retention=settings.CRAWL_JOB_RETENTION_SECONDS,
        tenant_id=TENANT,
        job_id=JOB,
        member=MEMBER,
    )
    assert answer == ["gone"]


async def test_cancel_on_terminal_job_answers_idle(frontier: Frontier) -> None:
    # given
    await _submit(frontier, job_json=_job_json(state="succeeded"))

    # when / then
    answer = await frontier.cancel(
        job_key=job_key(TENANT, JOB),
        seen_key=seen_key(TENANT, JOB),
        claims_key=claims_key(TENANT, JOB),
        pages_key=pages_key(TENANT, JOB),
        runnable_key=RUNNABLE_KEY,
        updated_at="2026-10-19T00:00:00+00:00",
        retention=settings.CRAWL_JOB_RETENTION_SECONDS,
        tenant_id=TENANT,
        job_id=JOB,
        member=MEMBER,
    )
    assert answer == ["idle", "succeeded"]


async def test_add_urls_queues_only_unseen(frontier: Frontier, redis: FakeRedis) -> None:
    # given a submitted job
    await _submit(frontier)

    # when sitemap URLs arrive with one duplicate
    links = json.dumps(
        [
            {"u": "https://example.com/s1", "d": 1, "domain": "example.com"},
            {"u": "https://example.com/", "d": 1, "domain": "example.com"},
        ]
    )
    answer = await frontier.add_urls(
        job_key=job_key(TENANT, JOB),
        seen_key=seen_key(TENANT, JOB),
        updated_at="2026-10-19T00:00:00+00:00",
        retention=settings.CRAWL_JOB_RETENTION_SECONDS,
        tenant_id=TENANT,
        job_id=JOB,
        links_json=links,
    )

    # then only the unseen URL is queued
    assert answer == ["added", "1"]
    assert await redis.lrange(queue_key(TENANT, JOB, "example.com"), 0, -1) == [
        "0\thttps://example.com/",
        "1\thttps://example.com/s1",
    ]


async def test_add_urls_on_missing_job_answers_gone(frontier: Frontier) -> None:
    answer = await frontier.add_urls(
        job_key=job_key(TENANT, JOB),
        seen_key=seen_key(TENANT, JOB),
        updated_at="2026-10-19T00:00:00+00:00",
        retention=settings.CRAWL_JOB_RETENTION_SECONDS,
        tenant_id=TENANT,
        job_id=JOB,
        links_json="[]",
    )
    assert answer == ["gone"]


async def test_add_urls_on_terminal_job_answers_idle(frontier: Frontier) -> None:
    # given
    await _submit(frontier, job_json=_job_json(state="failed"))

    # when / then
    answer = await frontier.add_urls(
        job_key=job_key(TENANT, JOB),
        seen_key=seen_key(TENANT, JOB),
        updated_at="2026-10-19T00:00:00+00:00",
        retention=settings.CRAWL_JOB_RETENTION_SECONDS,
        tenant_id=TENANT,
        job_id=JOB,
        links_json="[]",
    )
    assert answer == ["idle", "failed"]


async def test_set_index_key_on_succeeded_job(frontier: Frontier, redis: FakeRedis) -> None:
    # given
    await _submit(frontier, job_json=_job_json(state="succeeded"))

    # when
    answer = await frontier.set_index_key(
        job_key=job_key(TENANT, JOB),
        updated_at="2026-10-19T00:00:00+00:00",
        retention=60,
        index_key="tenant/acme/x",
    )
    assert answer == ["ok"]

    # then
    assert (await _record(redis))["pages_ndjson_key"] == "tenant/acme/x"


async def test_set_index_key_on_missing_job_answers_gone(frontier: Frontier) -> None:
    assert await frontier.set_index_key(
        job_key=job_key(TENANT, JOB), updated_at="2026-10-19T00:00:00+00:00", retention=60, index_key="x"
    ) == ["gone"]


async def test_set_index_key_on_running_job_answers_idle(frontier: Frontier) -> None:
    # given
    await _submit(frontier)

    # when / then
    assert await frontier.set_index_key(
        job_key=job_key(TENANT, JOB), updated_at="2026-10-19T00:00:00+00:00", retention=60, index_key="x"
    ) == ["idle", "waiting"]


async def test_list_and_remove_runnable_and_read_pages(frontier: Frontier, redis: FakeRedis) -> None:
    # given
    await _submit(frontier)

    # when / then
    assert await frontier.list_runnable() == [MEMBER]
    assert await frontier.read_pages(pages_key(TENANT, JOB)) == []
    await frontier.remove_runnable_member(MEMBER)
    assert await frontier.list_runnable() == []


async def test_delete_frontier_removes_every_key(frontier: Frontier, redis: FakeRedis) -> None:
    # given a finished job with pages left
    await _submit(frontier)
    await frontier.claim(**_claim_kwargs(frontier))
    await frontier.finish(**_finish_kwargs())

    # when
    await frontier.delete_frontier(TENANT, JOB, ["example.com"])

    # then every key of the job is gone
    assert (
        await redis.exists(
            queue_key(TENANT, JOB, "example.com"),
            inflight_key(TENANT, JOB, "example.com"),
            next_fetch_key(TENANT, JOB, "example.com"),
            seen_key(TENANT, JOB),
            claims_key(TENANT, JOB),
            pages_key(TENANT, JOB),
        )
        == 0
    )


async def _finish_skipped(redis: FakeRedis, record: str) -> list[str]:
    await redis.set(job_key(TENANT, JOB), record)
    await redis.zadd(claims_key(TENANT, JOB), {claim_entry(0, "example.com", "https://example.com/a"): 1})
    return await Frontier(redis).finish(
        job_key=job_key(TENANT, JOB),
        seen_key=seen_key(TENANT, JOB),
        claims_key=claims_key(TENANT, JOB),
        pages_key=pages_key(TENANT, JOB),
        runnable_key=RUNNABLE_KEY,
        entry=claim_entry(0, "example.com", "https://example.com/a"),
        outcome="robots_skipped",
        page_line='{"status":"skipped"}',
        max_depth=2,
        retention=60,
        skipped_delta=0,
        tenant_id=TENANT,
        job_id=JOB,
        domain="example.com",
        links_json="[]",
        updated_at="t2",
        member=runnable_member(TENANT, JOB),
        robots_skip_factor=10,
    )


async def test_finish_counts_a_robots_skip_apart_from_failed_and_outside_the_budget(redis: FakeRedis) -> None:
    # given a running job with one page left and a budget one finished page away
    counts = {
        "queued": 0,
        "fetched": 1,
        "unchanged": 0,
        "failed": 0,
        "skipped_unsafe": 0,
        "robots_skipped": 2,
    }
    job = _job_json(
        state="running",
        counts=counts,
        request={**_request_with_patterns(), "page_budget": 2},
        pending=2,
    )

    # when
    answer = await _finish_skipped(redis, job)

    # then the job keeps running, because the skip did not reach the budget
    assert answer == ["running"]
    stored = json.loads(str(await redis.get(job_key(TENANT, JOB))))
    assert stored["counts"]["robots_skipped"] == 3
    assert stored["counts"]["failed"] == 0
    assert stored["pending"] == 1
    assert await redis.lrange(pages_key(TENANT, JOB), 0, -1) == ['{"status":"skipped"}']


async def test_finish_reads_a_record_written_before_the_robots_skip_count_existed(redis: FakeRedis) -> None:
    # given a job record without the count, and one last page
    counts = {"queued": 0, "fetched": 1, "unchanged": 0, "failed": 0, "skipped_unsafe": 0}
    job = _job_json(state="running", counts=counts, pending=1)

    # when
    answer = await _finish_skipped(redis, job)

    # then the job ends and the count starts from zero
    assert answer == ["succeeded"]
    stored = json.loads(str(await redis.get(job_key(TENANT, JOB))))
    assert stored["counts"]["robots_skipped"] == 1
