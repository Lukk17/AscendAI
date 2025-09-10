import aiofiles
import os
import tempfile
from fastapi import UploadFile
from pathlib import Path
from typing import Optional


def _create_temp_file(suffix: str = "") -> str:
    """
    Create a temporary file synchronously and return its path.
    """
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        return tmp.name


def _safe_suffix_from_filename(filename: str) -> str:
    """
    Build a safe suffix for a temporary file based on the original filename's suffix.
    Returns an empty string if the filename has no extension.
    """
    try:
        suffix = Path(filename).suffix  # includes a leading dot if any
        return suffix if suffix else ""
    except Exception:
        return ""


async def save_upload_to_temp_async(upload: UploadFile) -> str:
    """
    Asynchronously save an UploadFile to a temporary file and return the file path.
    """
    suffix = _safe_suffix_from_filename(upload.filename or "")

    temp_path = _create_temp_file(suffix)

    await upload.seek(0)
    async with aiofiles.open(temp_path, 'wb') as out_file:
        content = await upload.read()
        await out_file.write(content)

    return temp_path


def cleanup_temp_file_async(file_path: Optional[str]) -> None:
    """
    Asynchronously clean up a temporary file if it exists.
    """
    if file_path and os.path.exists(file_path):
        try:
            os.remove(file_path)
        except Exception:
            pass
