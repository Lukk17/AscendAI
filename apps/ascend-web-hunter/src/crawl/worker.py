"""Crawl worker tasks.

Each instance runs ``CRAWL_WORKER_CONCURRENCY`` tasks of :meth:`Worker.run_forever`.
One iteration claims at most one URL through the frontier scripts, so one
instance never reads more pages at once than it has tasks, while the
per-domain cap, the crawl delay and the page budget hold for all instances
together. Every fetch runs inside the crawl proxy context.
Discovered links, redirect hops, robots.txt and sitemap fetches all pass
the same guard and connect-time pinning as a single read: a
link the guard refuses is dropped and counted as ``skipped_unsafe``.
"""

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final, NamedTuple, Protocol, cast
from urllib.parse import urlparse

import redis.asyncio as redis
from ascend_python_common.uri_guard import UnsafeUriError, check_fetch_uri
from protego import Protego

from src.config.config import settings
from src.crawl import fetcher
from src.crawl.fetcher import CRAWL_USER_AGENT, ConditionalProbe
from src.crawl.frontier import Frontier, claim_entry
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
from src.crawl.models import UNREADABLE_RECORD_ERRORS, CrawlRequest, JobRecord, match_glob
from src.crawl.result_store import (
    RecrawlStore,
    ResultStore,
    index_object_key,
    normalize_url,
    page_object_key,
    recrawl_scope,
)
from src.crawl.robots import ROBOTS_SKIP_REASON, RobotsStore, origin_of
from src.observability.safe_address import address_without_query, exception_text_without_queries
from src.proxy.proxy_provider import crawl_proxy
from src.reader.browser_guard import web_hunter_fetch_policy
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.link_annotator import annotate_links
from src.reader.strategies.base_strategy import validators_of
from src.reader.web_reader import PageResult, WebReader

logger = logging.getLogger(__name__)

_MS_PER_SECOND: Final[int] = 1000
_NOT_MODIFIED: Final[int] = 304


class ProbeFn(Protocol):
    def __call__(
        self, url: str, *, etag: str | None, last_modified: str | None, profile: str | None
    ) -> Awaitable[ConditionalProbe]: ...


TERMINAL_STATES = ("succeeded", "failed", "cancelled")
LIVE_STATES = ("waiting", "running")


@dataclass(frozen=True, slots=True)
class PageWrite:
    """The page object and recrawl entry one read wrote, so a cancelled job can take both back."""

    page_key: str
    scope: str
    url: str
    recrawl_value: str | None
    prior: dict[str, Any] | None


class PageOutcome(NamedTuple):
    outcome: str
    page_line: str
    links: list[dict[str, object]]
    skipped: int
    written: PageWrite | None = None


DROPPED_PAGE = PageOutcome("failed", "", [], 0)


class ExtractedPage(NamedTuple):
    content: str | None
    links: list[str]
    etag: str | None = None
    last_modified: str | None = None
    reason: str | None = None


UNREAD_PAGE = ExtractedPage(None, [])


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _robots_skipped(url: str) -> PageOutcome:
    line = json.dumps({"url": url, "status": "skipped", "reason": ROBOTS_SKIP_REASON}, sort_keys=True)
    return PageOutcome("robots_skipped", line, [], 0)


def _unread(url: str, reason: str) -> PageOutcome:
    line = json.dumps({"url": url, "status": "failed", "reason": reason}, sort_keys=True)
    return PageOutcome("failed", line, [], 0)


def _formatted_content(result: dict[str, Any]) -> str:
    if "content" not in result:
        return json.dumps(result, sort_keys=True, default=str)
    shaped = result["content"]
    if isinstance(shaped, str):
        return shaped
    return json.dumps(shaped, sort_keys=True, default=str)


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
        self._clock_ms = clock_ms if clock_ms is not None else (lambda: int(time.time() * _MS_PER_SECOND))
        self._seeded: set[tuple[str, str]] = set()

    async def apply_result_expiry(self) -> None:
        await self._results.apply_expiry_rule()

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
        self._drop_caches_of_ended_jobs(members)
        for member in members:
            try:
                if await self._drain_member(member):
                    return True
            except Exception as exc:
                logger.warning(
                    "crawl: sweep of job %s failed: %s", member, exception_text_without_queries(exc)
                )
        return False

    def _drop_caches_of_ended_jobs(self, members: list[str]) -> None:
        live = {member.partition(":")[2] for member in members}
        for job_id in (self._robots.job_ids() | {key[0] for key in self._seeded}) - live:
            self._drop_job_caches(job_id)

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
        if record is None or record.state in TERMINAL_STATES:
            await self._frontier.remove_runnable_member(member)
            self._drop_job_caches(job_id)
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
        except UNREADABLE_RECORD_ERRORS:
            await self._frontier.remove_runnable_member(f"{tenant_id}:{job_id}")
            return None

    async def _try_domain(
        self, tenant_id: str, job_id: str, member: str, record: JobRecord, domain: str
    ) -> bool:
        head_url = await self._peek_queue_head(tenant_id, job_id, domain)
        delay_ms = await self._domain_delay_ms(record, head_url)
        now_ms = self._clock_ms()
        try:
            answer = await self._frontier.claim(
                job_key=job_key(tenant_id, job_id),
                queue_key=queue_key(tenant_id, job_id, domain),
                inflight_key=inflight_key(tenant_id, job_id, domain),
                claims_key=claims_key(tenant_id, job_id),
                next_fetch_key=next_fetch_key(tenant_id, job_id, domain),
                runnable_key=RUNNABLE_KEY,
                now_ms=now_ms,
                lease_ms=settings.CRAWL_CLAIM_LEASE_SECONDS * _MS_PER_SECOND,
                page_budget=record.request.page_budget,
                domain_cap=settings.CRAWL_DOMAIN_CONCURRENCY,
                delay_ms=delay_ms,
                retention=settings.CRAWL_JOB_RETENTION_SECONDS,
                member=member,
                max_expiries=settings.CRAWL_CLAIM_MAX_EXPIRIES,
                updated_at=_now_iso(),
                tenant_id=tenant_id,
                job_id=job_id,
                domain=domain,
                robots_skip_factor=settings.CRAWL_ROBOTS_SKIP_FACTOR,
            )
        except Exception as exc:
            logger.warning("crawl: claim failed for %s: %s", member, exc)
            return False
        status = answer[0]
        if status == "gone":
            await self._frontier.remove_runnable_member(member)
            self._drop_job_caches(job_id)
            return False
        if status == "idle":
            if len(answer) > 1:
                await self._frontier.remove_runnable_member(member)
                self._drop_job_caches(job_id)
            return False
        if status in ("budget", "ended"):
            if len(answer) > 1:
                await self._finalize(tenant_id, job_id, member)
            return False
        if status != "claimed":
            return False
        url = answer[1]
        if head_url is None or origin_of(url) != origin_of(head_url):
            await self._extend_delay(tenant_id, job_id, record, domain, url, now_ms, delay_ms)
        await self._process_claim(tenant_id, job_id, member, record, domain, url, int(answer[2]))
        return True

    async def _peek_queue_head(self, tenant_id: str, job_id: str, domain: str) -> str | None:
        head = await self._client.lindex(queue_key(tenant_id, job_id, domain), 0)
        if head is None:
            return None
        return str(head).partition("\t")[2]

    async def _extend_delay(
        self,
        tenant_id: str,
        job_id: str,
        record: JobRecord,
        domain: str,
        url: str,
        claimed_at_ms: int,
        granted_delay_ms: int,
    ) -> None:
        claimed_delay_ms = await self._domain_delay_ms(record, url)
        if claimed_delay_ms <= granted_delay_ms:
            return
        await self._frontier.extend_next_fetch(
            next_fetch_key=next_fetch_key(tenant_id, job_id, domain),
            next_fetch_ms=claimed_at_ms + claimed_delay_ms,
            retention=settings.CRAWL_JOB_RETENTION_SECONDS,
        )

    async def _domain_delay_ms(self, record: JobRecord, url: str | None) -> int:
        floor_ms = int(settings.CRAWL_DEFAULT_DELAY_SECONDS * _MS_PER_SECOND)
        if url is None or not record.request.respect_robots:
            return floor_ms
        try:
            rules = await self._robots_rules(record, url)
        except Exception as exc:
            logger.warning(
                "crawl: robots read failed for %s: %s",
                address_without_query(url),
                exception_text_without_queries(exc),
            )
            return floor_ms
        if rules is None:
            return floor_ms
        extra = rules.crawl_delay(CRAWL_USER_AGENT)
        if extra is None:
            return floor_ms
        return max(floor_ms, int(min(extra, settings.CRAWL_MAX_DELAY_SECONDS) * _MS_PER_SECOND))

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
        entry = claim_entry(depth, domain, url)
        with crawl_proxy():
            if await self._is_disallowed(record, url):
                page = _robots_skipped(url)
            else:
                try:
                    sitemap_skipped = await self._seed_sitemaps(tenant_id, job_id, record, url, depth)
                    page = await self._read_page(tenant_id, job_id, record, url, depth)
                    page = page._replace(skipped=page.skipped + sitemap_skipped)
                except Exception as exc:
                    logger.warning(
                        "crawl: page processing of %s failed: %s",
                        address_without_query(url),
                        exception_text_without_queries(exc),
                    )
                    page = DROPPED_PAGE
        await self._finish(
            tenant_id,
            job_id,
            member,
            record,
            domain,
            entry,
            outcome=page.outcome,
            page_line=page.page_line,
            links=page.links,
            skipped=page.skipped,
            written=page.written,
        )

    async def _is_disallowed(self, record: JobRecord, url: str) -> bool:
        if not record.request.respect_robots:
            return False
        try:
            rules = await self._robots_rules(record, url)
        except Exception as exc:
            logger.warning(
                "crawl: robots read failed for %s, the page is skipped: %s",
                address_without_query(url),
                exception_text_without_queries(exc),
            )
            return True
        return rules is not None and not rules.can_fetch(url, CRAWL_USER_AGENT)

    async def _robots_rules(self, record: JobRecord, url: str) -> Protego | None:
        with crawl_proxy():
            return await self._robots.rules(record.job_id, url, profile=record.request.profile)

    async def _seed_sitemaps(
        self, tenant_id: str, job_id: str, record: JobRecord, url: str, depth: int
    ) -> int:
        key = (job_id, origin_of(url))
        if key in self._seeded:
            return 0
        self._seeded.add(key)
        same_domain_only = record.request.same_domain_only
        try:
            async with asyncio.timeout(settings.CRAWL_SITEMAP_TIMEOUT_SECONDS):
                urls = await self._robots.sitemap_seed_urls(
                    job_id,
                    url,
                    profile=record.request.profile,
                    max_urls=record.request.page_budget,
                    accept=lambda raw: self._follows(record, raw, depth + 1),
                    seed_domains=record.request.seed_domains if same_domain_only else None,
                )
                return await self._queue_new(tenant_id, job_id, record, urls, depth + 1)
        except Exception as exc:
            logger.warning(
                "crawl: sitemap seed failed for %s: %s",
                address_without_query(url),
                exception_text_without_queries(exc),
            )
            return 0

    def _follows(self, record: JobRecord, raw: str, depth: int) -> bool:
        try:
            url = normalize_url(raw)
        except ValueError:
            return False
        return self._filter_link(record, url, depth) is not None

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
                await check_fetch_uri(url, web_hunter_fetch_policy())
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
        if record.request.same_domain_only and (
            cookie_manager.registrable_domain(url) not in record.request.seed_domains
        ):
            return None
        path = urlparse(url).path
        include = record.request.include_patterns
        if include and not match_glob(include, path):
            return None
        if match_glob(record.request.exclude_patterns, path):
            return None
        return url

    async def _accepts_writes(self, tenant_id: str, job_id: str) -> bool:
        record = await self._load_record(tenant_id, job_id)
        return record is not None and record.state in LIVE_STATES

    async def _read_page(
        self, tenant_id: str, job_id: str, record: JobRecord, url: str, depth: int
    ) -> PageOutcome:
        request = record.request
        scope = recrawl_scope(request)
        prior = await self._recrawl.read(tenant_id, scope, url)
        prior_key = prior.get("page_key") if prior is not None else None
        if not isinstance(prior_key, str):
            prior = None
            prior_key = None
        new_key = page_object_key(tenant_id, job_id, url, request.output_format)
        prior_exists = await self._results.page_exists(prior_key) if prior_key is not None else False
        copyable = prior_exists
        if prior_exists and prior_key is not None and prior is not None:
            etag, last_modified = _stored_validators(prior)
            probe = await self._probe(url, etag=etag, last_modified=last_modified, profile=request.profile)
            stored_links = _stored_links(prior)
            if probe.status == _NOT_MODIFIED:
                if stored_links is not None:
                    links, skipped = await self._links_for(record, stored_links, depth)
                    current_etag, current_last_modified = _validators_after_304(probe, etag, last_modified)
                    copied = await self._copy_forward(
                        tenant_id,
                        job_id,
                        scope,
                        url,
                        prior,
                        prior_key,
                        new_key,
                        stored_links,
                        links,
                        skipped,
                        etag=current_etag,
                        last_modified=current_last_modified,
                    )
                    if copied is not None:
                        return copied
                copyable = False
        content, raw_links, read_etag, read_last_modified, reason = await self._extract(record, url)
        if content is None:
            return DROPPED_PAGE if reason is None else _unread(url, reason)
        links, skipped = await self._links_for(record, raw_links, depth)
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if copyable and prior is not None and prior.get("hash") == digest and prior_key is not None:
            copied = await self._copy_forward(
                tenant_id,
                job_id,
                scope,
                url,
                prior,
                prior_key,
                new_key,
                raw_links,
                links,
                skipped,
                etag=read_etag,
                last_modified=read_last_modified,
            )
            if copied is not None:
                return copied
        if not await self._accepts_writes(tenant_id, job_id):
            return DROPPED_PAGE
        await self._results.write_page(new_key, content)
        recrawl_value = await self._write_recrawl(
            tenant_id, scope, url, digest, read_etag, read_last_modified, new_key, raw_links
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
        return PageOutcome("ok", line, links, skipped, PageWrite(new_key, scope, url, recrawl_value, prior))

    async def _copy_forward(
        self,
        tenant_id: str,
        job_id: str,
        scope: str,
        url: str,
        prior: dict[str, object],
        prior_key: str,
        new_key: str,
        raw_links: list[str],
        links: list[dict[str, object]],
        skipped: int,
        *,
        etag: str | None,
        last_modified: str | None,
    ) -> PageOutcome | None:
        if not await self._accepts_writes(tenant_id, job_id):
            return DROPPED_PAGE
        try:
            await self._results.copy_page_forward(prior_key, new_key)
        except Exception as exc:
            logger.warning("crawl: copy forward of %s failed: %s", prior_key, exc)
            if not await self._results.page_exists(prior_key):
                return None
            raise
        digest = prior.get("hash")
        recrawl_value = await self._write_recrawl(
            tenant_id,
            scope,
            url,
            digest if isinstance(digest, str) else "",
            etag,
            last_modified,
            new_key,
            raw_links,
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
        written = PageWrite(new_key, scope, url, recrawl_value, prior)
        return PageOutcome("unchanged", line, links, skipped, written)

    async def _extract(self, record: JobRecord, url: str) -> ExtractedPage:
        request = record.request
        try:
            read = await self._read(request, url)
        except Exception as exc:
            logger.warning(
                "crawl: read of %s failed: %s",
                address_without_query(url),
                exception_text_without_queries(exc),
            )
            return UNREAD_PAGE
        if read.get("status") != "success":
            reason = read.get("reason")
            return UNREAD_PAGE._replace(reason=reason) if isinstance(reason, str) else UNREAD_PAGE
        if request.output_format == "text":
            content = read.get("content")
            raw_links = read.get("links")
        else:
            content = _formatted_content(read)
            raw_links = annotate_links(read.page, url)[1]
        if not isinstance(content, str):
            return UNREAD_PAGE
        urls: list[str] = []
        if isinstance(raw_links, dict):
            urls.extend(value for value in raw_links.values() if isinstance(value, str))
        return ExtractedPage(content, urls, *validators_of(read.page))

    async def _read(self, request: CrawlRequest, url: str) -> PageResult:
        if request.output_format == "text":
            return await self._reader.read_linked_page(
                url, profile=request.profile, allow_human_tier=False, use_read_cache=False
            )
        return await self._reader.read_page(
            url,
            output_format=request.output_format,
            extraction_schema=request.extraction_schema,
            profile=request.profile,
            allow_human_tier=False,
            use_read_cache=False,
        )

    async def _links_for(
        self, record: JobRecord, urls: list[str], depth: int
    ) -> tuple[list[dict[str, object]], int]:
        kept: list[dict[str, object]] = []
        skipped = 0
        for raw in urls:
            try:
                url = normalize_url(raw)
            except ValueError:
                continue
            try:
                await check_fetch_uri(url, web_hunter_fetch_policy())
            except UnsafeUriError:
                skipped += 1
                continue
            item = self._filter_link(record, url, depth + 1)
            if item is None:
                continue
            kept.append({"u": item, "d": depth + 1, "domain": cookie_manager.registrable_domain(item)})
        return kept, skipped

    async def _write_recrawl(
        self,
        tenant_id: str,
        scope: str,
        url: str,
        digest: str,
        etag: str | None,
        last_modified: str | None,
        page_key: str,
        links: list[str],
    ) -> str | None:
        try:
            return await self._recrawl.write(
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
            logger.warning(
                "crawl: recrawl write failed for %s: %s",
                address_without_query(url),
                exception_text_without_queries(exc),
            )
            return None

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
        written: PageWrite | None = None,
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
                robots_skip_factor=settings.CRAWL_ROBOTS_SKIP_FACTOR,
            )
        except Exception as exc:
            logger.warning("crawl: finish failed for %s: %s", member, exc)
            return
        status = answer[0]
        if status in ("succeeded", "failed"):
            await self._finalize(tenant_id, job_id, member)
        elif status in ("cancelled", "gone", "stale"):
            if status == "cancelled" and written is not None:
                await self._take_back(tenant_id, written)
            self._drop_job_caches(job_id)

    async def _take_back(self, tenant_id: str, written: PageWrite) -> None:
        try:
            await self._results.delete_page(written.page_key)
            if written.recrawl_value is not None:
                await self._recrawl.revert(
                    tenant_id, written.scope, written.url, written.recrawl_value, written.prior
                )
        except Exception as exc:
            logger.warning("crawl: cleanup of cancelled page %s failed: %s", written.page_key, exc)

    async def _finalize(self, tenant_id: str, job_id: str, member: str) -> None:
        try:
            raw = await self._client.get(job_key(tenant_id, job_id))
            if raw is None:
                return
            record = JobRecord.model_validate_json(raw)
            if record.state == "succeeded":
                await self._write_index(tenant_id, job_id)
            await self._frontier.delete_frontier(tenant_id, job_id, record.domains)
        except Exception as exc:
            logger.warning("crawl: finalize failed for %s: %s", member, exc)
        finally:
            self._drop_job_caches(job_id)

    async def _write_index(self, tenant_id: str, job_id: str) -> None:
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

    def _drop_job_caches(self, job_id: str) -> None:
        self._robots.drop_job(job_id)
        for key in [key for key in self._seeded if key[0] == job_id]:
            self._seeded.discard(key)


def _stored_validators(prior: dict[str, object]) -> tuple[str | None, str | None]:
    etag = prior.get("etag")
    last_modified = prior.get("last_modified")
    return (
        etag if isinstance(etag, str) else None,
        last_modified if isinstance(last_modified, str) else None,
    )


def _validators_after_304(
    probe: ConditionalProbe, etag: str | None, last_modified: str | None
) -> tuple[str | None, str | None]:
    return (
        probe.etag if probe.etag is not None else etag,
        probe.last_modified if probe.last_modified is not None else last_modified,
    )


def _stored_links(prior: dict[str, object]) -> list[str] | None:
    links = prior.get("links")
    if not isinstance(links, list) or not all(isinstance(link, str) for link in links):
        return None
    return cast("list[str]", links)


def seed_domains(request: CrawlRequest) -> list[str]:
    return sorted(request.seed_domains)
