import logging
import os
import tempfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from src.config.config import settings

logger = logging.getLogger(__name__)

readiness_router = APIRouter(tags=["health"])


def _is_windows() -> bool:
    """Indirection so tests can mock platform behavior without touching
    `os.name` globally — patching `os.name` during a test breaks pytest's
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


def _probe_ffmpeg() -> dict[str, str]:
    """ffmpeg + ffprobe are runtime-required; if either is absent, the service
    cannot transcribe Audacity projects or chunk audio for OpenAI/HF."""

    if _resolve_on_path(settings.FFMPEG_PATH) is None:
        return {"status": "error", "detail": "ffmpeg not on PATH"}
    if _resolve_on_path(settings.FFPROBE_PATH) is None:
        return {"status": "error", "detail": "ffprobe not on PATH"}
    return {"status": "ok"}


def _probe_temp_dir() -> dict[str, str]:
    """Temp dir must be writable for streamed uploads and ffmpeg chunking."""

    temp_root = Path(tempfile.gettempdir())
    if not temp_root.exists():
        return {"status": "error", "detail": f"temp dir {temp_root} missing"}
    try:
        probe = temp_root / "audioscribe_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("/ready: temp-dir probe failed: %s", exc)

        return {"status": "error", "detail": "temp dir not writable"}
    return {"status": "ok"}


@readiness_router.get("/ready")
def ready() -> JSONResponse:
    """Readiness probe. /health is liveness; this is readiness. Sync `def`
    because every probe is sync (`shutil.which`, `pathlib.Path.write_text`);
    FastAPI runs sync handlers in a threadpool."""

    ffmpeg_status = _probe_ffmpeg()
    tempdir_status = _probe_temp_dir()

    checks: dict[str, dict[str, Any]] = {
        "ffmpeg": ffmpeg_status,
        "tempdir": tempdir_status,
    }
    ok = all(c.get("status") == "ok" for c in checks.values())
    body = {"status": "ready" if ok else "degraded", "checks": checks}

    return JSONResponse(
        status_code=status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE,
        content=body,
    )
