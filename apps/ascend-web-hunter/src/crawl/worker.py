"""Crawl worker tasks (design D5, D6 and D15).

Each instance runs ``CRAWL_WORKER_CONCURRENCY`` tasks of :meth:`Worker.run_forever`.
One iteration claims at most one URL through the frontier scripts, so one
instance never reads more pages at once than it has tasks, while the
per-domain cap, the crawl delay and the page budget hold for all instances
together. Every fetch runs inside the crawl proxy context (design D7).
Discovered links, redirect hops, robots.txt and sitemap fetches all pass
the same guard and connect-time pinning as a single read (design D4): a
link the guard refuses is dropped and counted as ``skipped_unsafe``.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import cast
from urllib.parse import urlparse

import redis.asyncio as redis
from ascend_python_common.uri_guard import FetchPolicy, UnsafeUriError, check_fetch_uri

from src.config.config import settings
from src.crawl import fetcher
from src.crawl.fetcher import ConditionalProbe
from src.crawl.frontier import Frontier
from src.crawl.keys import (
    RUNNABLE_KEY,
    claims_key,
    inflight_key,
    job_key,
    next_fetch_key,
    pages_key,
    queue_key,
    seen_key,
)
from src.crawl.models import CrawlRequest, JobRecord, match_glob
from src.crawl.result_store import (
    RecrawlStore,
    ResultStore,
    index_object_key,
    normalize_url,
    page_object_key,
    recrawl_scope,
)
from src.crawl.robots import RobotsStore
from src.proxy.proxy_provider import crawl_proxy
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.web_reader import WebReader

logger = logging.getLogger(__name__)

ProbeFn = Callable[..., Awaitable[ConditionalProbe]]

TERMINAL_STATES = ("succeeded", "failed", "cancelled")


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


class Worker:
    """One crawl worker shared by the worker tasks of one instance."""

    def __init__(
        self,
        client: redis.Redis,
        *,
        reader: WebReader | None = None,
        frontier: Frontier | None = None,
        robots: RobotsStore | None = None,
        results: ResultStore | None = None,
        recrawl: RecrawlStore | None = None,
        probe: ProbeFn | None = None,
        clock_ms: Callable[[], int] | None = None,
    ) -> None:
        self._client = client
        self._reader = reader if reader is not None else WebReader()
        self._frontier = frontier if frontier is not None else Frontier(client)
        self._robots = robots if robots is not None else RobotsStore()
        self._results = results if results is not None else ResultStore()
        self._recrawl = recrawl if recrawl is not None else RecrawlStore(client)
        self._probe = probe if probe is not None else fetcher.conditional_probe
        self._clock_ms = clock_ms if clock_ms is not None else (lambda: int(time.time() * 1000))
        self._seeded: set[tuple[str, str]] = set()

    def _fetch_policy(self) -> FetchPolicy:
        return FetchPolicy(
            allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
            file_root=None,
            max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
        )

    async def run_forever(self, stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                claimed = await self.run_once()
            except Exception as exc:
                logger.warning("crawl: worker sweep failed: %s", exc)
                claimed = False
            if not claimed:
                await asyncio.sleep(settings.CRAWL_WORKER_IDLE_SECONDS)

    async def run_once(self) -> bool:
        """Sweep the runnable set once. Answers True when a page was read."""
        try:
            members = await self._frontier.list_runnable()
        except Exception as exc:
            logger.warning("crawl: runnable read failed: %s", exc)
            return False
        for member in members:
            if await self._drain_member(member):
                return True
        return False

    async def _drain_member(self, member: str) -> bool:
        tenant_id, _, job_id = member.partition(":")
        if not tenant_id or not job_id:
            await self._frontier.remove_runnable_member(member)
            return False
        try:
            record = await self._load_record(tenant_id, job_id)
        except Exception as exc:
            logger.warning("crawl: job read failed for %s: %s", member, exc)
            return False
        if record is None:
            await self._frontier.remove_runnable_member(member)
            return False
        if record.state in TERMINAL_STATES:
            await self._frontier.remove_runnable_member(member)
            return False
        seeds = [cookie_manager.registrable_domain(str(seed)) for seed in record.request.seeds]
        for domain in record.domains or seeds:
            if await self._try_domain(tenant_id, job_id, member, record, domain):
                return True
        return False

    async def _load_record(self, tenant_id: str, job_id: str) -> JobRecord | None:
        raw = await self._client.get(job_key(tenant_id, job_id))
        if raw is None:
            return None
        try:
            return JobRecord.model_validate_json(raw)
        except ValueError:
            await self._frontier.remove_runnable_member(f"{tenant_id}:{job_id}")
            return None

    async def _try_domain(
        self, tenant_id: str, job_id: str, member: str, record: JobRecord, domain: str
    ) -> bool:
        delay_ms = await self._domain_delay_ms(record, domain)
        try:
            answer = await self._frontier.claim(
                job_key=job_key(tenant_id, job_id),
                queue_key=queue_key(tenant_id, job_id, domain),
                inflight_key=inflight_key(tenant_id, job_id, domain),
                claims_key=claims_key(tenant_id, job_id),
                next_fetch_key=next_fetch_key(tenant_id, job_id, domain),
                runnable_key=RUNNABLE_KEY,
                now_ms=self._clock_ms(),
                lease_ms=settings.CRAWL_CLAIM_LEASE_SECONDS * 1000,
                page_budget=record.request.page_budget,
                domain_cap=settings.CRAWL_DOMAIN_CONCURRENCY,
                delay_ms=delay_ms,
                retention=settings.CRAWL_JOB_RETENTION_SECONDS,
                member=member,
                max_expiries=settings.CRAWL_CLAIM_MAX_EXPIRIES,
                updated_at=_now_iso(),
            )
        except Exception as exc:
            logger.warning("crawl: claim failed for %s: %s", member, exc)
            return False
        status = answer[0]
        if status == "gone":
            await self._frontier.remove_runnable_member(member)
            return False
        if status == "idle":
            if len(answer) > 1:
                await self._frontier.remove_runnable_member(member)
            return False
        if status == "budget":
            if len(answer) > 1 and answer[1] == "succeeded":
                await self._finalize(tenant_id, job_id, member)
            return False
        if status != "claimed":
            return False
        await self._process_claim(tenant_id, job_id, member, record, domain, answer[1], int(answer[2]))
        return True

    async def _domain_delay_ms(self, record: JobRecord, domain: str) -> int:
        floor_ms = int(settings.CRAWL_DEFAULT_DELAY_SECONDS * 1000)
        if not record.request.respect_robots:
            return floor_ms
        try:
            rules = await self._robots.rules(record.job_id, f"https://{domain}/")
        except Exception as exc:
            logger.warning("crawl: robots read failed for %s: %s", domain, exc)
            return floor_ms
        if rules is None:
            return floor_ms
        extra = rules.crawl_delay("*")
        if extra is None:
            return floor_ms
        return max(floor_ms, int(extra * 1000))

    async def _process_claim(
        self,
        tenant_id: str,
        job_id: str,
        member: str,
        record: JobRecord,
        domain: str,
        url: str,
        depth: int,
    ) -> None:
        entry = f"{depth}\t{url}"
        with crawl_proxy():
            if await self._is_disallowed(record, url):
                outcome: str = "failed"
                page_line = ""
                links: list[dict[str, object]] = []
                skipped = 0
            else:
                try:
                    sitemap_skipped = await self._seed_sitemaps(tenant_id, job_id, record, domain, depth)
                    outcome, page_line, links, skipped = await self._read_page(
                        tenant_id, job_id, record, url, depth
                    )
                    skipped += sitemap_skipped
                except Exception as exc:
                    logger.warning("crawl: page processing of %s failed: %s", url, exc)
                    outcome, page_line, links, skipped = "failed", "", [], 0
        await self._finish(
            tenant_id,
            job_id,
            member,
            record,
            domain,
            entry,
            outcome=outcome,
            page_line=page_line,
            links=links,
            skipped=skipped,
        )

    async def _is_disallowed(self, record: JobRecord, url: str) -> bool:
        if not record.request.respect_robots:
            return False
        try:
            rules = await self._robots.rules(record.job_id, url)
        except Exception as exc:
            logger.warning("crawl: robots read failed for %s: %s", url, exc)
            return False
        return rules is not None and not rules.can_fetch(url, "*")

    async def _seed_sitemaps(
        self, tenant_id: str, job_id: str, record: JobRecord, domain: str, depth: int
    ) -> int:
        if (job_id, domain) in self._seeded:
            return 0
        self._seeded.add((job_id, domain))
        if not record.request.respect_robots:
            return 0
        try:
            urls = await self._robots.sitemap_seed_urls(job_id, f"https://{domain}/")
        except Exception as exc:
            logger.warning("crawl: sitemap seed failed for %s: %s", domain, exc)
            return 0
        return await self._queue_new(tenant_id, job_id, record, urls, depth + 1)

    async def _queue_new(
        self,
        tenant_id: str,
        job_id: str,
        record: JobRecord,
        urls: list[str],
        depth: int,
    ) -> int:
        kept: list[dict[str, object]] = []
        skipped = 0
        for raw in urls:
            try:
                url = normalize_url(raw)
            except ValueError:
                continue
            try:
                await check_fetch_uri(url, self._fetch_policy())
            except UnsafeUriError:
                skipped += 1
                continue
            if self._filter_link(record, url, depth) is None:
                continue
            kept.append({"u": url, "d": depth, "domain": cookie_manager.registrable_domain(url)})
        if not kept:
            return skipped
        try:
            await self._frontier.add_urls(
                job_key=job_key(tenant_id, job_id),
                seen_key=seen_key(tenant_id, job_id),
                updated_at=_now_iso(),
                retention=settings.CRAWL_JOB_RETENTION_SECONDS,
                tenant_id=tenant_id,
                job_id=job_id,
                links_json=json.dumps(kept),
            )
        except Exception as exc:
            logger.warning("crawl: sitemap seed write failed for %s: %s", job_id, exc)
        return skipped

    def _filter_link(self, record: JobRecord, raw: str, depth: int) -> str | None:
        url = raw
        if depth > record.request.max_depth:
            return None
        if record.request.same_domain_only:
            seeds = {cookie_manager.registrable_domain(str(seed)) for seed in record.request.seeds}
            if cookie_manager.registrable_domain(url) not in seeds:
                return None
        path = urlparse(url).path
        include = record.request.include_patterns
        if include and not match_glob(include, path):
            return None
        if match_glob(record.request.exclude_patterns, path):
            return None
        return url

    async def _read_page(
        self, tenant_id: str, job_id: str, record: JobRecord, url: str, depth: int
    ) -> tuple[str, str, list[dict[str, object]], int]:
        request = record.request
        scope = recrawl_scope([str(seed) for seed in request.seeds], request.include_patterns)
        prior = await self._recrawl.read(tenant_id, scope, url)
        prior_key = prior.get("page_key") if prior is not None else None
        if not isinstance(prior_key, str):
            prior = None
            prior_key = None
        new_key = page_object_key(tenant_id, job_id, url, request.output_format)
        prior_exists = await self._results.page_exists(prior_key) if prior_key is not None else False
        etag: str | None = prior.get("etag") if prior is not None else None
        if not isinstance(etag, str):
            etag = None
        last_modified: str | None = prior.get("last_modified") if prior is not None else None
        if not isinstance(last_modified, str):
            last_modified = None
        fresh_etag, fresh_last_modified = etag, last_modified
        copyable = prior_exists
        if prior_exists and prior_key is not None and prior is not None:
            probe = await self._probe(url, etag=etag, last_modified=last_modified)
            fresh_etag, fresh_last_modified = probe.etag, probe.last_modified
            if probe.status == 304:
                copied = await self._copy_forward(tenant_id, scope, url, prior, prior_key, new_key, None, 0)
                if copied is not None:
                    return copied
                copyable = False
        content, links, skipped = await self._extract(record, url, depth)
        if content is None:
            return "failed", "", [], skipped
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if copyable and prior is not None and prior.get("hash") == digest and prior_key is not None:
            copied = await self._copy_forward(
                tenant_id, scope, url, prior, prior_key, new_key, links, skipped
            )
            if copied is not None:
                return copied
            copyable = False
        await self._results.write_page(new_key, content)
        if fresh_etag is None and fresh_last_modified is None:
            fresh_etag, fresh_last_modified = await fetcher.head_validators(url)
        await self._write_recrawl(
            tenant_id, scope, url, digest, fresh_etag, fresh_last_modified, new_key, links
        )
        line = json.dumps(
            {
                "url": url,
                "status": "fetched",
                "content_hash": digest,
                "fetched_at": _now_iso(),
                "key": new_key,
            },
            sort_keys=True,
        )
        return "ok", line, links, skipped

    async def _copy_forward(
        self,
        tenant_id: str,
        scope: str,
        url: str,
        prior: dict[str, object],
        prior_key: str,
        new_key: str,
        fresh_links: list[dict[str, object]] | None,
        fresh_skipped: int,
    ) -> tuple[str, str, list[dict[str, object]], int] | None:
        if fresh_links is None and not isinstance(prior.get("links"), list):
            return None
        try:
            await self._results.copy_page_forward(prior_key, new_key)
        except Exception as exc:
            logger.warning("crawl: copy forward of %s failed: %s", prior_key, exc)
            if not await self._results.page_exists(prior_key):
                return None
            raise
        digest = prior.get("hash")
        raw_etag = prior.get("etag")
        raw_modified = prior.get("last_modified")
        if fresh_links is not None:
            links_out = fresh_links
            skipped_out = fresh_skipped
        else:
            links_out = cast("list[dict[str, object]]", prior.get("links"))
            skipped_out = 0
        await self._write_recrawl(
            tenant_id,
            scope,
            url,
            digest if isinstance(digest, str) else "",
            raw_etag if isinstance(raw_etag, str) else None,
            raw_modified if isinstance(raw_modified, str) else None,
            new_key,
            links_out,
        )
        line = json.dumps(
            {
                "url": url,
                "status": "unchanged",
                "content_hash": digest,
                "fetched_at": _now_iso(),
                "key": new_key,
            },
            sort_keys=True,
        )
        return "unchanged", line, links_out, skipped_out

    async def _extract(
        self, record: JobRecord, url: str, depth: int
    ) -> tuple[str | None, list[dict[str, object]], int]:
        request = record.request
        try:
            linked = await self._reader.read_with_links(url, profile=request.profile)
        except Exception as exc:
            logger.warning("crawl: read of %s failed: %s", url, exc)
            return None, [], 0
        if linked.get("status") != "success":
            return None, [], 0
        raw_links = linked.get("links")
        urls: list[str] = []
        if isinstance(raw_links, dict):
            urls.extend(value for value in raw_links.values() if isinstance(value, str))
        content = linked.get("content")
        if not isinstance(content, str):
            return None, [], 0
        if request.output_format != "text":
            content = await self._extract_format(record, url)
            if content is None:
                return None, [], 0
        return await self._links_for(record, urls, depth, content)

    async def _extract_format(self, record: JobRecord, url: str) -> str | None:
        try:
            result = await self._reader.read(
                url,
                output_format=record.request.output_format,
                extraction_schema=record.request.extraction_schema,
                profile=record.request.profile,
            )
        except Exception as exc:
            logger.warning("crawl: formatted read of %s failed: %s", url, exc)
            return None
        if result.get("status") != "success":
            return None
        if "content" in result:
            shaped = result["content"]
            if isinstance(shaped, str):
                return shaped
            return json.dumps(shaped, sort_keys=True, default=str)
        return json.dumps(result, sort_keys=True, default=str)

    async def _links_for(
        self, record: JobRecord, urls: list[str], depth: int, content: str
    ) -> tuple[str, list[dict[str, object]], int]:
        kept: list[dict[str, object]] = []
        skipped = 0
        for raw in urls:
            try:
                url = normalize_url(raw)
            except ValueError:
                continue
            try:
                await check_fetch_uri(url, self._fetch_policy())
            except UnsafeUriError:
                skipped += 1
                continue
            item = self._filter_link(record, url, depth + 1)
            if item is None:
                continue
            kept.append({"u": item, "d": depth + 1, "domain": cookie_manager.registrable_domain(item)})
        return content, kept, skipped

    async def _write_recrawl(
        self,
        tenant_id: str,
        scope: str,
        url: str,
        digest: str,
        etag: str | None,
        last_modified: str | None,
        page_key: str,
        links: list[dict[str, object]],
    ) -> None:
        try:
            await self._recrawl.write(
                tenant_id,
                scope,
                url,
                {
                    "hash": digest,
                    "etag": etag,
                    "last_modified": last_modified,
                    "page_key": page_key,
                    "links": links,
                },
            )
        except Exception as exc:
            logger.warning("crawl: recrawl write failed for %s: %s", url, exc)

    async def _finish(
        self,
        tenant_id: str,
        job_id: str,
        member: str,
        record: JobRecord,
        domain: str,
        entry: str,
        *,
        outcome: str,
        page_line: str,
        links: list[dict[str, object]],
        skipped: int,
    ) -> None:
        try:
            answer = await self._frontier.finish(
                job_key=job_key(tenant_id, job_id),
                seen_key=seen_key(tenant_id, job_id),
                claims_key=claims_key(tenant_id, job_id),
                pages_key=pages_key(tenant_id, job_id),
                runnable_key=RUNNABLE_KEY,
                entry=entry,
                outcome=outcome,
                page_line=page_line,
                max_depth=record.request.max_depth,
                retention=settings.CRAWL_JOB_RETENTION_SECONDS,
                skipped_delta=skipped,
                tenant_id=tenant_id,
                job_id=job_id,
                domain=domain,
                links_json=json.dumps(links),
                updated_at=_now_iso(),
                member=member,
            )
        except Exception as exc:
            logger.warning("crawl: finish failed for %s: %s", member, exc)
            return
        status = answer[0]
        if status == "succeeded":
            await self._finalize(tenant_id, job_id, member)
        elif status in ("cancelled", "gone", "stale"):
            self._drop_job_caches(job_id)

    async def _finalize(self, tenant_id: str, job_id: str, member: str) -> None:
        try:
            raw = await self._client.get(job_key(tenant_id, job_id))
            if raw is None:
                return
            record = JobRecord.model_validate_json(raw)
            stored = await self._frontier.read_pages(pages_key(tenant_id, job_id))
            lines = [json.loads(line) for line in stored]
            index_key = index_object_key(tenant_id, job_id)
            await self._results.write_index(index_key, lines)
            await self._frontier.set_index_key(
                job_key=job_key(tenant_id, job_id),
                updated_at=_now_iso(),
                retention=settings.CRAWL_JOB_RETENTION_SECONDS,
                index_key=index_key,
            )
            await self._frontier.delete_frontier(tenant_id, job_id, record.domains)
        except Exception as exc:
            logger.warning("crawl: finalize failed for %s: %s", member, exc)
        finally:
            self._drop_job_caches(job_id)

    def _drop_job_caches(self, job_id: str) -> None:
        self._robots.drop_job(job_id)
        for key in [key for key in self._seeded if key[0] == job_id]:
            self._seeded.discard(key)


def seed_domains(request: CrawlRequest) -> list[str]:
    return sorted({cookie_manager.registrable_domain(str(seed)) for seed in request.seeds})
