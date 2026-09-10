from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from adblockparser import AdblockRules
from httpx import AsyncClient

from src.config.blocklist_loader import (
    BlocklistRefreshThrottledError,
    BlocklistState,
    BlocklistValidationError,
)
from src.config.blocklist_loader import blocklist_loader as real_blocklist_loader
from src.validator.url_validator import url_validator


@pytest.fixture
def restore_url_validator_rules():
    """The refresh endpoint mutates the process-wide `url_validator` singleton in
    place; restore it after any test that exercises a real (non-error) refresh so
    the swap does not leak into unrelated tests."""
    original_rules = url_validator.rules
    yield
    url_validator.rules = original_rules


@pytest.mark.asyncio
async def test_status_returns_current_rule_count_and_age(client: AsyncClient):
    resp = await client.get("/api/v1/blocklist/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["rule_count"] == real_blocklist_loader.state.rule_count
    assert body["age_seconds"] >= 0


@pytest.mark.asyncio
async def test_status_returns_503_when_not_loaded(client: AsyncClient):
    with patch.object(real_blocklist_loader, "_state", None):
        resp = await client.get("/api/v1/blocklist/status")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_refresh_success_returns_new_rule_count(client: AsyncClient, restore_url_validator_rules):
    new_state = BlocklistState(rule_count=42, loaded_at=datetime.now(UTC))
    new_rules = AdblockRules(["||fresh.example^"])
    with patch(
        "src.api.rest.blocklist_endpoints.blocklist_loader.refresh",
        new_callable=AsyncMock,
        return_value=(new_rules, new_state),
    ):
        resp = await client.post("/api/v1/blocklist/refresh")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "refreshed"
    assert body["rule_count"] == 42


@pytest.mark.asyncio
async def test_refresh_swaps_the_shared_url_validator_rules(client: AsyncClient, restore_url_validator_rules):
    new_state = BlocklistState(rule_count=1, loaded_at=datetime.now(UTC))
    new_rules = AdblockRules(["||fresh.example^"])
    with patch(
        "src.api.rest.blocklist_endpoints.blocklist_loader.refresh",
        new_callable=AsyncMock,
        return_value=(new_rules, new_state),
    ):
        resp = await client.post("/api/v1/blocklist/refresh")

    assert resp.status_code == 200
    assert url_validator.rules is new_rules


@pytest.mark.asyncio
async def test_refresh_network_failure_returns_503(client: AsyncClient):
    with patch(
        "src.api.rest.blocklist_endpoints.blocklist_loader.refresh",
        new_callable=AsyncMock,
        side_effect=httpx.ConnectError("network down"),
    ):
        resp = await client.post("/api/v1/blocklist/refresh")
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_refresh_validation_failure_returns_502(client: AsyncClient):
    with patch(
        "src.api.rest.blocklist_endpoints.blocklist_loader.refresh",
        new_callable=AsyncMock,
        side_effect=BlocklistValidationError("empty ruleset"),
    ):
        resp = await client.post("/api/v1/blocklist/refresh")
    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_refresh_throttled_returns_429_with_retry_after(client: AsyncClient):
    with patch(
        "src.api.rest.blocklist_endpoints.blocklist_loader.refresh",
        new_callable=AsyncMock,
        side_effect=BlocklistRefreshThrottledError(30.0),
    ):
        resp = await client.post("/api/v1/blocklist/refresh")
    assert resp.status_code == 429
    assert "Retry-After" in resp.headers
