import ipaddress
import logging
import re
import socket
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import url2pathname

import aiofiles
import aiohttp

from src.adapters.file_service import cleanup_temp_file, create_temp_file, safe_suffix_from_filename
from src.api.exception_handlers import FileSizeExceededError
from src.config.config import settings

logger = logging.getLogger(__name__)


def _extract_audio_suffix_from_query(query: str) -> str:
    """Attempt to find a valid audio file extension in the query parameters.
    Useful for URLs like MinIO presigned URLs where the filename is a
    parameter, e.g. `?file=foo.mp3&sig=...`."""

    extensions_pattern = "|".join(settings.SUPPORTED_AUDIO_EXTENSIONS)
    match = re.search(r"\.(" + extensions_pattern + r")(?:$|[&?])", query, re.IGNORECASE)
    if match:
        return "." + match.group(1)
    return ""


def _resolve_to_ips(hostname: str) -> list[str]:
    """Resolve a hostname to every IPv4/IPv6 it points at. Empty list on
    failure — callers treat that as "do not allow"."""

    try:
        infos = socket.getaddrinfo(hostname, None)
    except socket.gaierror:
        return []
    return list({str(info[4][0]) for info in infos})


def _is_safe_ip(addr: str) -> bool:
    """True only when the IP is publicly routable (not private, loopback,
    link-local, multicast, reserved, or unspecified). The SSRF guard."""

    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _validate_http_target(hostname: str | None) -> None:
    """SSRF guard. Rejects loopback, RFC1918, link-local, cloud metadata
    (169.254/16), and similar unless the hostname appears verbatim in
    MCP_ALLOWED_HOSTS (intended for the docker-internal MinIO pattern)."""

    if not hostname:
        raise ValueError("URI has no hostname")
    if hostname in settings.MCP_ALLOWED_HOSTS:
        return
    ips = _resolve_to_ips(hostname)
    if not ips:
        raise ValueError(f"Could not resolve host '{hostname}'")
    if not all(_is_safe_ip(ip) for ip in ips):
        raise ValueError(f"Host '{hostname}' resolves to a non-public address (SSRF blocked)")


def _resolve_file_uri(uri_path: str) -> Path:
    """file:// scheme jail. Requires MCP_FILE_URI_ROOT to be set; resolves the
    URI path under that root and rejects any traversal outside via realpath."""

    if not settings.MCP_FILE_URI_ROOT:
        raise ValueError("file:// scheme is disabled (MCP_FILE_URI_ROOT not set)")
    root = Path(settings.MCP_FILE_URI_ROOT).resolve()

    relative = url2pathname(uri_path)
    candidate = (root / relative.lstrip("/\\")).resolve()
    if not candidate.is_relative_to(root):
        raise ValueError("file:// path escapes MCP_FILE_URI_ROOT jail")
    if not candidate.exists():
        raise ValueError(f"File not found: {candidate}")
    return candidate


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
    async with aiohttp.ClientSession(timeout=timeout) as session, session.get(uri) as response:
        if response.status != 200:
            raise ValueError(f"Failed to download from {uri}: HTTP {response.status}")
        content_length = response.content_length
        if content_length is not None and content_length > cap:
            raise FileSizeExceededError(
                f"Content-Length {content_length} exceeds cap of {cap} bytes"
            )

        written = 0
        buffer_size = settings.UPLOAD_BUFFER_BYTES
        async with aiofiles.open(dest_path, "wb") as out_file:
            async for chunk in response.content.iter_chunked(buffer_size):
                written += len(chunk)
                if written > cap:
                    raise FileSizeExceededError(
                        f"Streamed body exceeds cap of {cap} bytes"
                    )
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
        source = _resolve_file_uri(parsed.path)
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
        _validate_http_target(parsed.hostname)

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
