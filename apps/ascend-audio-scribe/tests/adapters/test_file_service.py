from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.adapters import file_service
from src.api.exception_handlers import FileSizeExceededError


def test_create_temp_file_returns_path() -> None:
    path = file_service.create_temp_file(suffix=".wav")
    assert Path(path).exists()
    Path(path).unlink()


def test_safe_suffix_with_extension() -> None:
    assert file_service.safe_suffix_from_filename("clip.wav") == ".wav"


def test_safe_suffix_empty_filename() -> None:
    assert file_service.safe_suffix_from_filename("") == ""
    assert file_service.safe_suffix_from_filename("noext") == ""


def test_safe_suffix_handles_exception() -> None:
    """When Path() raises (rare — usually a passing-non-str filename), the
    fallback returns an empty string. Patches the symbol the production
    code calls."""

    with patch.object(file_service, "Path", side_effect=ValueError("boom")):
        assert file_service.safe_suffix_from_filename("x.wav") == ""


def test_cleanup_temp_file_handles_none() -> None:
    file_service.cleanup_temp_file(None)


def test_cleanup_temp_file_swallows_oserror(tmp_path: Path) -> None:
    path = tmp_path / "x.txt"
    path.write_text("y", encoding="utf-8")
    with patch.object(file_service.os, "remove", side_effect=OSError("nope")):
        file_service.cleanup_temp_file(str(path))


def test_cleanup_temp_file_skips_missing_path(tmp_path: Path) -> None:
    file_service.cleanup_temp_file(str(tmp_path / "missing.txt"))


@pytest.mark.asyncio
async def test_save_upload_streams_and_succeeds(tmp_path: Path) -> None:
    upload = MagicMock()
    upload.filename = "clip.wav"
    upload.seek = AsyncMock()
    reads = [b"x" * 1024, b"y" * 512, b""]
    upload.read = AsyncMock(side_effect=reads)

    path = await file_service.save_upload_to_temp_async(upload)
    written = Path(path).read_bytes()
    Path(path).unlink()
    assert written == reads[0] + reads[1]


@pytest.mark.asyncio
async def test_save_upload_enforces_size_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(file_service.settings, "MAX_UPLOAD_BYTES", 100)
    monkeypatch.setattr(file_service.settings, "UPLOAD_BUFFER_BYTES", 64)
    upload = MagicMock()
    upload.filename = "big.wav"
    upload.seek = AsyncMock()
    upload.read = AsyncMock(side_effect=[b"a" * 64, b"b" * 64, b""])
    with pytest.raises(FileSizeExceededError):
        await file_service.save_upload_to_temp_async(upload)
