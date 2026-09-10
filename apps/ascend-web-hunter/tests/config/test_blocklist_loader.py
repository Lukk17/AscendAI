import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from src.config.blocklist_loader import (
    BlocklistLoader,
    BlocklistRefreshThrottledError,
    BlocklistValidationError,
)
from src.config.config import settings


def _make_loader(tmp_path: Path, content: str | None = "||example.com^\n! comment\n") -> BlocklistLoader:
    path = tmp_path / "fanboy-annoyance.txt"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    return BlocklistLoader(blocklist_path=str(path))


def test_load_rules_reads_the_vendored_file(tmp_path):
    loader = _make_loader(tmp_path, "||example.com^\n! comment\n\n||other.com^\n")
    rules = loader.load_rules()
    assert rules.should_block("http://example.com")
    assert loader.state is not None
    assert loader.state.rule_count == 2


def test_load_rules_raises_file_not_found_when_missing(tmp_path):
    loader = _make_loader(tmp_path, content=None)
    with pytest.raises(FileNotFoundError):
        loader.load_rules()


def test_load_rules_raises_runtime_error_on_corrupt_file(tmp_path):
    loader = _make_loader(tmp_path)
    with patch("pathlib.Path.open", side_effect=PermissionError("read denied")):
        with pytest.raises(RuntimeError):
            loader.load_rules()


def _mock_response(content: bytes) -> MagicMock:
    response = MagicMock()
    response.content = content
    response.raise_for_status = MagicMock()
    return response


@pytest.mark.asyncio
async def test_refresh_success_swaps_file_and_state(tmp_path):
    loader = _make_loader(tmp_path)
    new_content = b"||fresh.example^\n! comment\n||another.example^\n"
    with patch("httpx.AsyncClient.get", return_value=_mock_response(new_content)):
        rules, state = await loader.refresh()

    assert rules.should_block("http://fresh.example")
    assert state.rule_count == 2
    assert loader.state == state
    assert loader.blocklist_path.read_bytes() == new_content


@pytest.mark.asyncio
async def test_refresh_raises_httpx_error_and_leaves_file_untouched(tmp_path):
    loader = _make_loader(tmp_path)
    original_content = loader.blocklist_path.read_bytes()
    with patch("httpx.AsyncClient.get", side_effect=httpx.ConnectError("network down")):
        with pytest.raises(httpx.HTTPError):
            await loader.refresh()

    assert loader.blocklist_path.read_bytes() == original_content
    assert loader.state is None


@pytest.mark.asyncio
async def test_refresh_raises_validation_error_on_empty_ruleset_and_leaves_file_untouched(tmp_path):
    loader = _make_loader(tmp_path)
    original_content = loader.blocklist_path.read_bytes()
    with patch("httpx.AsyncClient.get", return_value=_mock_response(b"! only a comment\n")):
        with pytest.raises(BlocklistValidationError):
            await loader.refresh()

    assert loader.blocklist_path.read_bytes() == original_content
    assert loader.state is None


@pytest.mark.asyncio
async def test_refresh_raises_throttled_error_within_cooldown(tmp_path):
    loader = _make_loader(tmp_path)
    with patch("httpx.AsyncClient.get", return_value=_mock_response(b"||example.com^\n")):
        await loader.refresh()
        with pytest.raises(BlocklistRefreshThrottledError):
            await loader.refresh()


@pytest.mark.asyncio
async def test_refresh_allows_retry_after_cooldown_elapses(tmp_path, monkeypatch):
    loader = _make_loader(tmp_path)
    fake_clock = [1000.0]
    monkeypatch.setattr("src.config.blocklist_loader.time.monotonic", lambda: fake_clock[0])
    with patch("httpx.AsyncClient.get", return_value=_mock_response(b"||example.com^\n")):
        await loader.refresh()

        fake_clock[0] += settings.BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS + 1
        _, state = await loader.refresh()

    assert state.rule_count == 1


@pytest.mark.asyncio
async def test_refresh_serialises_concurrent_calls(tmp_path):
    loader = _make_loader(tmp_path)
    call_order: list[str] = []

    async def _slow_get(*_args: object, **_kwargs: object) -> MagicMock:
        call_order.append("start")
        await asyncio.sleep(0.01)
        call_order.append("end")
        return _mock_response(b"||example.com^\n")

    with patch("httpx.AsyncClient.get", side_effect=_slow_get):
        results = await asyncio.gather(loader.refresh(), loader.refresh(), return_exceptions=True)

    successes = [r for r in results if not isinstance(r, Exception)]
    throttled = [r for r in results if isinstance(r, BlocklistRefreshThrottledError)]
    assert len(successes) == 1
    assert len(throttled) == 1
    # The second call's lock wait must not overlap the first call's network call.
    assert call_order == ["start", "end"]
