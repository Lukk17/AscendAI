from __future__ import annotations

import logging
import mimetypes
import os
import shutil
import tempfile
from pathlib import Path
from typing import Iterable, Optional

from fastapi import UploadFile

from src.audio.analyzer import get_audio_duration

logger = logging.getLogger(__name__)


def get_file_extension(file_path: str) -> str:
    """
    Extract file extension without the dot from file path.
    Returns lowercase extension or empty string if no extension.
    """
    _, ext = os.path.splitext(file_path)
    return ext[1:].lower() if ext else ""


def build_filename(prefix: str, original_filename: str, output_path: str) -> str:
    """
    Build filename using the prefix + original name and extension from output_path.
    Example: "converted_audio.mp3" from prefix="converted", original="audio.wav", output ends with .mp3
    """
    base = remove_extension(original_filename)

    output_ext = retrieve_extension(output_path)
    return f"{prefix}_{base}.{output_ext}"


def retrieve_extension(output_path: str) -> str:
    return output_path.split('.')[-1]


def remove_extension(original_filename: str) -> str:
    return original_filename.rsplit('.', 1)[0]


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


def save_upload_to_temp(upload: UploadFile) -> str:
    """
    Persist an UploadFile to a non-deleting NamedTemporaryFile and return the file path.
    """
    suffix = _safe_suffix_from_filename(upload.filename or "")
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        upload.file.seek(0)

        shutil.copyfileobj(upload.file, tmp)  # type: ignore | tmp is already the correct type for copyfileobj
        return tmp.name


def create_temp_path(extension: Optional[str] = None, prefix: str = "", suffix: Optional[str] = None) -> str:
    """
    Create a unique temporary file path without creating the file.
    - extension: pass like "mp3" or ".mp3" to set extension
    - suffix: full suffix overrides extension if provided
    Returns an absolute file path string.
    """
    if suffix is None:
        if extension:
            ext = extension if extension.startswith(".") else f".{extension}"
        else:
            ext = ""
        suffix = ext

    # Create a NamedTemporaryFile to get a unique name, then remove the file
    with tempfile.NamedTemporaryFile(delete=False, prefix=prefix, suffix=suffix) as tmp:
        path = tmp.name

    # Remove the created file so external tools can create it fresh
    os.unlink(path)
    return path


def cleanup_paths(paths: Iterable[Optional[str]]) -> None:
    """
    Delete files for given paths if they exist. Ignores None and non-existing paths.
    """
    for p in paths:
        if not p:
            continue
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def ensure_parent_dir(path: str) -> None:
    """
    Ensure the parent directory exists for the path.
    """
    parent = Path(path).parent
    parent.mkdir(parents=True, exist_ok=True)


def get_media_type_from_path(path: str) -> str:
    """
    Get media type from file extension using Python's mimetypes module.
    Returns audio/octet-stream if unknown.

    octet-stream: A generic binary format when the specific type is unknown.
    It tells the browser to treat the file as a binary download.
    """
    # First, try the standard library
    mime_type, _ = mimetypes.guess_type(path)
    if mime_type and mime_type.startswith('audio/'):
        return mime_type

    # Fallback for common audio types not in mimetypes
    ext = Path(path).suffix.lower()
    audio_types = {
        '.mp3': 'audio/mpeg',
        '.wav': 'audio/wav',
        '.ogg': 'audio/ogg',
        '.m4a': 'audio/mp4',
        '.mp4': 'audio/mp4',
        '.flac': 'audio/flac',
        '.aac': 'audio/aac',
        '.wma': 'audio/x-ms-wma',
        '.opus': 'audio/opus',
        '.aiff': 'audio/aiff',
        '.au': 'audio/basic',
    }

    return audio_types.get(ext, 'audio/octet-stream')


def print_file_info(file_path: str) -> None:
    """Log file size and duration information."""
    if not os.path.exists(file_path):
        logger.warning(f"File not found: {file_path}")
        return

    file_size_mb = os.path.getsize(file_path) / (1024 * 1024)
    duration_sec = get_audio_duration(file_path)
    duration_min = duration_sec / 60

    logger.info(
        f"File: {os.path.basename(file_path)} | Size: {file_size_mb:.2f}MB | Duration: {duration_min:.2f}min ({duration_sec:.1f}s)")
