"""robots.txt and sitemap handling of the crawl jobs (design D5).

Every robots.txt and sitemap fetch goes through the shared guarded
``curl_cffi`` fetch, so the same SSRF guard and connect-time pinning as a
single read applies (design D4). Each instance keeps the parsed file in
memory until the job ends, which is correct because every instance reads
the same file (design D15).
"""

import logging
import xml.etree.ElementTree as ET
from collections.abc import Awaitable, Callable
from urllib.parse import urlparse, urlunparse

from protego import Protego

from src.config.config import settings
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi

logger = logging.getLogger(__name__)

FetchFn = Callable[[str], Awaitable[str]]

_SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"


async def _default_fetch(url: str) -> str:
    return await fetch_with_curl_cffi(url, lambda: "ascend-web-hunter-crawl", "crawl-robots")


def robots_url(page_url: str) -> str:
    parsed = urlparse(page_url)
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


async def load_rules(page_url: str, fetch: FetchFn = _default_fetch) -> Protego | None:
    """Fetch and parse the robots.txt of the host of *page_url*.

    A missing or unreadable file answers None, which the worker reads as
    allow-all with no delay and no sitemaps.
    """
    try:
        body = await fetch(robots_url(page_url))
    except Exception as exc:
        logger.warning("crawl: robots.txt fetch of %s failed: %s", page_url, exc)
        return None
    if not body:
        return None
    return Protego.parse(body)


def ensure_opt_out(seeds: list[str], respect_robots: bool) -> None:
    """Refuse ``respect_robots`` false for a domain the operator does not own.

    Raises ValueError, which the API answers with 400 ``validation``,
    before any job is created.
    """
    if respect_robots:
        return
    allowed = set(settings.CRAWL_ROBOTS_OPT_OUT_DOMAINS)
    for seed in seeds:
        domain = cookie_manager.registrable_domain(seed)
        if domain not in allowed:
            raise ValueError(
                f"respect_robots=false is refused for {domain}: add it to CRAWL_ROBOTS_OPT_OUT_DOMAINS"
            )


def sitemap_locations(body: str) -> tuple[list[str], list[str]]:
    """Split one sitemap document into page URLs and nested sitemap URLs."""
    try:
        root = ET.fromstring(body)  # noqa: S314
    except ET.ParseError:
        return [], []
    pages: list[str] = []
    nested: list[str] = []
    tag = root.tag
    if tag in (f"{_SITEMAP_NS}sitemapindex", "sitemapindex"):
        for child in root:
            loc = _loc_of(child)
            if loc is not None:
                nested.append(loc)
    elif tag in (f"{_SITEMAP_NS}urlset", "urlset"):
        for child in root:
            loc = _loc_of(child)
            if loc is not None:
                pages.append(loc)
    return pages, nested


def _loc_of(entry: ET.Element) -> str | None:
    for child in entry:
        tag = child.tag
        if tag in (f"{_SITEMAP_NS}loc", "loc"):
            text = (child.text or "").strip()
            if text:
                return text
    return None


async def collect_sitemap_urls(sitemap_urls: list[str], fetch: FetchFn = _default_fetch) -> list[str]:
    """Fetch sitemap documents and return every page URL they name.

    Sitemap indexes are followed one level at a time with a visited set,
    so an index that names itself cannot loop forever.
    """
    found: list[str] = []
    visited: set[str] = set()
    pending = list(sitemap_urls)
    while pending:
        target = pending.pop()
        if target in visited:
            continue
        visited.add(target)
        try:
            body = await fetch(target)
        except Exception as exc:
            logger.warning("crawl: sitemap fetch of %s failed: %s", target, exc)
            continue
        if not body:
            continue
        pages, nested = sitemap_locations(body)
        found.extend(pages)
        pending.extend(nested)
    return found


class RobotsStore:
    """Per-instance robots.txt memory of one worker (design D15)."""

    def __init__(self, fetch: FetchFn = _default_fetch) -> None:
        self._fetch = fetch
        self._cache: dict[tuple[str, str], Protego | None] = {}

    async def rules(self, job_id: str, page_url: str) -> Protego | None:
        domain = cookie_manager.registrable_domain(page_url)
        key = (job_id, domain)
        if key not in self._cache:
            self._cache[key] = await load_rules(page_url, self._fetch)
        return self._cache[key]

    async def sitemap_seed_urls(self, job_id: str, page_url: str) -> list[str]:
        rules = await self.rules(job_id, page_url)
        if rules is None:
            return []
        return await collect_sitemap_urls(list(rules.sitemaps), self._fetch)

    def drop_job(self, job_id: str) -> None:
        for key in [key for key in self._cache if key[0] == job_id]:
            del self._cache[key]
