"""robots.txt and sitemap handling of the crawl jobs.

Every robots.txt and sitemap fetch goes through the shared guarded
``curl_cffi`` hop, so the same SSRF guard and connect-time pinning as a
single read applies. The answer to a robots.txt fetch is read as RFC 9309
says: a 4xx answer other than 429 allows every page of the origin, a 5xx
answer, a 429 or no answer at all disallows every page of the origin.
Each instance keeps the verdict in memory until the job ends or the limit
of remembered origins evicts it, which is correct because every instance
reads the same file and an evicted file is only fetched again.
"""

import asyncio
import logging
import re
import socket
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass, field
from typing import Final
from urllib.parse import unquote, urlparse, urlunparse
from xml.parsers import expat

from ascend_python_common.startup_banner import strip_user_info
from ascend_python_common.uri_guard import UnsafeUriError
from protego import Protego

from src.config.config import settings
from src.crawl.fetcher import CRAWL_USER_AGENT, RobotsFetch, fetch_robots_txt
from src.fetch.capped_inflate import gunzip_capped
from src.observability.safe_address import address_without_query, exception_text_without_queries
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.strategies.curl_cffi_fetcher import fetch_with_curl_cffi
from src.session.profile import MAX_URL_LENGTH

logger = logging.getLogger(__name__)

FetchFn = Callable[[str], Awaitable[str]]
RobotsFetchFn = Callable[[str, str | None], Awaitable[RobotsFetch]]
ProfileFetchFn = Callable[[str, str | None], Awaitable[str]]
AcceptFn = Callable[[str], bool]

ROBOTS_SKIP_REASON: Final[str] = "robots_disallowed"

_NAMESPACE_SEPARATOR: Final[str] = " "
_SITEMAP_NS: Final[str] = f"http://www.sitemaps.org/schemas/sitemap/0.9{_NAMESPACE_SEPARATOR}"
_PAGE_ROOTS: Final[frozenset[str]] = frozenset({f"{_SITEMAP_NS}urlset", "urlset"})
_INDEX_ROOTS: Final[frozenset[str]] = frozenset({f"{_SITEMAP_NS}sitemapindex", "sitemapindex"})
_LOC_NAMES: Final[frozenset[str]] = frozenset({f"{_SITEMAP_NS}loc", "loc"})
_ROOT_DEPTH: Final[int] = 1
_ENTRY_DEPTH: Final[int] = 2
_LOC_DEPTH: Final[int] = 3
_MAX_LOC_TEXT_CHARS: Final[int] = 2 * MAX_URL_LENGTH
_SITEMAP_PARSE_STEP_CHARS: Final[int] = 64 * 1024
_NO_SESSION_PROFILE: Final[str] = "!no-stored-session"
_BYTE_ORDER_MARK: Final[str] = "\ufeff"
_USER_AGENT_LINE: Final[re.Pattern[str]] = re.compile(r"user(?:-|\s+)?agent(?:\s*:|\s|$)", re.IGNORECASE)
_ALLOW_DIRECTIVE: Final[str] = "allow"
_INDEX_PAGE_SUFFIX: Final[str] = "/index.html"
_START_TAG_NOT_HEADS: Final[frozenset[bytes]] = frozenset({b"<!", b"<?", b"</"})
_MARKUP_HEAD_BYTES: Final[int] = 2
_DEFAULT_PORTS = {"http": 80, "https": 443}
_GZIP_MAGIC: Final[bytes] = b"\x1f\x8b"
_TOO_MANY_REQUESTS: Final[int] = 429
_SUCCESS: Final[range] = range(200, 300)
_SERVER_ERROR_FLOOR: Final[int] = 500
_DISALLOW_ALL: Final[Protego] = Protego.parse("User-agent: *\nDisallow: /\n")


async def _default_sitemap_fetch(url: str, profile: str | None) -> str:
    try:
        return await fetch_with_curl_cffi(
            url,
            lambda: CRAWL_USER_AGENT,
            "crawl-sitemap",
            profile,
            max_bytes=settings.CRAWL_SITEMAP_MAX_BYTES,
            unpack=_unpack_sitemap,
        )
    except UnsafeUriError:
        return ""


def _unpack_sitemap(raw: bytes, _content_type: str | None) -> bytes | None:
    """Inflate a sitemap whose body starts with the gzip signature, within CRAWL_SITEMAP_MAX_BYTES."""
    if not raw.startswith(_GZIP_MAGIC):
        return raw
    return gunzip_capped(raw, settings.CRAWL_SITEMAP_MAX_BYTES)


def origin_of(url: str) -> str:
    """Answer the origin of *url*: scheme, host and port, the scope robots.txt rules apply to."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    port = parsed.port or _DEFAULT_PORTS.get(scheme)
    return f"{scheme}://{parsed.hostname or ''}:{port}"


def robots_url(page_url: str) -> str:
    parsed = urlparse(page_url)
    return urlunparse((parsed.scheme, parsed.netloc, "/robots.txt", "", "", ""))


def _registrable_domain(url: str) -> str:
    try:
        return cookie_manager.registrable_domain(url)
    except ValueError:
        return ""


def _is_unreachable(status: int | None) -> bool:
    return status is None or status == _TOO_MANY_REQUESTS or status >= _SERVER_ERROR_FLOOR


async def load_rules(
    page_url: str, fetch: RobotsFetchFn = fetch_robots_txt, *, profile: str | None
) -> Protego | None:
    """Fetch with the session of *profile* and parse the robots.txt of the origin of *page_url* per RFC 9309.

    The rules alone, see ``_load_counted_rules``.
    """
    rules, _ = await _load_counted_rules(page_url, fetch, profile=profile)

    return rules


async def _load_counted_rules(
    page_url: str, fetch: RobotsFetchFn, *, profile: str | None
) -> tuple[Protego | None, int]:
    """Fetch and parse one robots.txt and answer its rules with the rule objects counted for it.

    None means allow-all with no delay and no sitemaps: an empty file, a 4xx
    answer other than 429, a redirect chain the guard refuses, or one left
    unfinished at the hop limit. A 5xx answer, a 429, a host that does not
    resolve, a file slower than CRAWL_ROBOTS_TIMEOUT_SECONDS, a file that
    expands past CRAWL_ROBOTS_MAX_RULES or no answer at all answers rules
    that disallow every page of the origin. Any other error *fetch* raises
    reaches the caller.
    """
    target = robots_url(page_url)
    try:
        async with asyncio.timeout(settings.CRAWL_ROBOTS_TIMEOUT_SECONDS):
            answer = await fetch(target, profile)
    except UnsafeUriError as exc:
        if isinstance(exc.__cause__, socket.gaierror):
            logger.warning(
                "crawl: robots.txt %s does not resolve, every page of the origin is disallowed",
                strip_user_info(target),
            )
            return _DISALLOW_ALL, 0
        logger.warning(
            "crawl: the guard refused robots.txt %s, read as an absent file", strip_user_info(target)
        )
        return None, 0
    except TimeoutError:
        logger.warning(
            "crawl: robots.txt %s did not answer in time, every page of the origin is disallowed",
            strip_user_info(target),
        )
        return _DISALLOW_ALL, 0
    if _is_unreachable(answer.status):
        logger.warning(
            "crawl: robots.txt %s is unreachable (status %s), every page of the origin is disallowed",
            strip_user_info(target),
            answer.status,
        )
        return _DISALLOW_ALL, 0
    if answer.status not in _SUCCESS or not answer.body:
        return None, 0
    body = answer.body.removeprefix(_BYTE_ORDER_MARK)
    rule_objects = _rule_objects_of(body)
    if rule_objects > settings.CRAWL_ROBOTS_MAX_RULES:
        logger.warning(
            "crawl: robots.txt %s expands to %d rules, above the limit of %d, "
            "every page of the origin is disallowed",
            strip_user_info(target),
            rule_objects,
            settings.CRAWL_ROBOTS_MAX_RULES,
        )
        return _DISALLOW_ALL, 0
    return await asyncio.to_thread(Protego.parse, body), rule_objects


def _rule_objects_of(body: str) -> int:
    """Answer the most rule objects Protego can build for *body*: its rule sets times its weighted rules."""
    rule_sets = 0
    rules = 0
    for raw_line in body.splitlines():
        line = raw_line.partition("#")[0].strip()
        if not line:
            continue
        agent = _USER_AGENT_LINE.match(line)
        if agent is None:
            rules += _rules_of_line(line)
        else:
            rule_sets += _rule_sets_of_agent(line[agent.end() :].strip())
    return rule_sets * rules


def _rule_sets_of_agent(value: str) -> int:
    """Answer the rule sets of one user-agent value: a starred name makes one with and one without stars."""
    if not value:
        return 0
    return 2 if "*" in value and value.strip("*") else 1


def _rules_of_line(line: str) -> int:
    """Answer the most rules one non-agent line makes per rule set.

    A value with a dollar sign makes the rule twice, and an allowed page named
    index.html makes each of those once more for its folder, after percent-decoding.
    """
    rules = 2 if "$" in line else 1
    if line.lower().startswith(_ALLOW_DIRECTIVE) and _INDEX_PAGE_SUFFIX in unquote(line):
        return 2 * rules
    return rules


@dataclass(slots=True)
class SitemapAllowance:
    """What one job may still spend on sitemaps in this instance, shared by all its origins."""

    documents: int
    urls: int


class _DoctypeRefusedError(Exception):
    """A sitemap that declares a DOCTYPE, which no valid sitemap does."""


class _StartTagTooLongError(Exception):
    """A sitemap with a start tag longer than one parse step, which would buffer in the parser."""


class _LocationStream:
    """Parses one sitemap piece by piece and keeps only the text of its ``loc`` elements."""

    def __init__(self) -> None:
        parser = expat.ParserCreate(namespace_separator=_NAMESPACE_SEPARATOR)
        parser.buffer_text = True
        parser.StartDoctypeDeclHandler = self._refuse_doctype
        parser.StartElementHandler = self._start_element
        parser.EndElementHandler = self._end_element
        parser.CharacterDataHandler = self._characters
        self._parser = parser
        self._fed_bytes = 0
        self._pending_markup_head = b""
        self._depth = 0
        self._reads_locations = False
        self.is_index = False
        self._entry_has_location = False
        self._in_location = False
        self._text: list[str] = []
        self._text_chars = 0
        self._locations: list[str] = []

    def feed(self, piece: str, *, final: bool = False) -> None:
        """Parse the next piece of the document.

        Raises:
            expat.ExpatError: when the document is not well formed.
            _DoctypeRefusedError: when the document declares a DOCTYPE.
            _StartTagTooLongError: when a start tag fills this whole piece.
        """
        self._parser.Parse(piece, final)
        encoded = piece.encode()
        self._fed_bytes += len(encoded)
        index = self._parser.CurrentByteIndex
        pending = self._fed_bytes - index if index >= 0 else 0
        window = self._pending_markup_head + encoded
        if pending <= len(window):
            self._pending_markup_head = window[len(window) - pending :][:_MARKUP_HEAD_BYTES]
        if pending > len(encoded) and self._pending_token_is_start_tag():
            raise _StartTagTooLongError

    def _pending_token_is_start_tag(self) -> bool:
        head = self._pending_markup_head

        return len(head) == _MARKUP_HEAD_BYTES and head.startswith(b"<") and head not in _START_TAG_NOT_HEADS

    def take_locations(self) -> list[str]:
        finished = self._locations
        self._locations = []
        return finished

    def _refuse_doctype(self, *_declaration: object) -> None:
        raise _DoctypeRefusedError

    def _start_element(self, name: str, _attributes: dict[str, str]) -> None:
        self._depth += 1
        if self._depth == _ROOT_DEPTH:
            self.is_index = name in _INDEX_ROOTS
            self._reads_locations = self.is_index or name in _PAGE_ROOTS
        elif self._depth == _ENTRY_DEPTH:
            self._entry_has_location = False
        elif self._starts_location(name):
            self._in_location = True
            self._text = []
            self._text_chars = 0

    def _starts_location(self, name: str) -> bool:
        return (
            self._depth == _LOC_DEPTH
            and name in _LOC_NAMES
            and self._reads_locations
            and not self._entry_has_location
        )

    def _characters(self, data: str) -> None:
        if not self._in_location or self._depth != _LOC_DEPTH:
            return
        self._text_chars += len(data)
        if self._text_chars <= _MAX_LOC_TEXT_CHARS:
            self._text.append(data)

    def _end_element(self, _name: str) -> None:
        if self._in_location and self._depth == _LOC_DEPTH:
            self._in_location = False
            self._finish_location()
        self._depth -= 1

    def _finish_location(self) -> None:
        location = "".join(self._text).strip()
        if location and self._text_chars <= _MAX_LOC_TEXT_CHARS and len(location) <= MAX_URL_LENGTH:
            self._entry_has_location = True
            self._locations.append(location)


def _keep_pages(locations: list[str], allowance: SitemapAllowance, accept: AcceptFn, kept: list[str]) -> None:
    for location in locations:
        if allowance.urls <= 0:
            return
        if accept(location):
            kept.append(location)
            allowance.urls -= 1


def _keep_nested(locations: list[str], max_nested: int, accept: AcceptFn, kept: list[str]) -> None:
    for location in locations:
        if len(kept) >= max_nested:
            return
        if accept(location) and location not in kept:
            kept.append(location)


async def sitemap_locations(
    body: str,
    *,
    allowance: SitemapAllowance,
    max_nested: int,
    accept: AcceptFn,
    accept_nested: AcceptFn,
) -> tuple[list[str], list[str]]:
    """Stream one sitemap document into page addresses and nested sitemap addresses.

    Parsing stops once *allowance* has no address left or *max_nested* nested
    sitemaps are found, and the event loop gets a turn after every parse step.
    A document that is malformed, declares a DOCTYPE or has a start tag longer
    than one parse step yields nothing and spends nothing.
    """
    stream = _LocationStream()
    kept: list[str] = []

    def keep_finished() -> bool:
        if stream.is_index:
            _keep_nested(stream.take_locations(), max_nested, accept_nested, kept)
            return len(kept) >= max_nested
        _keep_pages(stream.take_locations(), allowance, accept, kept)
        return allowance.urls <= 0

    try:
        for start in range(0, len(body), _SITEMAP_PARSE_STEP_CHARS):
            stream.feed(body[start : start + _SITEMAP_PARSE_STEP_CHARS])
            if keep_finished():
                break
            await asyncio.sleep(0)
        else:
            stream.feed("", final=True)
            keep_finished()
    except (expat.ExpatError, _DoctypeRefusedError, _StartTagTooLongError):
        if not stream.is_index:
            allowance.urls += len(kept)
        return [], []
    return ([], kept) if stream.is_index else (kept, [])


def _accept_all(_url: str) -> bool:
    return True


async def collect_sitemap_urls(
    sitemap_urls: Iterable[str],
    fetch: FetchFn,
    *,
    allowance: SitemapAllowance,
    accept: AcceptFn = _accept_all,
    accept_sitemap: AcceptFn = _accept_all,
) -> list[str]:
    """Fetch sitemap documents and return the page URLs that *accept* keeps, within *allowance*.

    Sitemap indexes are followed one level at a time and each document is
    fetched once, so an index that names itself cannot loop forever. Every
    fetch spends one document of *allowance*, indexes and failed fetches
    included, and the waiting sitemaps never outnumber the documents left.
    """
    found: list[str] = []
    visited: set[str] = set()
    pending = [url for url in dict.fromkeys(sitemap_urls) if accept_sitemap(url)]
    not_fetched = 0

    def is_new_sitemap(url: str) -> bool:
        return url not in visited and url not in pending and accept_sitemap(url)

    while True:
        not_fetched += len(pending[allowance.documents :])
        del pending[allowance.documents :]
        if not pending or allowance.urls <= 0:
            break
        target = pending.pop()
        visited.add(target)
        allowance.documents -= 1
        try:
            body = await fetch(target)
        except Exception as exc:
            logger.warning(
                "crawl: sitemap fetch of %s failed: %s",
                address_without_query(target),
                exception_text_without_queries(exc),
            )
            continue
        if not body:
            continue
        room = max(allowance.documents - len(pending), 0)
        pages, nested = await sitemap_locations(
            body,
            allowance=allowance,
            max_nested=room + 1,
            accept=accept,
            accept_nested=is_new_sitemap,
        )
        found.extend(pages)
        pending.extend(nested[:room])
        not_fetched += len(nested[room:])
    if not_fetched and allowance.urls > 0:
        logger.warning("crawl: sitemap limit of the job reached, %d sitemaps not fetched", not_fetched)
    return found


@dataclass(frozen=True, slots=True)
class _CachedRules:
    rules: Protego | None
    rule_objects: int


@dataclass(slots=True)
class _Gate:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    users: int = 0


class RobotsStore:
    """Per-instance robots.txt memory of one worker, one entry per job, profile and origin.

    Concurrent asks for one key share one fetch. A fetch that raises or is
    cancelled is not kept, so the next waiter fetches again. A completed
    verdict, an unreachable file's disallow-all included, is kept until the job
    is dropped or the origin limit or the rule limit of the cache evicts it,
    and a fetch still running when its job is dropped keeps nothing.
    """

    def __init__(
        self, fetch: RobotsFetchFn = fetch_robots_txt, sitemap_fetch: ProfileFetchFn = _default_sitemap_fetch
    ) -> None:
        self._fetch = fetch
        self._sitemap_fetch = sitemap_fetch
        self._cache: OrderedDict[tuple[str, str | None, str], _CachedRules] = OrderedDict()
        self._cached_rules = 0
        self._allowances: dict[str, SitemapAllowance] = {}
        self._gates: dict[tuple[str, str | None, str], _Gate] = {}
        self._dropped: set[str] = set()

    async def rules(self, job_id: str, page_url: str, *, profile: str | None) -> Protego | None:
        key = (job_id, profile, origin_of(page_url))
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key].rules
        gate = self._gates.setdefault(key, _Gate())
        gate.users += 1
        try:
            async with gate.lock:
                if key in self._cache:
                    return self._cache[key].rules
                rules, rule_objects = await _load_counted_rules(page_url, self._fetch, profile=profile)
                if job_id not in self._dropped:
                    self._remember(key, _CachedRules(rules, rule_objects))
                return rules
        finally:
            gate.users -= 1
            if gate.users == 0:
                del self._gates[key]
                if not self._has_gate(job_id):
                    self._dropped.discard(job_id)

    def _remember(self, key: tuple[str, str | None, str], cached: _CachedRules) -> None:
        self._cache[key] = cached
        self._cached_rules += cached.rule_objects
        while (
            len(self._cache) > settings.CRAWL_ROBOTS_CACHE_MAX_ORIGINS
            or self._cached_rules > settings.CRAWL_ROBOTS_CACHE_MAX_RULES
        ):
            _, evicted = self._cache.popitem(last=False)
            self._cached_rules -= evicted.rule_objects

    async def sitemap_seed_urls(
        self,
        job_id: str,
        page_url: str,
        *,
        profile: str | None,
        max_urls: int,
        accept: AcceptFn = _accept_all,
        seed_domains: frozenset[str] | None = None,
    ) -> list[str]:
        """Answer the page URLs the sitemaps of the origin of *page_url* add to job *job_id*.

        Documents and addresses are counted per job. With *seed_domains* set a
        sitemap on another registrable domain is dropped. A sitemap on another
        registrable domain than robots.txt is fetched with no stored session.
        """
        rules = await self.rules(job_id, page_url, profile=profile)
        if rules is None:
            return []
        robots_domain = _registrable_domain(page_url)

        async def fetch(url: str) -> str:
            same_domain = _registrable_domain(url) == robots_domain
            return await self._sitemap_fetch(url, profile if same_domain else _NO_SESSION_PROFILE)

        def accept_sitemap(url: str) -> bool:
            return seed_domains is None or _registrable_domain(url) in seed_domains

        return await collect_sitemap_urls(
            rules.sitemaps,
            fetch,
            allowance=self._allowances.setdefault(
                job_id, SitemapAllowance(documents=settings.CRAWL_SITEMAP_MAX_DOCUMENTS, urls=max_urls)
            ),
            accept=accept,
            accept_sitemap=accept_sitemap,
        )

    def job_ids(self) -> set[str]:
        return {key[0] for key in self._cache} | set(self._allowances)

    def drop_job(self, job_id: str) -> None:
        for key in [key for key in self._cache if key[0] == job_id]:
            self._cached_rules -= self._cache.pop(key).rule_objects
        self._allowances.pop(job_id, None)
        if self._has_gate(job_id):
            self._dropped.add(job_id)

    def _has_gate(self, job_id: str) -> bool:
        return any(key[0] == job_id for key in self._gates)
