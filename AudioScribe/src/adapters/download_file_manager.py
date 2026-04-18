import logging
import os
import tempfile
import threading
import time
import uuid

from src.config.config import settings

logger = logging.getLogger(__name__)

_file_registry: dict[str, tuple[str, float]] = {}
_registry_lock = threading.Lock()


def store_transcript(content: str, filename: str = "transcript.md") -> str:
    file_id = uuid.uuid4().hex
    safe_filename = f"audioscribe_{file_id}_{filename}"
    file_path = os.path.join(tempfile.gettempdir(), safe_filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)

    with _registry_lock:
        _file_registry[file_id] = (file_path, time.monotonic())

    logger.info(f"Stored transcript as {file_path} (id={file_id})")
    return file_id


def get_transcript_path(file_id: str) -> str | None:
    with _registry_lock:
        entry = _file_registry.get(file_id)

    if not entry:
        return None

    file_path, created_at = entry
    elapsed = time.monotonic() - created_at

    if elapsed > settings.DOWNLOAD_FILE_TTL_SECONDS:
        _remove_entry(file_id, file_path)
        return None

    if not os.path.exists(file_path):
        _remove_entry(file_id)
        return None

    return file_path


def remove_transcript(file_id: str) -> None:
    with _registry_lock:
        entry = _file_registry.pop(file_id, None)

    if entry:
        _cleanup_file(entry[0])


def cleanup_expired() -> None:
    now = time.monotonic()
    expired_ids = []

    with _registry_lock:
        for fid, (path, created_at) in _file_registry.items():
            if now - created_at > settings.DOWNLOAD_FILE_TTL_SECONDS:
                expired_ids.append((fid, path))

    for fid, path in expired_ids:
        _remove_entry(fid, path)

    if expired_ids:
        logger.info(f"Cleaned up {len(expired_ids)} expired transcript files.")


def _remove_entry(file_id: str, file_path: str | None = None) -> None:
    with _registry_lock:
        entry = _file_registry.pop(file_id, None)

    path = file_path or (entry[0] if entry else None)
    if path:
        _cleanup_file(path)


def _cleanup_file(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass
