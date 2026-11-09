import json
import logging
from typing import Any

import pytest
from botocore.exceptions import ClientError, EndpointConnectionError
from fakeredis.aioredis import FakeRedis
from prometheus_client import REGISTRY

from src.config.config import settings
from src.crawl import result_store as result_store_module
from src.crawl.models import CrawlRequest
from src.crawl.result_store import (
    ExpiryRuleStatus,
    RecrawlStore,
    ResultStore,
    index_object_key,
    normalize_url,
    page_extension,
    page_object_key,
    recrawl_scope,
)


def test_normalize_url_lowercases_and_drops_fragment() -> None:
    assert normalize_url("HTTPS://Example.COM:443/Path?x=1#frag") == "https://example.com:443/Path?x=1"
    assert normalize_url("https://example.com/a") == "https://example.com/a"


def _request(**fields: Any) -> CrawlRequest:
    values: dict[str, Any] = {"seeds": ["https://a.example/", "https://b.example/"]}
    values.update(fields)
    return CrawlRequest(**values)


def test_recrawl_scope_sorts_inputs() -> None:
    assert recrawl_scope(
        _request(seeds=["https://b.example/", "https://a.example/"], include_patterns=["/y", "/x"])
    ) == recrawl_scope(_request(include_patterns=["/x", "/y"]))
    assert recrawl_scope(_request(exclude_patterns=["/q", "/p"])) == recrawl_scope(
        _request(exclude_patterns=["/p", "/q"])
    )


@pytest.mark.parametrize(
    "changed",
    [
        {"seeds": ["https://a.example/"]},
        {"include_patterns": ["/y"]},
        {"exclude_patterns": ["/y"]},
        {"output_format": "structured"},
        {"output_format": "schema", "extraction_schema": {"type": "object"}},
        {"profile": "work"},
    ],
)
def test_recrawl_scope_changes_with_every_option_that_shapes_a_stored_page(changed: dict[str, Any]) -> None:
    assert recrawl_scope(_request(**changed)) != recrawl_scope(_request())


def test_recrawl_scope_separates_extraction_schemas() -> None:
    first = _request(output_format="schema", extraction_schema={"type": "object"})
    second = _request(output_format="schema", extraction_schema={"type": "array"})
    assert recrawl_scope(first) != recrawl_scope(second)


@pytest.mark.parametrize(
    "unchanged",
    [{"page_budget": 7}, {"max_depth": 1}, {"same_domain_only": False}, {"respect_robots": True}],
)
def test_recrawl_scope_ignores_options_the_stored_page_does_not_depend_on(unchanged: dict[str, Any]) -> None:
    assert recrawl_scope(_request(**unchanged)) == recrawl_scope(_request())


def test_page_extension_json_for_schema() -> None:
    assert page_extension("schema") == ".json"
    assert page_extension("text") == ".md"


def test_object_keys_carry_tenant_and_prefix() -> None:
    key = page_object_key("acme", "j1", "https://example.com/a?x=1#f", "text")
    assert key.startswith("tenant/acme/crawl-results/j1/pages/")
    assert key.endswith(".md")
    assert index_object_key("acme", "j1") == "tenant/acme/crawl-results/j1/pages.ndjson"


class _FakeObjects:
    def __init__(self) -> None:
        self.text: dict[str, str] = {}
        self.copied: list[tuple[str, str]] = []
        self.expiry_calls: list[tuple[str, str, int]] = []

    async def ensure_bucket(self, bucket: str) -> None:
        return None

    async def set_expiry(self, bucket: str, prefix: str, days: int) -> None:
        self.expiry_calls.append((bucket, prefix, days))

    async def put_text(self, bucket: str, key: str, text: str) -> None:
        self.text[key] = text

    async def get_text(self, bucket: str, key: str) -> str | None:
        return self.text.get(key)

    async def head(self, bucket: str, key: str) -> bool:
        return key in self.text

    async def delete(self, bucket: str, key: str) -> None:
        self.text.pop(key, None)

    async def copy_inside_bucket(self, bucket: str, source_key: str, dest_key: str) -> None:
        self.text[dest_key] = self.text[source_key]
        self.copied.append((source_key, dest_key))

    async def put_bytes(self, bucket: str, key: str, body: bytes) -> None:
        self.text[key] = body.decode("utf-8")


@pytest.fixture
def results() -> ResultStore:
    return ResultStore(_FakeObjects())  # type: ignore[arg-type]


async def test_write_and_read_page(results: ResultStore) -> None:
    # when
    await results.write_page("k", "hello")

    # then the key starts with the tenant and the content round-trips
    assert await results.read_page("k") == "hello"
    assert await results.page_exists("k") is True
    assert await results.page_exists("missing") is False
    assert await results.read_page("missing") is None


async def test_copy_page_forward(results: ResultStore) -> None:
    # given
    await results.write_page("src", "hello")

    # when
    await results.copy_page_forward("src", "dst")

    # then the bytes are shared without a re-upload
    assert await results.read_page("dst") == "hello"


async def test_write_and_read_index(results: ResultStore) -> None:
    # given
    lines = [{"url": "https://example.com/", "status": "fetched"}]

    # when
    await results.write_index("idx", lines)

    # then the lines round-trip as NDJSON
    assert await results.read_index("idx") == lines
    assert await results.read_index("missing") == []


def test_bucket_comes_from_settings(results: ResultStore) -> None:
    assert results.bucket == settings.CRAWL_RESULT_S3_BUCKET


async def test_recrawl_write_read_and_expiry() -> None:
    # given
    redis = FakeRedis(decode_responses=True)
    store = RecrawlStore(redis)

    # when
    await store.write("acme", "scope", "HTTPS://EXAMPLE.COM/A#f", {"hash": "abc", "page_key": "k"})

    # then the normalised URL is the field and the hash carries the retention expiry
    assert await store.read("acme", "scope", "https://example.com/A") == {
        "hash": "abc",
        "page_key": "k",
    }
    ttl = await redis.ttl("crawl_recrawl:acme:scope")
    assert settings.CRAWL_JOB_RETENTION_SECONDS - 2 <= ttl <= settings.CRAWL_JOB_RETENTION_SECONDS
    assert store.key("acme", "scope") == "crawl_recrawl:acme:scope"


async def test_recrawl_read_missing_and_corrupt() -> None:
    # given
    redis = FakeRedis(decode_responses=True)
    store = RecrawlStore(redis)

    # when / then
    assert await store.read("acme", "scope", "https://example.com/a") is None
    await redis.hset("crawl_recrawl:acme:scope", "https://example.com/a", "not json")
    assert await store.read("acme", "scope", "https://example.com/a") is None
    await redis.hset("crawl_recrawl:acme:scope", "https://example.com/b", json.dumps(["x"]))
    assert await store.read("acme", "scope", "https://example.com/b") is None


async def test_recrawl_state_never_crosses_tenants() -> None:
    # given
    redis = FakeRedis(decode_responses=True)
    store = RecrawlStore(redis)

    # when a job of tenant acme writes its scope
    await store.write("acme", "scope", "https://example.com/a", {"hash": "abc"})

    # then no key of another tenant exists
    assert [key async for key in redis.scan_iter(match="crawl_*:globex:*")] == []
    assert [key async for key in redis.scan_iter(match="*")] == ["crawl_recrawl:acme:scope"]


@pytest.fixture
def fresh_expiry_status(monkeypatch: pytest.MonkeyPatch) -> ExpiryRuleStatus:
    status = ExpiryRuleStatus()
    monkeypatch.setattr(result_store_module, "expiry_rule_status", status)
    return status


async def test_result_writes_never_touch_the_lifecycle_rule(fresh_expiry_status: ExpiryRuleStatus) -> None:
    # given a store that has written nothing yet
    objects = _FakeObjects()
    store = ResultStore(objects)  # type: ignore[arg-type]

    # when pages and an index are written
    await store.write_page("tenant/acme/p1", "one")
    await store.write_index("tenant/acme/idx", [])

    # then no write set the lifecycle rule
    assert objects.expiry_calls == []
    assert set(objects.text) == {"tenant/acme/p1", "tenant/acme/idx"}


@pytest.mark.parametrize(("retention", "days"), [(604800, 7), (90000, 2), (3600, 1), (86400, 1)])
async def test_expiry_rule_is_applied_once_per_process_in_whole_days(
    monkeypatch: pytest.MonkeyPatch, fresh_expiry_status: ExpiryRuleStatus, retention: int, days: int
) -> None:
    # given a retention
    monkeypatch.setattr(settings, "CRAWL_JOB_RETENTION_SECONDS", retention)
    objects = _FakeObjects()

    # when two stores of one process apply the rule
    await ResultStore(objects).apply_expiry_rule()  # type: ignore[arg-type]
    await ResultStore(objects).apply_expiry_rule()  # type: ignore[arg-type]

    # then the rule was set once, rounded up to whole days, and reported applied
    assert objects.expiry_calls == [(settings.CRAWL_RESULT_S3_BUCKET, "tenant/", days)]
    assert fresh_expiry_status.applied is True
    assert fresh_expiry_status.error is None
    gauge = REGISTRY.get_sample_value(
        "crawl_result_expiry_rule_applied", {"bucket": settings.CRAWL_RESULT_S3_BUCKET}
    )
    assert gauge == 1


@pytest.mark.parametrize(
    "refusal",
    [
        ClientError(
            {"Error": {"Code": "NotImplemented", "Message": "lifecycle"}}, "PutBucketLifecycleConfiguration"
        ),
        EndpointConnectionError(endpoint_url="http://store:9070"),
    ],
    ids=["store-refuses-lifecycle", "store-unreachable"],
)
async def test_refused_expiry_rule_warns_and_never_fails_a_page(
    fresh_expiry_status: ExpiryRuleStatus, caplog: pytest.LogCaptureFixture, refusal: Exception
) -> None:
    # given a store that refuses the lifecycle rule
    class RefusingObjects(_FakeObjects):
        async def set_expiry(self, bucket: str, prefix: str, days: int) -> None:
            await super().set_expiry(bucket, prefix, days)
            raise refusal

    objects = RefusingObjects()
    store = ResultStore(objects)  # type: ignore[arg-type]

    # when the rule is applied and a page is written afterwards
    with caplog.at_level(logging.WARNING, logger="src.crawl.result_store"):
        await store.apply_expiry_rule()
    await store.write_page("tenant/acme/p1", "one")

    # then one warning names the bucket and the error, the state is reported and the page is stored
    warnings = [record for record in caplog.records if record.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert settings.CRAWL_RESULT_S3_BUCKET in warnings[0].getMessage()
    assert str(refusal) in warnings[0].getMessage()
    assert fresh_expiry_status.applied is False
    assert fresh_expiry_status.error == type(refusal).__name__
    gauge = REGISTRY.get_sample_value(
        "crawl_result_expiry_rule_applied", {"bucket": settings.CRAWL_RESULT_S3_BUCKET}
    )
    assert gauge == 0
    assert objects.text == {"tenant/acme/p1": "one"}


async def test_delete_page_removes_the_object(results: ResultStore) -> None:
    # given
    await results.write_page("k", "hello")

    # when
    await results.delete_page("k")

    # then
    assert await results.page_exists("k") is False


async def test_recrawl_revert_without_prior_deletes_the_field() -> None:
    # given an entry this job wrote over nothing
    redis = FakeRedis(decode_responses=True)
    store = RecrawlStore(redis)
    written = await store.write("acme", "scope", "https://example.com/a", {"page_key": "new"})

    # when
    await store.revert("acme", "scope", "https://example.com/a", written, None)

    # then
    assert await store.read("acme", "scope", "https://example.com/a") is None


async def test_recrawl_revert_restores_the_prior_entry() -> None:
    # given an entry this job wrote over an earlier job's entry
    redis = FakeRedis(decode_responses=True)
    store = RecrawlStore(redis)
    prior = {"page_key": "old", "hash": "h"}
    await store.write("acme", "scope", "https://example.com/a", prior)
    written = await store.write("acme", "scope", "https://example.com/a", {"page_key": "new"})

    # when
    await store.revert("acme", "scope", "https://example.com/a", written, prior)

    # then
    assert await store.read("acme", "scope", "https://example.com/a") == prior


async def test_recrawl_revert_leaves_an_entry_another_job_wrote_since() -> None:
    # given an entry overwritten by another job after this job's write
    redis = FakeRedis(decode_responses=True)
    store = RecrawlStore(redis)
    written = await store.write("acme", "scope", "https://example.com/a", {"page_key": "mine"})
    await store.write("acme", "scope", "https://example.com/a", {"page_key": "theirs"})

    # when
    await store.revert("acme", "scope", "https://example.com/a", written, None)

    # then the other job's entry stays
    assert await store.read("acme", "scope", "https://example.com/a") == {"page_key": "theirs"}
