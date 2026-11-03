import logging
import re
from pathlib import Path
from urllib.parse import urlparse

import aiofiles
import aiohttp
from ascend_python_common.uri_guard import check_fetch_uri
from ascend_python_common.uri_guard_aiohttp import PinnedResolver, guarded_get

from src.adapters.file_service import cleanup_temp_file, create_temp_file, safe_suffix_from_filename
from src.api.exception_handlers import FileSizeExceededError
from src.config.config import settings

logger = logging.getLogger(__name__)


def _extract_audio_suffix_from_query(query: str) -> str:
    """Attempt to find a valid audio file extension in the query parameters.
    Useful for URLs like S3 presigned URLs where the filename is a
    parameter, e.g. `?file=foo.mp3&sig=...`."""

    extensions_pattern = "|".join(settings.SUPPORTED_AUDIO_EXTENSIONS)
    match = re.search(r"\.(" + extensions_pattern + r")(?:$|[&?])", query, re.IGNORECASE)
    if match:
        return "." + match.group(1)
    return ""


async def _copy_file_streaming(source: Path, dest_path: str, cap: int) -> None:
    """Copy a local file in fixed-size chunks, enforcing the size cap so a
    100 GB file mounted under the jail cannot OOM the temp disk."""

    written = 0
    buffer_size = settings.UPLOAD_BUFFER_BYTES
    async with aiofiles.open(source, "rb") as src, aiofiles.open(dest_path, "wb") as dst:
        while True:
            chunk = await src.read(buffer_size)
            if not chunk:
                break
            written += len(chunk)
            if written > cap:
                raise FileSizeExceededError(f"file:// source exceeds {cap} bytes")
            await dst.write(chunk)


async def _fetch_http_streaming(uri: str, dest_path: str, cap: int) -> None:
    """Stream an HTTP(S) body in fixed-size chunks via aiohttp, enforcing
    the size cap while looping. Honours Content-Length as an early reject."""

    timeout = aiohttp.ClientTimeout(total=settings.MCP_DOWNLOAD_TIMEOUT_SECONDS)
    connector = aiohttp.TCPConnector(resolver=PinnedResolver(), use_dns_cache=False)
    async with (
        aiohttp.ClientSession(timeout=timeout, connector=connector) as session,
        guarded_get(session, uri, settings.fetch_policy()) as response,
    ):
        if response.status != 200:
            raise ValueError(f"Failed to download from {uri}: HTTP {response.status}")
        content_length = response.content_length
        if content_length is not None and content_length > cap:
            raise FileSizeExceededError(f"Content-Length {content_length} exceeds cap of {cap} bytes")

        written = 0
        buffer_size = settings.UPLOAD_BUFFER_BYTES
        async with aiofiles.open(dest_path, "wb") as out_file:
            async for chunk in response.content.iter_chunked(buffer_size):
                written += len(chunk)
                if written > cap:
                    raise FileSizeExceededError(f"Streamed body exceeds cap of {cap} bytes")
                await out_file.write(chunk)


async def download_to_temp_async(uri: str) -> str:
    """Async download from URI to a temp file. Supports:
      - file:// (only when MCP_FILE_URI_ROOT is set; realpath-jailed)
      - http(s):// (SSRF-guarded, streamed with MAX_DOWNLOAD_BYTES cap)
    Any other scheme is rejected.
    """

    parsed = urlparse(uri)
    scheme = parsed.scheme.lower()

    if scheme == "file":
        target = await check_fetch_uri(uri, settings.fetch_policy())
        source = target.file_path
        if source is None or not source.exists():
            raise ValueError(f"File not found: {source}")
        suffix = safe_suffix_from_filename(str(source))
        temp_path = create_temp_file(suffix)
        try:
            await _copy_file_streaming(source, temp_path, settings.MAX_DOWNLOAD_BYTES)
        except Exception:
            # Any failure mid-fetch leaves a half-written file on disk;
            # remove it before propagating so the temp partition doesn't
            # accumulate orphans.
            cleanup_temp_file(temp_path)
            raise

        return temp_path

    if scheme in ("http", "https"):
        await check_fetch_uri(uri, settings.fetch_policy())

        suffix = safe_suffix_from_filename(parsed.path)
        if not suffix and parsed.query:
            suffix = _extract_audio_suffix_from_query(parsed.query)
        temp_path = create_temp_file(suffix)
        try:
            await _fetch_http_streaming(uri, temp_path, settings.MAX_DOWNLOAD_BYTES)
        except Exception:
            # Any failure mid-fetch leaves a half-written file on disk;
            # remove it before propagating so the temp partition doesn't
            # accumulate orphans.
            cleanup_temp_file(temp_path)
            raise

        return temp_path

    raise ValueError(f"Unsupported URI scheme: '{scheme}'")
