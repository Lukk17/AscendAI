import asyncio
import contextlib
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


def store_transcript(content: str, filename: str = "transcript.md") -> tuple[str, str]:
    """Persist a transcript to a temp file and register it under a random id.
    Returns (file_id, file_path) so callers can avoid the redundant registry
    re-lookup the old API forced."""

    file_id = uuid.uuid4().hex
    safe_filename = f"audioscribe_{file_id}_{filename}"
    file_path = os.path.join(tempfile.gettempdir(), safe_filename)

    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    os.chmod(file_path, 0o600)

    with _registry_lock:
        _file_registry[file_id] = (file_path, time.monotonic())

    logger.info(f"Stored transcript at {file_path} (id={file_id})")
    return file_id, file_path


def get_transcript_path(file_id: str) -> str | None:
    """Resolve a file_id to its path if still valid (within TTL and on disk).
    Otherwise, drop the registry entry and return None."""

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
    """Remove the registry entry and delete the underlying file."""

    with _registry_lock:
        entry = _file_registry.pop(file_id, None)

    if entry:
        _cleanup_file(entry[0])


def cleanup_expired() -> None:
    """Sweep the registry for entries past their TTL. Holds the lock for the
    full collect-and-pop so a concurrent get_transcript_path cannot return a
    path that is about to be deleted (TOCTOU fix vs the previous design)."""

    now = time.monotonic()
    expired_paths: list[str] = []

    with _registry_lock:
        expired_ids = [
            fid
            for fid, (_, created_at) in _file_registry.items()
            if now - created_at > settings.DOWNLOAD_FILE_TTL_SECONDS
        ]
        for fid in expired_ids:
            entry = _file_registry.pop(fid, None)
            if entry is not None:
                expired_paths.append(entry[0])

    for path in expired_paths:
        _cleanup_file(path)

    if expired_paths:
        logger.info(f"Cleaned up {len(expired_paths)} expired transcript files.")


async def run_cleanup_loop(stop_event: asyncio.Event) -> None:
    """Background sweep task installed from the FastAPI lifespan so orphaned
    transcripts don't survive indefinitely when nobody hits the download
    endpoint."""

    interval = settings.DOWNLOAD_CLEANUP_INTERVAL_SECONDS
    while not stop_event.is_set():
        try:
            await asyncio.to_thread(cleanup_expired)
        except Exception:
            logger.exception("Background cleanup sweep failed")
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            continue


def _remove_entry(file_id: str, file_path: str | None = None) -> None:
    with _registry_lock:
        entry = _file_registry.pop(file_id, None)

    path = file_path or (entry[0] if entry else None)
    if path:
        _cleanup_file(path)


def _cleanup_file(path: str) -> None:
    with contextlib.suppress(OSError):
        os.remove(path)
