"""Task 3.3: self-healing per-domain selector recipes."""

from typing import Any
from unittest.mock import patch

import pytest

from src.reader.recipe_store import (
    apply_selectors,
    build_object,
    coerce_field,
    delete,
    lookup,
    recipe_key,
    recipe_redis,
    replay_valid,
    store,
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "price": {"type": "number"}},
    "required": ["name", "price"],
}

_HTML = (
    "<html><body><h1 class='product'>Red Widget</h1>"
    "<span class='price'>19.99</span></body></html>"
)


class _FakeRedis:
    def __init__(self, fail: str | None = None) -> None:
        self.records: dict[str, tuple[str, int]] = {}
        self.fail = fail

    async def get(self, key: str) -> str | None:
        if self.fail == "get":
            raise ConnectionError("redis is down")
        record = self.records.get(key)
        return record[0] if record else None

    async def setex(self, key: str, ttl: int, value: str) -> bool:
        if self.fail == "setex":
            raise ConnectionError("redis is down")
        self.records[key] = (value, ttl)
        return True

    async def delete(self, key: str) -> int:
        if self.fail == "delete":
            raise ConnectionError("redis is down")
        return 1 if self.records.pop(key, None) is not None else 0


@pytest.fixture
def fake_redis() -> Any:
    with patch("src.reader.recipe_store._RecipeClientHolder.client", _FakeRedis()) as fake:
        yield fake


def test_recipe_key_shape() -> None:
    assert recipe_key("example.com", "abc123") == "recipe:example.com:abc123"


@pytest.mark.asyncio
async def test_store_and_lookup_roundtrip(fake_redis: _FakeRedis) -> None:
    # given
    selectors = {"name": "h1.product", "price": ".price"}

    # when
    stored = await store("example.com", "digest1", selectors)

    # then
    assert stored is True
    assert await lookup("example.com", "digest1") == selectors
    assert fake_redis.records["recipe:example.com:digest1"][1] == 604800


@pytest.mark.asyncio
async def test_store_honours_ttl_override(fake_redis: _FakeRedis) -> None:
    # when
    with patch("src.reader.recipe_store.settings.RECIPE_TTL_SECONDS", 60):
        await store("example.com", "digest1", {"name": "h1"})

    # then
    assert fake_redis.records["recipe:example.com:digest1"][1] == 60


@pytest.mark.asyncio
async def test_lookup_miss_is_none(fake_redis: _FakeRedis) -> None:
    assert await lookup("example.com", "missing") is None


@pytest.mark.asyncio
async def test_lookup_corrupt_record_is_none(fake_redis: _FakeRedis) -> None:
    # given
    fake_redis.records["recipe:example.com:bad"] = ("{not json", 60)

    # when
    found = await lookup("example.com", "bad")

    # then
    assert found is None


@pytest.mark.asyncio
async def test_lookup_without_selectors_is_none(fake_redis: _FakeRedis) -> None:
    # given
    fake_redis.records["recipe:example.com:empty"] = ('{"selectors": {}}', 60)

    # when
    found = await lookup("example.com", "empty")

    # then
    assert found is None


@pytest.mark.asyncio
async def test_lookup_error_is_none_and_logged(
    fake_redis: _FakeRedis, caplog: pytest.LogCaptureFixture
) -> None:
    # given
    fake_redis.fail = "get"

    # when
    with caplog.at_level("WARNING"):
        found = await lookup("example.com", "digest1")

    # then
    assert found is None
    assert any("recipe_store" in record.name for record in caplog.records)


@pytest.mark.asyncio
async def test_no_client_skips_redis() -> None:
    # when
    with (
        patch("src.reader.recipe_store._RecipeClientHolder.client", None),
        patch("src.reader.recipe_store.settings.REDIS_URL", ""),
    ):
        assert await lookup("example.com", "digest1") is None
        assert await store("example.com", "digest1", {"name": "h1"}) is False
        await delete("example.com", "digest1")


@pytest.mark.asyncio
async def test_recipe_redis_builds_real_client_when_configured() -> None:
    # when
    with patch("src.reader.recipe_store._RecipeClientHolder.client", None):
        client = recipe_redis()

    # then
    assert client is not None
    await client.aclose()


@pytest.mark.asyncio
async def test_store_error_is_false(fake_redis: _FakeRedis) -> None:
    # given
    fake_redis.fail = "setex"

    # when
    stored = await store("example.com", "digest1", {"name": "h1"})

    # then
    assert stored is False


@pytest.mark.asyncio
async def test_store_nothing_valid_is_false(fake_redis: _FakeRedis) -> None:
    assert await store("example.com", "digest1", {"name": "x" * 513}) is False


@pytest.mark.asyncio
async def test_delete_error_is_tolerated(fake_redis: _FakeRedis) -> None:
    # given
    fake_redis.fail = "delete"

    # when
    await delete("example.com", "digest1")


def test_apply_selectors_reads_first_match() -> None:
    # when
    found = apply_selectors(_HTML, {"name": "h1.product", "price": ".price"})

    # then
    assert found == {"name": "Red Widget", "price": "19.99"}


def test_apply_selectors_skips_missing_and_bad() -> None:
    # when
    found = apply_selectors(_HTML, {"absent": ".nope", "bad": "div["})

    # then
    assert found == {}


def test_apply_selectors_parse_failure_is_empty() -> None:
    assert apply_selectors("", {"name": "h1"}) == {}


def test_replay_valid_accepts_and_rejects() -> None:
    assert replay_valid({"name": "Red Widget", "price": 19.99}, _SCHEMA) is True
    assert replay_valid({"name": "Red Widget"}, _SCHEMA) is False
    assert replay_valid({"name": "", "price": 19.99}, _SCHEMA) is False
    assert replay_valid({"name": "Red Widget", "price": None}, _SCHEMA) is False
    assert replay_valid({"name": "Red Widget", "price": 19.99}, {"type": "object"}) is True
    assert replay_valid({"name": "Red Widget"}, {"type": "object", "required": "name"}) is False
    assert replay_valid({"name": "Red Widget"}, {"type": "object", "required": [42]}) is False


def test_coerce_field_converts_scalars() -> None:
    assert coerce_field("19.99", {"type": "number"}) == 19.99
    assert coerce_field("7", {"type": "integer"}) == 7
    assert coerce_field("7", {"type": ["integer", "null"]}) == 7
    assert coerce_field("true", {"type": "boolean"}) is True
    assert coerce_field("no", {"type": "boolean"}) is False
    assert coerce_field("maybe", {"type": "boolean"}) == "maybe"
    assert coerce_field("19.99", {"type": "string"}) == "19.99"
    assert coerce_field("19.99", {}) == "19.99"
    assert coerce_field(19.99, {"type": "number"}) == 19.99
    assert coerce_field("abc", {"type": "number"}) == "abc"
    assert coerce_field("7", {"type": ["integer", "number"]}) == 7.0
    assert coerce_field("x", {"type": 42}) == "x"


def test_build_object_coerces_each_field() -> None:
    # when
    found = build_object(_HTML, {"name": "h1.product", "price": ".price"}, _SCHEMA)

    # then
    assert found == {"name": "Red Widget", "price": 19.99}


def test_build_object_without_properties_keeps_text() -> None:
    assert build_object(_HTML, {"name": "h1.product"}, {"type": "object"}) == {"name": "Red Widget"}
    assert build_object(
        _HTML, {"name": "h1.product"}, {"type": "object", "properties": {"name": "h1"}}
    ) == {"name": "Red Widget"}
