"""Crawl result objects in Floci (design D3 and D6).

Keys carry the tenant prefix: ``tenant/<tenantId>/<prefix><job_id>/`` holds
``pages.ndjson`` (one line per page: URL, status, content hash, fetched time,
result key) and ``pages/<sha256 of URL>.md`` (or ``.json`` for ``schema``).
A recrawl that finds a page unchanged copies the earlier page file forward
to the new job's key with a server-side copy, so the bytes never pass the
service and every job keeps every reached page until it expires.
"""

import hashlib
import json
from typing import Any

import redis.asyncio as redis

from src.config.config import settings
from src.crawl.keys import recrawl_key
from src.storage.object_store import ObjectStore


def normalize_url(url: str) -> str:
    """Normalise a URL for the seen set and the recrawl state.

    Lowercases the scheme and host and drops the fragment. Two spellings of
    one page share one entry.
    """
    from urllib.parse import urlparse, urlunparse

    parsed = urlparse(url.strip())
    netloc = parsed.netloc.lower()
    cleaned = parsed._replace(scheme=parsed.scheme.lower(), netloc=netloc, fragment="")
    return urlunparse(cleaned)


def recrawl_scope(seeds: list[str], include_patterns: list[str]) -> str:
    """Hash one tenant scope: the sorted seeds and include patterns."""
    digest = hashlib.sha256()
    for part in sorted(seeds) + sorted(include_patterns):
        digest.update(part.encode("utf-8"))
        digest.update(b"\x00")
    return digest.hexdigest()


def page_extension(output_format: str) -> str:
    return ".json" if output_format == "schema" else ".md"


def page_object_key(tenant_id: str, job_id: str, url: str, output_format: str) -> str:
    name = hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()
    return (
        f"tenant/{tenant_id}/{settings.CRAWL_RESULT_S3_PREFIX}{job_id}/pages/"
        f"{name}{page_extension(output_format)}"
    )


def index_object_key(tenant_id: str, job_id: str) -> str:
    return f"tenant/{tenant_id}/{settings.CRAWL_RESULT_S3_PREFIX}{job_id}/pages.ndjson"


class ResultStore:
    def __init__(self, objects: ObjectStore | None = None) -> None:
        self._objects = objects if objects is not None else ObjectStore()

    @property
    def bucket(self) -> str:
        return settings.CRAWL_RESULT_S3_BUCKET

    async def write_page(self, key: str, content: str) -> None:
        await self._objects.ensure_bucket(self.bucket)
        await self._objects.put_text(self.bucket, key, content)

    async def read_page(self, key: str) -> str | None:
        return await self._objects.get_text(self.bucket, key)

    async def page_exists(self, key: str) -> bool:
        return await self._objects.head(self.bucket, key)

    async def copy_page_forward(self, source_key: str, dest_key: str) -> None:
        await self._objects.copy_inside_bucket(self.bucket, source_key, dest_key)

    async def write_index(self, key: str, lines: list[dict[str, Any]]) -> None:
        await self._objects.ensure_bucket(self.bucket)
        body = "".join(json.dumps(line, sort_keys=True) + "\n" for line in lines)
        await self._objects.put_bytes(self.bucket, key, body.encode("utf-8"))

    async def read_index(self, key: str) -> list[dict[str, Any]]:
        text = await self._objects.get_text(self.bucket, key)
        if text is None:
            return []
        return [json.loads(line) for line in text.splitlines() if line.strip()]


class RecrawlStore:
    """Per-tenant recrawl state in Redis (design D6 and D12).

    One hash per tenant and crawl scope with one field per normalised URL.
    Each write sets the expiry of ``CRAWL_JOB_RETENTION_SECONDS`` again, so
    the state of a scope nobody crawls again is gone that long after its
    last job. A job only ever writes the hash of its own tenant.
    """

    def __init__(self, client: redis.Redis) -> None:
        self._client = client

    def key(self, tenant_id: str, scope: str) -> str:
        return recrawl_key(tenant_id, scope)

    async def read(self, tenant_id: str, scope: str, url: str) -> dict[str, Any] | None:
        raw = await self._client.hget(self.key(tenant_id, scope), normalize_url(url))
        if raw is None:
            return None
        try:
            entry: dict[str, Any] = json.loads(raw)
        except ValueError:
            return None
        return entry if isinstance(entry, dict) else None

    async def write(
        self, tenant_id: str, scope: str, url: str, entry: dict[str, Any]
    ) -> None:
        key = self.key(tenant_id, scope)
        await self._client.hset(key, normalize_url(url), json.dumps(entry, sort_keys=True))
        await self._client.expire(key, settings.CRAWL_JOB_RETENTION_SECONDS)
