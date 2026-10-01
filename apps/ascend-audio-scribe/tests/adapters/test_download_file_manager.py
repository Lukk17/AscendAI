import asyncio
import os
import time
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

from src.adapters import download_file_manager as mgr
from src.config.config import settings


@pytest.fixture(autouse=True)
def _reset_registry() -> Iterator[None]:
    mgr._file_registry.clear()
    yield
    mgr._file_registry.clear()


def test_store_and_get_transcript() -> None:
    # given
    file_id, path = mgr.store_transcript("hello world", "x.md")

    # when
    resolved = mgr.get_transcript_path(file_id)

    # then
    assert resolved == path
    assert Path(path).read_text(encoding="utf-8") == "hello world"
    Path(path).unlink()


def test_get_transcript_returns_none_for_unknown() -> None:
    # when / then
    assert mgr.get_transcript_path("missing") is None


def test_get_transcript_returns_none_when_expired(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    file_id, path = mgr.store_transcript("y", "z.md")
    # Force expiry by advancing the clock past TTL.
    base = time.monotonic() + settings.DOWNLOAD_FILE_TTL_SECONDS + 1
    monkeypatch.setattr(time, "monotonic", lambda: base)

    # when / then
    assert mgr.get_transcript_path(file_id) is None
    assert not Path(path).exists()


def test_get_transcript_returns_none_when_file_missing() -> None:
    # given
    file_id, path = mgr.store_transcript("x", "x.md")

    # when
    Path(path).unlink()

    # then
    assert mgr.get_transcript_path(file_id) is None


def test_remove_transcript() -> None:
    # given
    file_id, path = mgr.store_transcript("x", "x.md")

    # when
    mgr.remove_transcript(file_id)

    # then
    assert not Path(path).exists()
    assert mgr.get_transcript_path(file_id) is None


def test_remove_transcript_unknown() -> None:
    # when / then
    mgr.remove_transcript("unknown")


def test_cleanup_expired_removes_old(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    file_id, path = mgr.store_transcript("x", "x.md")
    base = time.monotonic() + settings.DOWNLOAD_FILE_TTL_SECONDS + 1
    monkeypatch.setattr(time, "monotonic", lambda: base)

    # when
    mgr.cleanup_expired()

    # then
    assert file_id not in mgr._file_registry
    assert not Path(path).exists()


def test_cleanup_expired_handles_concurrent_pop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cover the `if entry is not None:` False branch in cleanup_expired:
    a concurrent thread can pop a fid between the snapshot iteration and
    the per-fid pop. Simulated by swapping the registry for a dict subclass
    whose first pop call empties the registry before delegating."""

    # given
    class _RacyRegistry(dict[str, tuple[str, float]]):
        def __init__(self, *args: object, **kwargs: object) -> None:
            super().__init__(*args, **kwargs)
            self._first_pop = True

        def pop(self, key: str, default: object = None) -> object:  # type: ignore[override]
            if self._first_pop:
                self._first_pop = False
                self.clear()
            return super().pop(key, default)

    file_id, path = mgr.store_transcript("x", "x.md")
    base = time.monotonic() + settings.DOWNLOAD_FILE_TTL_SECONDS + 1
    monkeypatch.setattr(time, "monotonic", lambda: base)

    racy = _RacyRegistry(mgr._file_registry)
    monkeypatch.setattr(mgr, "_file_registry", racy)

    # when
    mgr.cleanup_expired()

    # then
    assert file_id not in racy
    # Simulated racing thread didn't actually remove the on-disk file;
    # clean up so the temp dir doesn't accumulate fixture residue.
    if Path(path).exists():
        Path(path).unlink()


def test_cleanup_expired_skips_fresh() -> None:
    # given
    file_id, path = mgr.store_transcript("x", "x.md")

    # when
    mgr.cleanup_expired()

    # then
    assert file_id in mgr._file_registry
    Path(path).unlink()


def test_remove_entry_handles_missing() -> None:
    # when / then
    mgr._remove_entry("unknown")


def test_remove_entry_with_explicit_path(tmp_path: Path) -> None:
    # given
    p = tmp_path / "x.txt"
    p.write_text("y", encoding="utf-8")

    # when
    mgr._remove_entry("unknown", str(p))

    # then
    assert not p.exists()


def test_cleanup_file_swallows_oserror(tmp_path: Path) -> None:
    # when / then
    with patch.object(os, "remove", side_effect=OSError("nope")):
        mgr._cleanup_file(str(tmp_path / "x"))


@pytest.mark.asyncio
async def test_run_cleanup_loop_runs_then_stops(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    calls = {"n": 0}

    def fake_cleanup() -> None:
        calls["n"] += 1

    monkeypatch.setattr(mgr, "cleanup_expired", fake_cleanup)
    monkeypatch.setattr(settings, "DOWNLOAD_CLEANUP_INTERVAL_SECONDS", 0.01)

    stop = asyncio.Event()
    task = asyncio.create_task(mgr.run_cleanup_loop(stop))
    await asyncio.sleep(0.05)
    stop.set()

    # when
    await task

    # then
    assert calls["n"] >= 1


@pytest.mark.asyncio
async def test_run_cleanup_loop_logs_on_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    def boom() -> None:
        raise RuntimeError("kaboom")

    monkeypatch.setattr(mgr, "cleanup_expired", boom)
    monkeypatch.setattr(settings, "DOWNLOAD_CLEANUP_INTERVAL_SECONDS", 0.01)

    stop = asyncio.Event()
    task = asyncio.create_task(mgr.run_cleanup_loop(stop))
    await asyncio.sleep(0.03)
    stop.set()

    # when / then
    await task
