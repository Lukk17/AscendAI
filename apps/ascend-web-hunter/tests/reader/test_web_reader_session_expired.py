"""The read path validates a stored session before it uses one.

Change close-web-search-scraping-follow-ups, tasks 2.2 and 2.3.
"""

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.reader.web_reader import SESSION_EXPIRED_STATUS, WebReader, _cache_key

_URL = "https://example.com/feed"
_SESSION_EXPIRED_FIELDS = ["content", "status", "profile", "message"]
_ARTICLE_HTML = (
    "<html><head><title>Feed</title></head><body><article><p>"
    "This is the main body of the article. It has enough text to pass the content validator. "
    "The article covers interesting topics and provides information to the reader. "
    "Multiple sentences ensure it clears any minimum length requirement easily."
    "</p></article></body></html>"
)


def _gate(has_auth: bool, valid: bool) -> list[Any]:
    return [
        patch(
            "src.reader.web_reader.cookie_manager.has_auth_cookies",
            new=AsyncMock(return_value=has_auth),
        ),
        patch("src.reader.web_reader.session_manager.validate", new=AsyncMock(return_value=valid)),
    ]


async def _read(reader: WebReader, patches: list[Any], **kwargs: Any) -> dict[str, Any]:
    for patched in patches:
        patched.start()
    try:
        return await reader.read(_URL, **kwargs)
    finally:
        for patched in patches:
            patched.stop()


async def _read_with_links(reader: WebReader, patches: list[Any], **kwargs: Any) -> dict[str, Any]:
    for patched in patches:
        patched.start()
    try:
        return await reader.read_with_links(_URL, **kwargs)
    finally:
        for patched in patches:
            patched.stop()


def _succeeding_reader() -> tuple[WebReader, dict[str, int], Any]:
    reader = WebReader()
    counter = {"calls": 0}

    async def _execute(name: str, strategy: Any, url: str, **_kwargs: Any) -> dict[str, Any]:
        counter["calls"] += 1

        return {"content": "the page", "status": "success", "mode": name}

    return reader, counter, patch.object(reader, "_execute_strategy", side_effect=_execute)


def _html_reader() -> tuple[WebReader, dict[str, int], Any]:
    reader = WebReader()
    counter = {"calls": 0}

    async def _execute_html(name: str, strategy: Any, url: str) -> str:
        counter["calls"] += 1

        return _ARTICLE_HTML

    return reader, counter, patch.object(reader, "_execute_html_strategy", side_effect=_execute_html)


@pytest.mark.asyncio
async def test_a_target_with_no_stored_login_reads_as_before():
    reader, counter, execute = _succeeding_reader()

    result = await _read(reader, [*_gate(has_auth=False, valid=False), execute])

    assert result["status"] == "success"
    assert counter["calls"] == 1


@pytest.mark.asyncio
async def test_a_target_with_no_stored_login_is_never_validated():
    reader, _, execute = _succeeding_reader()
    validate = AsyncMock(return_value=False)

    with (
        patch(
            "src.reader.web_reader.cookie_manager.has_auth_cookies",
            new=AsyncMock(return_value=False),
        ),
        patch("src.reader.web_reader.session_manager.validate", new=validate),
        execute,
    ):
        await reader.read(_URL)

    validate.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_live_session_runs_the_chain():
    reader, counter, execute = _succeeding_reader()

    result = await _read(reader, [*_gate(has_auth=True, valid=True), execute])

    assert result["status"] == "success"
    assert counter["calls"] == 1


@pytest.mark.asyncio
async def test_an_expired_session_stops_the_read_before_any_tier_runs():
    reader, counter, execute = _succeeding_reader()

    result = await _read(reader, [*_gate(has_auth=True, valid=False), execute], profile="work")

    assert result["status"] == SESSION_EXPIRED_STATUS
    assert counter["calls"] == 0


@pytest.mark.asyncio
async def test_the_expired_outcome_carries_its_whole_contract():
    reader, _, execute = _succeeding_reader()

    result = await _read(reader, [*_gate(has_auth=True, valid=False), execute], profile="work")

    for field in _SESSION_EXPIRED_FIELDS:
        assert field in result
    assert result["content"] == ""
    assert result["profile"] == "work"
    assert "example.com" in result["message"]
    assert "work" in result["message"]
    assert "establish" in result["message"]


@pytest.mark.asyncio
async def test_the_expired_outcome_names_the_default_profile_when_none_was_given():
    reader, _, execute = _succeeding_reader()

    result = await _read(reader, [*_gate(has_auth=True, valid=False), execute])

    assert result["profile"] == "default"


@pytest.mark.asyncio
async def test_the_expired_outcome_is_not_the_generic_failure():
    reader, _, execute = _succeeding_reader()

    result = await _read(reader, [*_gate(has_auth=True, valid=False), execute])

    assert result["status"] != "error"
    assert "reason" not in result


@pytest.mark.asyncio
async def test_the_links_path_reports_the_expired_session_too():
    reader, counter, execute = _html_reader()

    result = await _read_with_links(reader, [*_gate(has_auth=True, valid=False), execute], profile="work")

    assert result["status"] == SESSION_EXPIRED_STATUS
    assert counter["calls"] == 0


@pytest.mark.asyncio
async def test_the_links_path_with_a_live_session_runs_the_chain():
    reader, counter, execute = _html_reader()

    result = await _read_with_links(reader, [*_gate(has_auth=True, valid=True), execute])

    assert result["status"] == "success"
    assert counter["calls"] == 1


@pytest.mark.asyncio
async def test_a_cached_result_does_not_mask_an_expired_session():
    reader, _, execute = _succeeding_reader()
    key = _cache_key(_URL, False, False, None, None)
    reader._cache_put(key, {"content": "stale but authenticated", "status": "success", "mode": "1"})

    result = await _read(reader, [*_gate(has_auth=True, valid=False), execute])

    assert result["status"] == SESSION_EXPIRED_STATUS
