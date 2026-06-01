"""audio_chunker tests.

`chunked_audio` is a contextmanager whose `__enter__` raises in the error
cases, so the `with` body never runs. Each failing test exercises the
contextmanager outside `with`, asserting on the raised exception directly
to avoid a stylistically-empty `pass` body in the `with` block.
"""

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.transcription import audio_chunker


def test_chunked_audio_yields_chunks(tmp_path: Path) -> None:
    work = tmp_path / "work_xx"
    work.mkdir()
    (work / "chunk_00000.wav").write_bytes(b"a")
    (work / "chunk_00001.wav").write_bytes(b"b")

    with patch.object(audio_chunker.tempfile, "mkdtemp", return_value=str(work)), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         audio_chunker.chunked_audio("input.wav", 5) as chunks:
        assert len(chunks) == 2
        assert chunks[0].endswith("chunk_00000.wav")


def _enter_and_collect(work: Path) -> list[str]:
    """Enter chunked_audio with the work directory already patched and
    return the yielded list. Helper exists so the failing tests don't need
    an empty `with ... as chunks: pass` body."""

    with audio_chunker.chunked_audio("input.wav", 5) as chunks:
        return chunks


def test_chunked_audio_no_chunks_raises(tmp_path: Path) -> None:
    work = tmp_path / "work_empty"
    work.mkdir()
    with patch.object(audio_chunker.tempfile, "mkdtemp", return_value=str(work)), \
         patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         pytest.raises(OSError, match="no chunks"):
        _enter_and_collect(work)


def test_chunked_audio_timeout(tmp_path: Path) -> None:
    work = tmp_path / "work_t"
    work.mkdir()
    err = subprocess.TimeoutExpired(cmd="ffmpeg", timeout=1)
    with patch.object(audio_chunker.tempfile, "mkdtemp", return_value=str(work)), \
         patch("subprocess.run", side_effect=err), \
         pytest.raises(OSError, match="timed out"):
        _enter_and_collect(work)


def test_chunked_audio_called_process_error(tmp_path: Path) -> None:
    work = tmp_path / "work_e"
    work.mkdir()
    err = subprocess.CalledProcessError(1, "ffmpeg", stderr=b"bad input")
    with patch.object(audio_chunker.tempfile, "mkdtemp", return_value=str(work)), \
         patch("subprocess.run", side_effect=err), \
         pytest.raises(OSError, match="segmentation failed"):
        _enter_and_collect(work)


def test_chunked_audio_cleanup_swallows(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    work = tmp_path / "work_clean"
    work.mkdir()
    (work / "chunk_00000.wav").write_bytes(b"a")
    monkeypatch.setattr(audio_chunker.tempfile, "mkdtemp", lambda **_k: str(work))

    def boom(_path: str) -> None:
        raise OSError("cannot delete")

    with patch("subprocess.run", return_value=MagicMock(returncode=0)), \
         patch.object(audio_chunker.os, "remove", side_effect=boom), \
         patch.object(audio_chunker.os, "rmdir", side_effect=OSError("nope")), \
         audio_chunker.chunked_audio("input.wav", 5) as chunks:
        assert chunks
