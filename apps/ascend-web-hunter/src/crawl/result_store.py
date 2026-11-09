"""Crawl result objects in Floci.

Keys carry the tenant prefix: ``tenant/<tenantId>/<prefix><job_id>/`` holds
``pages.ndjson`` (one line per page: URL, status, content hash, fetched time,
result key) and ``pages/<sha256 of URL>.md`` (or ``.json`` for ``schema``).
A recrawl that finds a page unchanged copies the earlier page file forward
to the new job's key with a server-side copy, so the bytes never pass the
service and every job keeps every reached page until it expires. Every
object under ``tenant/`` in the crawl bucket expires through one bucket
lifecycle rule ``CRAWL_JOB_RETENTION_SECONDS`` after it was written, rounded
up to whole days. The rule is set once per process at crawl worker startup,
merged into the bucket's other rules. A store that refuses it leaves results
without expiry: a WARNING, the startup banner and the
``crawl_result_expiry_rule_applied`` gauge report it, and pages are still
written.
"""

import hashlib
import json
import logging
import math
from dataclasses import dataclass
from typing import Any

import redis.asyncio as redis
from botocore.exceptions import BotoCoreError, ClientError

from src.config.config import settings
from src.crawl.keys import recrawl_key
from src.crawl.models import CrawlRequest
from src.observability.metrics import CRAWL_RESULT_EXPIRY_RULE_APPLIED
from src.storage.object_store import ObjectStore

logger = logging.getLogger(__name__)

RESULT_KEY_ROOT = "tenant/"
SECONDS_PER_DAY = 86400


@dataclass(slots=True)
class ExpiryRuleStatus:
    """Outcome of this process's lifecycle rule attempt: ``applied`` is None until it ran."""

    applied: bool | None = None
    error: str | None = None


expiry_rule_status = ExpiryRuleStatus()

REVERT_SCRIPT = """
if redis.call('HGET', KEYS[1], ARGV[1]) ~= ARGV[2] then
  return 0
end
if ARGV[3] == '' then
  redis.call('HDEL', KEYS[1], ARGV[1])
else
  redis.call('HSET', KEYS[1], ARGV[1], ARGV[3])
end
return 1
"""


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


def recrawl_scope(request: CrawlRequest) -> str:
    """Hash one tenant scope: every request option a stored page or its stored links depend on."""
    scope = {
        "seeds": sorted(str(seed) for seed in request.seeds),
        "include_patterns": sorted(request.include_patterns),
        "exclude_patterns": sorted(request.exclude_patterns),
        "output_format": request.output_format,
        "extraction_schema": request.extraction_schema,
        "profile": request.profile,
    }
    canonical = json.dumps(scope, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def retention_days() -> int:
    return max(1, math.ceil(settings.CRAWL_JOB_RETENTION_SECONDS / SECONDS_PER_DAY))


def page_extension(output_format: str) -> str:
    return ".json" if output_format == "schema" else ".md"


def page_object_key(tenant_id: str, job_id: str, url: str, output_format: str) -> str:
    name = hashlib.sha256(normalize_url(url).encode("utf-8")).hexdigest()
    return (
        f"{RESULT_KEY_ROOT}{tenant_id}/{settings.CRAWL_RESULT_S3_PREFIX}{job_id}/pages/"
        f"{name}{page_extension(output_format)}"
    )


def index_object_key(tenant_id: str, job_id: str) -> str:
    return f"{RESULT_KEY_ROOT}{tenant_id}/{settings.CRAWL_RESULT_S3_PREFIX}{job_id}/pages.ndjson"


class ResultStore:
    def __init__(self, objects: ObjectStore | None = None) -> None:
        self._objects = objects if objects is not None else ObjectStore()

    @property
    def bucket(self) -> str:
        return settings.CRAWL_RESULT_S3_BUCKET

    async def apply_expiry_rule(self) -> None:
        """Set the result lifecycle rule once per process, warning rather than raising on a refusal."""
        if expiry_rule_status.applied is not None:
            return
        try:
            await self._objects.ensure_bucket(self.bucket)
            await self._objects.set_expiry(self.bucket, RESULT_KEY_ROOT, retention_days())
        except (ClientError, BotoCoreError) as exc:
            logger.warning(
                "crawl: result expiry rule for bucket %s was not set, results will not expire: %s",
                self.bucket,
                exc,
            )
            expiry_rule_status.applied = False
            expiry_rule_status.error = type(exc).__name__
            CRAWL_RESULT_EXPIRY_RULE_APPLIED.labels(bucket=self.bucket).set(0)
            return
        expiry_rule_status.applied = True
        expiry_rule_status.error = None
        CRAWL_RESULT_EXPIRY_RULE_APPLIED.labels(bucket=self.bucket).set(1)

    async def write_page(self, key: str, content: str) -> None:
        await self._objects.ensure_bucket(self.bucket)
        await self._objects.put_text(self.bucket, key, content)

    async def read_page(self, key: str) -> str | None:
        return await self._objects.get_text(self.bucket, key)

    async def page_exists(self, key: str) -> bool:
        return await self._objects.head(self.bucket, key)

    async def copy_page_forward(self, source_key: str, dest_key: str) -> None:
        await self._objects.copy_inside_bucket(self.bucket, source_key, dest_key)

    async def delete_page(self, key: str) -> None:
        await self._objects.delete(self.bucket, key)

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
    """Per-tenant recrawl state in Redis.

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

    async def write(self, tenant_id: str, scope: str, url: str, entry: dict[str, Any]) -> str:
        """Store *entry* for *url* and answer the stored value, which :meth:`revert` takes back."""
        key = self.key(tenant_id, scope)
        value = json.dumps(entry, sort_keys=True)
        await self._client.hset(key, normalize_url(url), value)
        await self._client.expire(key, settings.CRAWL_JOB_RETENTION_SECONDS)
        return value

    async def revert(
        self, tenant_id: str, scope: str, url: str, written: str, prior: dict[str, Any] | None
    ) -> None:
        """Put back *prior*, or remove the field, while it still holds *written*.

        An entry another job wrote after *written* stays as it is.
        """
        restored = json.dumps(prior, sort_keys=True) if prior is not None else ""
        await self._client.eval(
            REVERT_SCRIPT, 1, self.key(tenant_id, scope), normalize_url(url), written, restored
        )
