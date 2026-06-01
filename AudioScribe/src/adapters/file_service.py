import contextlib
import logging
import os
import tempfile
from pathlib import Path

import aiofiles
from fastapi import UploadFile

from src.api.exception_handlers import FileSizeExceededError
from src.config.config import settings

logger = logging.getLogger(__name__)


def create_temp_file(suffix: str = settings.TEMP_FILE_SUFFIX_DEFAULT) -> str:
    """Create a temporary file synchronously and return its path."""

    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        return tmp.name


def safe_suffix_from_filename(filename: str) -> str:
    """Build a safe suffix for a temp file based on the original filename's
    suffix. Returns an empty string when the filename has no extension or is
    otherwise unparsable."""

    try:
        if not filename:
            return ""
        return Path(filename).suffix or ""
    except (TypeError, ValueError):
        return ""


async def save_upload_to_temp_async(upload: UploadFile) -> str:
    """Stream an UploadFile to disk in fixed-size chunks. Enforces
    MAX_UPLOAD_BYTES while looping so a multi-GB upload cannot OOM the
    container before we even reach validation."""

    suffix = safe_suffix_from_filename(upload.filename or "")
    temp_path = create_temp_file(suffix)

    bytes_written = 0
    cap = settings.MAX_UPLOAD_BYTES
    buffer_size = settings.UPLOAD_BUFFER_BYTES

    await upload.seek(0)
    try:
        async with aiofiles.open(temp_path, "wb") as out_file:
            while True:
                chunk = await upload.read(buffer_size)
                if not chunk:
                    break
                bytes_written += len(chunk)
                if bytes_written > cap:
                    raise FileSizeExceededError(
                        f"Upload exceeds maximum size of {cap} bytes"
                    )
                await out_file.write(chunk)
    except FileSizeExceededError:
        cleanup_temp_file(temp_path)
        raise

    return temp_path


def cleanup_temp_file(file_path: str | None) -> None:
    """Best-effort cleanup; silently swallows OSError because cleanup races
    with concurrent reads are expected on the SSE / FileResponse paths."""

    if file_path and os.path.exists(file_path):
        with contextlib.suppress(OSError):
            os.remove(file_path)
