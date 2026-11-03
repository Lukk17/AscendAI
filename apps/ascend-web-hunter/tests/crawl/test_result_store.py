import json

import pytest
from fakeredis.aioredis import FakeRedis

from src.config.config import settings
from src.crawl.result_store import (
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


def test_recrawl_scope_sorts_inputs() -> None:
    assert recrawl_scope(["b", "a"], ["y"]) == recrawl_scope(["a", "b"], ["y"])
    assert recrawl_scope(["a"], []) != recrawl_scope(["a"], ["y"])


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

    async def ensure_bucket(self, bucket: str) -> None:
        return None

    async def put_text(self, bucket: str, key: str, text: str) -> None:
        self.text[key] = text

    async def get_text(self, bucket: str, key: str) -> str | None:
        return self.text.get(key)

    async def head(self, bucket: str, key: str) -> bool:
        return key in self.text

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
