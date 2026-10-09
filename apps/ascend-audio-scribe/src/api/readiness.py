import logging
import os
import tempfile
from pathlib import Path

from ascend_python_common.readiness import ProbeResult

from src.config.config import settings

logger = logging.getLogger(__name__)


def _is_windows() -> bool:
    """Indirection so tests can mock platform behavior without touching
    `os.name` globally - patching `os.name` during a test breaks pytest's
    own pathlib-based reporter on Windows hosts."""

    return os.name == "nt"


def _executable_extensions() -> list[str]:
    if _is_windows():
        return os.environ.get("PATHEXT", "").split(os.pathsep)
    return [""]


def _resolve_on_path(binary_name: str) -> Path | None:
    """Locate `binary_name` on `$PATH` by walking the entries manually.

    Replaces `shutil.which`, which SonarLint (python: S6730) flags because
    its `cmd` parameter on Windows < 3.12 fails silently for PathLike
    inputs and the rule can't statically verify the arg type when callers
    pass a Pydantic Field attribute. Manual walk with `pathlib.Path` keeps
    the type story plain and platform-portable.

    On Windows we honor `PATHEXT` for executable extensions; on POSIX
    the empty suffix matches any executable bit set by the user.
    """

    candidate = Path(binary_name)
    if candidate.is_absolute():
        return candidate if candidate.is_file() else None

    path_dirs = os.environ.get("PATH", "").split(os.pathsep)
    extensions = _executable_extensions()

    for directory in path_dirs:
        if not directory:
            continue
        base = Path(directory) / binary_name
        for ext in extensions:
            full = base if not ext else base.with_suffix(ext.lower())
            if full.is_file():
                return full
    return None


def _probe_ffmpeg() -> ProbeResult:
    """ffmpeg + ffprobe are runtime-required; if either is absent, the service
    cannot transcribe Audacity projects or chunk audio for OpenAI/HF."""

    if _resolve_on_path(settings.FFMPEG_PATH) is None:
        return ProbeResult(status="error", details={"detail": "ffmpeg not on PATH"})
    if _resolve_on_path(settings.FFPROBE_PATH) is None:
        return ProbeResult(status="error", details={"detail": "ffprobe not on PATH"})
    return ProbeResult(status="ok")


def _probe_temp_dir() -> ProbeResult:
    """Temp dir must be writable for streamed uploads and ffmpeg chunking."""

    temp_root = Path(tempfile.gettempdir())
    if not temp_root.exists():
        return ProbeResult(status="error", details={"detail": f"temp dir {temp_root} missing"})
    try:
        probe = temp_root / "ascendaudioscribe_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("/ready: temp-dir probe failed: %s", exc)

        return ProbeResult(status="error", details={"detail": "temp dir not writable"})
    return ProbeResult(status="ok")


def probe_ffmpeg() -> ProbeResult:
    return _probe_ffmpeg()


def probe_temp_dir() -> ProbeResult:
    return _probe_temp_dir()
