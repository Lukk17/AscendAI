import os
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.api import readiness as readiness_module
from src.main import app


def test_resolve_on_path_returns_absolute_when_file_exists(tmp_path: Path) -> None:
    target = tmp_path / "ffmpeg.exe"
    target.write_bytes(b"")
    resolved = readiness_module._resolve_on_path(str(target))
    assert resolved == target


def test_resolve_on_path_returns_none_when_absolute_missing(tmp_path: Path) -> None:
    assert readiness_module._resolve_on_path(str(tmp_path / "absent")) is None


def test_resolve_on_path_walks_path_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "ffmpeg"
    target.write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(readiness_module, "_executable_extensions", lambda: [""])
    resolved = readiness_module._resolve_on_path("ffmpeg")
    assert resolved == target


def test_resolve_on_path_returns_none_when_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PATH", "")
    monkeypatch.setattr(readiness_module, "_executable_extensions", lambda: [""])
    assert readiness_module._resolve_on_path("nonexistent-binary-xyz") is None


def test_resolve_on_path_honours_pathext(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "ffmpeg.exe"
    target.write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(readiness_module, "_executable_extensions", lambda: [".EXE"])
    resolved = readiness_module._resolve_on_path("ffmpeg")
    assert resolved == target


def test_resolve_on_path_walks_to_second_directory_when_first_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inner-loop exhaustion → continue outer loop (branch 55->51)."""

    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    hit_dir = tmp_path / "hit"
    hit_dir.mkdir()
    target = hit_dir / "ffmpeg"
    target.write_bytes(b"")
    monkeypatch.setenv("PATH", f"{empty_dir}{os.pathsep}{hit_dir}")
    monkeypatch.setattr(readiness_module, "_executable_extensions", lambda: [""])
    resolved = readiness_module._resolve_on_path("ffmpeg")
    assert resolved == target


def test_resolve_on_path_tries_second_pathext_when_first_misses(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Inner-loop ext miss → continue to next ext (branch 57->55)."""

    target = tmp_path / "ffmpeg.bat"
    target.write_bytes(b"")
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(
        readiness_module, "_executable_extensions", lambda: [".EXE", ".BAT"]
    )
    resolved = readiness_module._resolve_on_path("ffmpeg")
    assert resolved == target


def test_resolve_on_path_skips_empty_directory_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "ffmpeg"
    target.write_bytes(b"")
    # Leading empty entry exercises the `if not directory` guard.
    monkeypatch.setenv("PATH", f"{os.pathsep}{tmp_path}")
    monkeypatch.setattr(readiness_module, "_executable_extensions", lambda: [""])
    resolved = readiness_module._resolve_on_path("ffmpeg")
    assert resolved == target


def test_executable_extensions_posix(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness_module, "_is_windows", lambda: False)
    assert readiness_module._executable_extensions() == [""]


def test_executable_extensions_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(readiness_module, "_is_windows", lambda: True)
    monkeypatch.setenv("PATHEXT", ".EXE;.BAT")
    assert readiness_module._executable_extensions() == [".EXE", ".BAT"]


def test_is_windows_reflects_os_name() -> None:
    assert readiness_module._is_windows() == (os.name == "nt")


def test_probe_ffmpeg_ok() -> None:
    with patch.object(readiness_module, "_resolve_on_path", return_value=Path("/usr/bin/ffmpeg")):
        assert readiness_module._probe_ffmpeg() == {"status": "ok"}


def test_probe_ffmpeg_missing() -> None:
    with patch.object(readiness_module, "_resolve_on_path", return_value=None):
        result = readiness_module._probe_ffmpeg()
    assert result["status"] == "error"


def test_probe_ffmpeg_ffprobe_missing() -> None:
    with patch.object(
        readiness_module,
        "_resolve_on_path",
        side_effect=[Path("/usr/bin/ffmpeg"), None],
    ):
        result = readiness_module._probe_ffmpeg()
    assert result["status"] == "error"
    assert "ffprobe" in result["detail"]


def test_probe_temp_dir_ok(tmp_path: Path) -> None:
    with patch.object(readiness_module.tempfile, "gettempdir", return_value=str(tmp_path)):
        assert readiness_module._probe_temp_dir() == {"status": "ok"}


def test_probe_temp_dir_missing() -> None:
    with patch.object(
        readiness_module.tempfile, "gettempdir", return_value="/nonexistent-audioscribe-xyz"
    ):
        result = readiness_module._probe_temp_dir()
    assert result["status"] == "error"


def test_probe_temp_dir_not_writable(tmp_path: Path) -> None:
    with patch.object(readiness_module.tempfile, "gettempdir", return_value=str(tmp_path)), \
         patch("pathlib.Path.write_text", side_effect=OSError("readonly")):
        result = readiness_module._probe_temp_dir()
    assert result["status"] == "error"


def test_ready_endpoint_200_when_clean() -> None:
    with patch.object(readiness_module, "_probe_ffmpeg", return_value={"status": "ok"}), \
         patch.object(readiness_module, "_probe_temp_dir", return_value={"status": "ok"}), \
         TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.json()["status"] == "ready"


def test_ready_endpoint_503_when_degraded() -> None:
    with patch.object(
        readiness_module, "_probe_ffmpeg", return_value={"status": "error", "detail": "x"}
    ), patch.object(
        readiness_module, "_probe_temp_dir", return_value={"status": "ok"}
    ), TestClient(app) as client:
        response = client.get("/ready")
        assert response.status_code == 503
        assert response.json()["status"] == "degraded"
