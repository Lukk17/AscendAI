import asyncio
import base64
import json
import logging
import random
import time
from collections.abc import Mapping
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Literal, NamedTuple, cast
from urllib.parse import urldefrag, urljoin, urlparse
from weakref import WeakSet

from ascend_python_common.uri_guard import UnsafeUriError
from bs4 import BeautifulSoup

from src.api.exceptions import (
    ChallengeDetectedException,
    ExtractionFailedError,
    ExtractionNotConfiguredError,
    HumanInterventionRequiredException,
    NoVNCFlowBusyException,
    ScreenshotUnavailableError,
    TierDisabledError,
)
from src.config.config import settings
from src.observability.domain_label import domain_label
from src.observability.metrics import (
    READ_BUDGET_EXHAUSTED_TOTAL,
    READ_CACHE_HITS_TOTAL,
    STRATEGY_ATTEMPTS_TOTAL,
    STRATEGY_DURATION_SECONDS,
)
from src.observability.safe_address import address_without_query, exception_text_without_queries
from src.reader import tier_memory
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.challenge_signals import (
    ChallengeVerdict,
    assess,
    log_verdict,
    record_window_verdict,
)
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.document_router import RouteResult, route_document
from src.reader.extraction import extract_structured, extract_tables, extract_text_with_fallback
from src.reader.link_annotator import annotate_links
from src.reader.recipe_store import build_object, names_whole_document, replay_valid
from src.reader.recipe_store import delete as recipe_delete
from src.reader.recipe_store import lookup as recipe_lookup
from src.reader.recipe_store import store as recipe_store_put
from src.reader.schema_extraction import check_schema_size, clean_markup, schema_hash
from src.reader.schema_extraction import run_model as run_schema_model
from src.reader.strategies.base_strategy import BaseStrategy, FetchedHtml
from src.reader.strategies.beautifulsoup_strategy import BeautifulSoupStrategy
from src.reader.strategies.camoufox_strategy import CamoufoxStrategy
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.novnc_strategy import NoVNCStrategy
from src.reader.strategies.patchright_strategy import PatchrightStrategy
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.reader.strategies.trafilatura_strategy import TrafilaturaStrategy
from src.session.session_manager import session_manager
from src.validator.content_validator import ContentValidator
from src.validator.url_validator import url_validator

logger = logging.getLogger(__name__)

NOVNC_STRATEGY_NAME = "6-novnc"
SESSION_EXPIRED_STATUS = "session_expired"

_challenge_verdict: ContextVar[ChallengeVerdict | None] = ContextVar(
    "web_reader_challenge_verdict", default=None
)

TierName = Literal[
    "1-beautifulsoup",
    "2-trafilatura",
    "4-playwright_stealth",
    "4a-patchright",
    "4b-camoufox",
    "5-crawlee_adaptive",
    "6-novnc",
]
OutputFormat = Literal["text", "structured", "schema", "tables", "screenshot"]

TIER_ORDER: tuple[TierName, ...] = (
    "1-beautifulsoup",
    "2-trafilatura",
    "4-playwright_stealth",
    "4a-patchright",
    "4b-camoufox",
    "5-crawlee_adaptive",
    "6-novnc",
)

_PATCHRIGHT_TIER_NAME: TierName = "4a-patchright"
_CAMOUFOX_TIER_NAME: TierName = "4b-camoufox"

_READ_CACHE_MAX_ENTRIES = 1024
_WRAPPER_MAX_OWN_WORDS = 25
_NON_TEXT_TAGS = ("script", "style", "noscript", "template")
_SECOND_LOOK_TIER = "reader"


class ReadCacheKey(NamedTuple):
    """The fields that together identify one read request for cache-aside."""

    url: str
    heavy_mode: bool
    include_links: bool
    profile: str
    output_format: str
    tier: str
    schema_hash: str
    link_filter: str


def _cache_key(
    url: str,
    heavy_mode: bool,
    include_links: bool,
    profile: str | None,
    output_format: str | None,
    tier: TierName | None = None,
    schema_hash: str = "",
    link_filter: str | None = None,
) -> ReadCacheKey:
    """Return the key that uniquely identifies a read request for cache-aside."""
    return ReadCacheKey(
        url=url,
        heavy_mode=heavy_mode,
        include_links=include_links,
        profile=profile or "",
        output_format=output_format or "text",
        tier=tier or "",
        schema_hash=schema_hash,
        link_filter=link_filter or "",
    )


async def _second_look(html: str, url: str) -> None:
    """Judge a tier's page once more, counting one verdict under the tier ``reader``.

    Raises:
        ChallengeDetectedException: when the page is a wall or carries no content.
    """
    verdict = await asyncio.to_thread(assess, 200, html, record_metrics=False)
    record_window_verdict(verdict, _SECOND_LOOK_TIER)
    log_verdict(verdict, _SECOND_LOOK_TIER, url)
    if not verdict.accepted:
        raise ChallengeDetectedException(verdict)


class PageResult(dict[str, Any]):
    """A read answer that keeps the page HTML of the one fetch that served it as an attribute, never a key."""

    page: str

    def __init__(self, answer: Mapping[str, Any], page: str = "") -> None:
        super().__init__(answer)
        self.page = page

    @classmethod
    def of(cls, answer: dict[str, Any]) -> "PageResult":
        """*answer* itself when it keeps a page, else *answer* with an empty page."""
        if isinstance(answer, PageResult):
            return answer

        return cls(answer)


_instances: WeakSet["WebReader"] = WeakSet()


def purge_domain_everywhere(domain: str) -> int:
    """Drop one domain's cached reads in every live WebReader of this process."""
    return sum(reader.clear_cache_for_domain(domain) for reader in list(_instances))


def clear_all_caches() -> int:
    """Drop every live WebReader's whole cache, returning the dropped count."""
    return sum(reader.clear_cache() for reader in list(_instances))


class WebReader:
    """
    Advanced WebReader Orchestrator.
    Manages multi-tier extraction strategies.
    dictates the execution order of strategies.
    """

    def __init__(self) -> None:
        self.validator = ContentValidator()
        self.user_agents = self._load_user_agents()
        self.url_validator = url_validator

        self._memory_cache: dict[ReadCacheKey, tuple[dict[str, Any], float]] = {}
        _instances.add(self)

    def _build_strategies(self, profile: str | None = None) -> dict[str, BaseStrategy]:
        all_strategies: dict[str, BaseStrategy] = {
            "1-beautifulsoup": BeautifulSoupStrategy(self._get_random_user_agent, profile),
            "2-trafilatura": TrafilaturaStrategy(self._get_random_user_agent, profile),
            "4-playwright_stealth": PlaywrightStrategy(
                self._get_random_user_agent, self.url_validator, profile
            ),
            _PATCHRIGHT_TIER_NAME: PatchrightStrategy(
                self._get_random_user_agent, self.url_validator, profile
            ),
            _CAMOUFOX_TIER_NAME: CamoufoxStrategy(self.url_validator, profile),
            "5-crawlee_adaptive": CrawleeStrategy(self.url_validator, profile),
            NOVNC_STRATEGY_NAME: NoVNCStrategy(profile),
        }

        return {name: all_strategies[name] for name in TIER_ORDER}

    def _load_user_agents(self) -> list[str]:
        ua_path = Path(settings.USER_AGENTS_PATH)
        if ua_path.exists():
            return self._read_json_file(ua_path)

        return [settings.SEARXNG_USER_AGENT]

    @staticmethod
    def _read_json_file(path: Path) -> list[str]:
        try:
            with path.open(encoding=settings.FILE_ENCODING) as f:
                loaded: list[str] = json.load(f)

                return loaded
        except Exception:
            logger.exception("Failed to load user agents")

            return [settings.SEARXNG_USER_AGENT]

    def _get_random_user_agent(self) -> str:
        return random.choice(self.user_agents)

    @staticmethod
    def _browser_tiers(strategies: dict[str, BaseStrategy]) -> dict[str, BaseStrategy]:
        names = (
            "4-playwright_stealth",
            _PATCHRIGHT_TIER_NAME,
            _CAMOUFOX_TIER_NAME,
            "5-crawlee_adaptive",
            NOVNC_STRATEGY_NAME,
        )

        return {name: strategies[name] for name in names if name in strategies}

    @staticmethod
    def _drop_disabled_tiers(strategies: dict[str, BaseStrategy]) -> dict[str, BaseStrategy]:
        """Skip tiers the operator switched off, on every chain. A caller that
        names a disabled tier itself as its starting tier is refused by
        `_require_tier_enabled` before this runs."""
        if not settings.CAMOUFOX_ENABLED:
            strategies = {
                name: strategy for name, strategy in strategies.items() if name != _CAMOUFOX_TIER_NAME
            }

        return strategies

    @staticmethod
    def _drop_human_tier(strategies: dict[str, BaseStrategy]) -> dict[str, BaseStrategy]:
        """Stop the ladder before the human-intervention tier."""
        return {name: strategy for name, strategy in strategies.items() if name != NOVNC_STRATEGY_NAME}

    @staticmethod
    def _from_tier(strategies: dict[str, BaseStrategy], tier: TierName) -> dict[str, BaseStrategy]:
        """Return *tier* and every tier after it, so escalation still runs from
        there, or nothing when this chain dropped *tier*.

        Raises:
            ValueError: when *tier* is not a rung of the ladder at all.
        """
        if tier not in TIER_ORDER:
            raise ValueError(f"unknown tier: {tier}")

        names = list(strategies)
        if tier not in names:
            return {}

        return {name: strategies[name] for name in names[names.index(tier) :]}

    @staticmethod
    def _require_tier_enabled(tier: str) -> None:
        """Refuse a caller-selected starting tier the operator switched off:
        naming a disabled tier is answered, never silently run past."""
        if tier == _CAMOUFOX_TIER_NAME and not settings.CAMOUFOX_ENABLED:
            raise TierDisabledError(_CAMOUFOX_TIER_NAME)

    async def _select_strategies(
        self,
        url: str,
        heavy_mode: bool,
        profile: str | None = None,
        tier: TierName | None = None,
        allow_human_tier: bool = True,
    ) -> dict[str, BaseStrategy]:
        strategies = self._build_strategies(profile)
        if not allow_human_tier:
            strategies = self._drop_human_tier(strategies)

        if ChallengeDetector.is_login_redirect_url(url):
            logger.warning(
                "WebReader: Pre-emptive URL redirect login detected on %s. Forcing NoVNC strategy.",
                address_without_query(url),
            )
            return {name: strategies[name] for name in (NOVNC_STRATEGY_NAME,) if name in strategies}

        if tier is not None:
            self._require_tier_enabled(tier)

            return self._from_tier(self._drop_disabled_tiers(strategies), tier)

        strategies = self._drop_disabled_tiers(strategies)

        if not await self._prefer_browser(url, heavy_mode, profile):
            remembered = await tier_memory.get(url)
            if remembered is not None and remembered in strategies:
                return self._from_tier(strategies, cast("TierName", remembered))

            return strategies

        return self._browser_tiers(strategies)

    @staticmethod
    async def _session_expired(url: str, profile: str | None) -> bool:
        """True when a login was captured for this target and no longer validates.

        A target nobody logged into, including one holding only a WAF clearance,
        is never gated here: it has no session to expire and reads anonymously
        exactly as it always did.
        """
        if not await cookie_manager.has_auth_state(url, profile):
            return False

        return not await session_manager.validate(url, profile)

    @staticmethod
    def _create_session_expired_response(url: str, profile: str | None) -> dict[str, Any]:
        domain = cookie_manager.registrable_domain(url)
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        logger.info(
            "WebReader: stored session for %s (profile=%s) is no longer valid; refusing to read anonymously",
            domain,
            effective_profile,
        )

        return {
            "content": "",
            "status": SESSION_EXPIRED_STATUS,
            "profile": effective_profile,
            "message": (
                f"Stored session for {domain} (profile={effective_profile}) is no longer valid. "
                f"Re-establish it with the session establish operation, then read again."
            ),
        }

    async def _has_stored_session(self, url: str, profile: str | None) -> bool:
        return await cookie_manager.get_storage_state(url, profile) is not None

    async def _prefer_browser(self, url: str, heavy_mode: bool, profile: str | None) -> bool:
        return heavy_mode or await self._has_stored_session(url, profile)

    @staticmethod
    def _record_strategy_outcome(name: str, outcome: str, dlabel: str, elapsed: float) -> None:
        STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome=outcome, domain=dlabel).inc()
        STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(elapsed)

    @staticmethod
    def _budget_exceeded(started_at: float, name: str) -> bool:
        if name == NOVNC_STRATEGY_NAME:
            return False

        elapsed = time.perf_counter() - started_at
        if elapsed > settings.READ_TOTAL_BUDGET:
            READ_BUDGET_EXHAUSTED_TOTAL.inc()
            logger.warning(
                "WebReader: READ_TOTAL_BUDGET=%ss exceeded before %s (elapsed=%.1fs). "
                "Skipping remaining tiers.",
                settings.READ_TOTAL_BUDGET,
                name,
                elapsed,
            )

            return True

        return False

    # ------------------------------------------------------------------
    # Cache-aside helpers
    # ------------------------------------------------------------------

    def _cache_get(self, key: ReadCacheKey | None) -> dict[str, Any] | None:
        if key is None:
            return None

        entry = self._memory_cache.get(key)
        if entry is None:
            return None

        result, stored_at = entry
        if time.monotonic() - stored_at > settings.READ_CACHE_TTL_SECONDS:
            del self._memory_cache[key]

            return None

        return result

    def _cache_put(self, key: ReadCacheKey | None, result: dict[str, Any]) -> None:
        """Store *result* as the newest entry, dropping expired entries and the
        oldest ones past `_READ_CACHE_MAX_ENTRIES`. Insertion order is age order.
        A None *key* is a read that skips the cache, so nothing is stored."""
        if key is None:
            return

        now = time.monotonic()
        self._drop_expired_entries(now)
        self._memory_cache.pop(key, None)
        self._memory_cache[key] = (result, now)
        while len(self._memory_cache) > _READ_CACHE_MAX_ENTRIES:
            del self._memory_cache[next(iter(self._memory_cache))]

    def _drop_expired_entries(self, now: float) -> None:
        for key, (_result, stored_at) in list(self._memory_cache.items()):
            if now - stored_at <= settings.READ_CACHE_TTL_SECONDS:
                return

            del self._memory_cache[key]

    def clear_cache(self) -> int:
        """Drop the whole in-process read cache, returning the dropped count."""
        count = len(self._memory_cache)
        self._memory_cache.clear()

        return count

    def clear_cache_for_domain(self, domain: str) -> int:
        """Purge in-process read-result cache entries whose URL belongs to *domain*.

        Used when a stored session for that domain is cleared, so a stale
        cached read captured before the session was known-bad is not served
        for the remainder of its TTL. Returns the number of entries removed.
        """
        stale_keys = [
            key for key in self._memory_cache if cookie_manager.registrable_domain(key.url) == domain
        ]
        for key in stale_keys:
            del self._memory_cache[key]

        return len(stale_keys)

    # ------------------------------------------------------------------
    # Public read methods
    # ------------------------------------------------------------------

    @staticmethod
    def _main_pdf_link(page_html: str, url: str) -> str | None:
        """The `.pdf` main link of a document wrapper page, or None.

        A page is a wrapper when one `.pdf` address, resolved against the page
        URL, is the only target its links point to, and its own text, link text
        left out, stays under `_WRAPPER_MAX_OWN_WORDS` words. An article that
        also links a PDF is read as the article.
        """
        soup = BeautifulSoup(page_html, "html.parser")
        anchors = soup.find_all("a", href=True)
        targets = {urldefrag(urljoin(url, str(anchor.get("href")))).url for anchor in anchors}
        targets.discard(urldefrag(url).url)
        if len(targets) != 1:
            return None

        (target,) = targets
        if not urlparse(target).path.lower().endswith(".pdf"):
            return None

        for element in [*anchors, *soup.find_all(_NON_TEXT_TAGS)]:
            element.decompose()
        if len(soup.get_text(" ").split()) >= _WRAPPER_MAX_OWN_WORDS:
            return None

        return target

    def _cached_unless_screenshot(
        self, key: ReadCacheKey | None, fmt: str, url: str
    ) -> dict[str, Any] | None:
        if fmt == "screenshot":
            return None
        cached = self._cache_get(key)
        if cached is not None:
            READ_CACHE_HITS_TOTAL.inc()
            logger.debug("WebReader: cache hit for %s", address_without_query(url))

        return cached

    @staticmethod
    def _only_screenshot_capable(strategies: dict[str, BaseStrategy], fmt: str) -> dict[str, BaseStrategy]:
        if fmt != "screenshot":
            return strategies
        capable = {
            name: strategy
            for name, strategy in strategies.items()
            if getattr(strategy, "screenshot_page", None) is not None
        }
        if not capable:
            raise ScreenshotUnavailableError()

        return capable

    @staticmethod
    def _routed_document(routed: RouteResult) -> dict[str, Any]:
        return {
            "content": routed.content,
            "status": "success",
            "mode": "document-router",
            "route": routed.route,
        }

    @staticmethod
    def _refused_document(refused: RouteResult) -> dict[str, Any]:
        return {
            "content": "",
            "status": "error",
            "reason": "routing_error",
            "route": refused.route,
            "routing_error": refused.error,
        }

    @staticmethod
    def _with_routing_error(result: dict[str, Any], failed_route: RouteResult | None) -> dict[str, Any]:
        """Name a failed direct route on the HTML extraction that answered instead."""
        if failed_route is None:
            return result

        return PageResult(
            {**result, "route": failed_route.route, "routing_error": failed_route.error},
            PageResult.of(result).page,
        )

    def _finish_read(
        self, key: ReadCacheKey | None, fmt: str, result: dict[str, Any], failed_route: RouteResult | None
    ) -> dict[str, Any]:
        finished = self._with_routing_error(result, failed_route)
        self._cache_result(key, fmt, finished)

        return finished

    @staticmethod
    async def _remember_tier(url: str, name: str, tier: TierName | None, heavy_mode: bool) -> None:
        """Remember the tier that served an unpinned read, so the next read of
        the domain starts there. A read with a caller tier or heavy_mode chose
        its own start and says nothing about the domain."""
        if tier is None and not heavy_mode:
            await tier_memory.record(url, name)

    def _cache_result(self, key: ReadCacheKey | None, fmt: str, result: dict[str, Any]) -> None:
        """Cache a whole successful read: never a screenshot, never a read whose routing failed."""
        if fmt != "screenshot" and "routing_error" not in result:
            self._cache_put(key, result)

    @staticmethod
    async def _screenshot_result(name: str, strategy: BaseStrategy, url: str) -> dict[str, Any] | None:
        """Base64 PNG from the browser tier that served the read."""
        capture = getattr(strategy, "screenshot_page", None)
        if capture is None:
            raise ScreenshotUnavailableError(f"tier {name} cannot produce a screenshot")
        page = await capture(url)
        if page is None:
            return None
        html, png = page
        await _second_look(html, url)

        return PageResult(
            {
                "content": base64.b64encode(png).decode("ascii"),
                "status": "success",
                "mode": name,
            },
            html,
        )

    async def _execute_screenshot_format(
        self, name: str, strategy: BaseStrategy, url: str, started: float, dlabel: str
    ) -> dict[str, Any] | None:
        """One navigation returns the rendered HTML and the PNG."""
        shot = await self._screenshot_result(name, strategy, url)
        if shot is None:
            self._record_strategy_outcome(name, "exception", dlabel, time.perf_counter() - started)
            logger.info("Strategy %s screenshot capture failed.", name)

            return None

        self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)

        return shot

    async def _execute_tables_format(
        self, name: str, page_html: str, started: float, dlabel: str
    ) -> dict[str, Any] | None:
        tables = extract_tables(page_html)
        if not tables:
            self._record_strategy_outcome(name, "empty", dlabel, time.perf_counter() - started)
            logger.info("Strategy %s found no tables.", name)

            return None

        flat = " ".join(cell for table in tables for row in table for cell in row)
        if self.validator.validate(flat):
            self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)

            return {"content": flat, "tables": tables, "status": "success", "mode": name}

        self._record_strategy_outcome(name, "validation_failed", dlabel, time.perf_counter() - started)
        logger.info("Strategy %s tables validation failed.", name)

        return None

    async def _with_main_pdf(
        self, url: str, page_html: str, content: str, mode: str, output_format: str | None
    ) -> dict[str, Any]:
        """Merge a routed main `.pdf` link into a text result."""
        if output_format not in (None, "text"):
            return {"content": content, "status": "success", "mode": mode}
        linked = await self._maybe_route_main_pdf(url, page_html)
        if linked is None:
            return {"content": content, "status": "success", "mode": mode}
        if "content" in linked:
            return {
                "content": linked["content"],
                "status": "success",
                "mode": mode,
                "route": linked["route"],
            }

        return {
            "content": content,
            "status": "success",
            "mode": mode,
            "route": linked["route"],
            "routing_error": linked["routing_error"],
        }

    async def _maybe_route_main_pdf(self, url: str, page_html: str) -> dict[str, Any] | None:
        """Route a page's main `.pdf` link, or None when the page links none."""
        link = self._main_pdf_link(page_html, url)
        if link is None:
            return None
        routed = await route_document(link)
        if routed is None or not routed.ok:
            return {"route": "pdf", "routing_error": routed.error if routed else "download_failed"}
        return {"route": "pdf", "content": routed.content}

    async def read(
        self,
        url: str,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        extraction_schema: dict[str, Any] | None = None,
        *,
        allow_human_tier: bool = True,
    ) -> dict[str, Any]:
        """Read *url* in *output_format*. With *allow_human_tier* false the
        ladder stops before 6-novnc, for callers no human watches."""
        page_read = await self.read_page(
            url,
            heavy_mode,
            profile,
            output_format,
            tier,
            extraction_schema,
            allow_human_tier=allow_human_tier,
        )

        return dict(page_read)

    async def read_page(
        self,
        url: str,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        extraction_schema: dict[str, Any] | None = None,
        *,
        allow_human_tier: bool = True,
        use_read_cache: bool = True,
    ) -> PageResult:
        """The answer of :meth:`read`, keeping the page HTML of the fetch that served it.

        With *use_read_cache* false the read neither answers from nor writes to the read cache.
        """
        _challenge_verdict.set(None)
        if await self._session_expired(url, profile):
            return PageResult(self._create_session_expired_response(url, profile))

        fmt: str = output_format or "text"
        if fmt == "schema" and extraction_schema is None:
            raise ValueError("extraction_schema is required with output_format=schema")
        if extraction_schema is not None:
            check_schema_size(extraction_schema)
        digest = schema_hash(extraction_schema) if extraction_schema is not None else ""
        key = _cache_key(url, heavy_mode, False, profile, fmt, tier, digest) if use_read_cache else None
        cached = self._cached_unless_screenshot(key, fmt, url)
        if cached is not None:
            return PageResult.of(cached)

        direct = await route_document(url)
        if direct is not None and direct.ok:
            routed = PageResult(self._routed_document(direct))
            self._cache_result(key, fmt, routed)

            return routed
        if direct is not None and direct.ends_read:
            return PageResult(self._refused_document(direct))

        logger.info(
            "Reading URL: %s (heavy_mode: %s, profile: %s, tier: %s)",
            address_without_query(url),
            heavy_mode,
            profile,
            tier,
        )
        strategies_to_run = await self._select_strategies(url, heavy_mode, profile, tier, allow_human_tier)
        strategies_to_run = self._only_screenshot_capable(strategies_to_run, fmt)
        started_at = time.perf_counter()
        budget_exhausted = False

        for name, strategy in strategies_to_run.items():
            if self._budget_exceeded(started_at, name):
                budget_exhausted = True
                break

            result = await self._execute_strategy(
                name,
                strategy,
                url,
                output_format=fmt,
                extraction_schema=extraction_schema,
                escalate_failures=tier is None and fmt != "schema",
            )
            if result:
                await self._remember_tier(url, name, tier, heavy_mode)

                return PageResult.of(self._finish_read(key, fmt, result, direct))
            if self._landed_on_login():
                break

        login_landing = self._landed_on_login()
        if (budget_exhausted or login_landing) and NOVNC_STRATEGY_NAME in strategies_to_run:
            novnc_result = await self._execute_strategy(
                NOVNC_STRATEGY_NAME,
                strategies_to_run[NOVNC_STRATEGY_NAME],
                url,
                output_format=fmt,
                extraction_schema=extraction_schema,
            )
            if novnc_result:
                await self._remember_tier(url, NOVNC_STRATEGY_NAME, tier, heavy_mode)

                return PageResult.of(self._finish_read(key, fmt, novnc_result, direct))

        return PageResult.of(
            self._with_routing_error(
                self._create_failure_response(
                    url, budget_exhausted=budget_exhausted, login_required=login_landing
                ),
                direct,
            )
        )

    async def read_with_links(
        self,
        url: str,
        link_filter: str | None = None,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        *,
        allow_human_tier: bool = True,
    ) -> dict[str, Any]:
        """Read *url* with its links annotated. With *allow_human_tier* false the
        ladder stops before 6-novnc, for callers no human watches."""
        linked = await self.read_linked_page(
            url,
            link_filter,
            heavy_mode,
            profile,
            output_format,
            tier,
            allow_human_tier=allow_human_tier,
        )

        return dict(linked)

    async def read_linked_page(
        self,
        url: str,
        link_filter: str | None = None,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
        *,
        allow_human_tier: bool = True,
        use_read_cache: bool = True,
    ) -> PageResult:
        """The answer of :meth:`read_with_links`, keeping the page HTML of the fetch that served it.

        With *use_read_cache* false the read neither answers from nor writes to the read cache.
        """
        _challenge_verdict.set(None)
        if await self._session_expired(url, profile):
            return PageResult(self._create_session_expired_response(url, profile))

        key = (
            _cache_key(url, heavy_mode, True, profile, output_format, tier, link_filter=link_filter)
            if use_read_cache
            else None
        )
        cached = self._cache_get(key)
        if cached is not None:
            READ_CACHE_HITS_TOTAL.inc()
            logger.debug("WebReader: cache hit (with links) for %s", address_without_query(url))

            return PageResult.of(cached)

        logger.info(
            "Reading URL with links: %s (heavy_mode: %s, profile: %s, tier: %s)",
            address_without_query(url),
            heavy_mode,
            profile,
            tier,
        )
        strategies_to_run = await self._select_strategies(url, heavy_mode, profile, tier, allow_human_tier)
        started_at = time.perf_counter()
        budget_exhausted = False

        for name, strategy in strategies_to_run.items():
            if self._budget_exceeded(started_at, name):
                budget_exhausted = True
                break

            html = await self._execute_html_strategy(name, strategy, url, escalate_failures=tier is None)
            if html:
                content, links = annotate_links(html, url, link_filter)
                if self.validator.validate(content):
                    result = PageResult(
                        {"content": content, "links": links, "status": "success", "mode": name}, html
                    )
                    await self._remember_tier(url, name, tier, heavy_mode)
                    self._cache_put(key, result)

                    return result

                logger.info("Strategy %s validation failed after annotation.", name)
            if self._landed_on_login():
                break

        login_landing = self._landed_on_login()
        if (budget_exhausted or login_landing) and NOVNC_STRATEGY_NAME in strategies_to_run:
            html = await self._execute_html_strategy(
                NOVNC_STRATEGY_NAME, strategies_to_run[NOVNC_STRATEGY_NAME], url
            )
            if html:
                content, links = annotate_links(html, url, link_filter)
                if self.validator.validate(content):
                    result = PageResult(
                        {
                            "content": content,
                            "links": links,
                            "status": "success",
                            "mode": NOVNC_STRATEGY_NAME,
                        },
                        html,
                    )
                    await self._remember_tier(url, NOVNC_STRATEGY_NAME, tier, heavy_mode)
                    self._cache_put(key, result)

                    return result

        return PageResult(
            self._create_failure_response(
                url, budget_exhausted=budget_exhausted, login_required=login_landing
            )
        )

    # ------------------------------------------------------------------
    # Internal execution helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _novnc_or_tier_html(name: str, strategy: BaseStrategy, url: str) -> FetchedHtml | str:
        verdict = _challenge_verdict.get()
        if name == NOVNC_STRATEGY_NAME and verdict is not None:
            return await cast("NoVNCStrategy", strategy).get_html(url, verdict)

        return await strategy.get_html(url)

    async def _extract_with_schema(
        self,
        name: str,
        url: str,
        page_html: str,
        extraction_schema: dict[str, Any],
    ) -> dict[str, Any]:
        """Schema extraction with recipe replay."""
        domain = cookie_manager.registrable_domain(url)
        digest = schema_hash(extraction_schema)
        selectors = await recipe_lookup(domain, digest)
        if selectors is not None:
            if not names_whole_document(page_html, selectors):
                replayed = build_object(page_html, selectors, extraction_schema)
                if replay_valid(replayed, extraction_schema):
                    return {"content": replayed, "status": "success", "mode": name, "recipe": "replay"}
            await recipe_delete(domain, digest)
        data, fresh = await run_schema_model(clean_markup(page_html), extraction_schema)
        await recipe_store_put(domain, digest, fresh, page_html, expected=data, schema=extraction_schema)

        return {"content": data, "status": "success", "mode": name, "recipe": "model"}

    async def _format_result(
        self,
        name: str,
        url: str,
        page_html: str,
        output_format: str | None,
        extraction_schema: dict[str, Any] | None,
        started: float,
        dlabel: str,
    ) -> dict[str, Any] | None:
        """Dispatch one tier's HTML to the requested output format."""
        if output_format == "schema":
            if extraction_schema is None:
                raise ValueError("extraction_schema is required with output_format=schema")
            schemed = await self._extract_with_schema(name, url, page_html, extraction_schema)
            self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)

            return schemed

        if output_format == "tables":
            return await self._execute_tables_format(name, page_html, started, dlabel)

        if output_format == "structured":
            structured = extract_structured(page_html)
            structured_content = structured.get("content", "")
            if self.validator.validate(structured_content):
                self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)

                return {**structured, "status": "success", "mode": name}

            elapsed = time.perf_counter() - started
            self._record_strategy_outcome(name, "validation_failed", dlabel, elapsed)
            logger.info("Strategy %s structured validation failed.", name)

            return None

        text = extract_text_with_fallback(page_html)
        if self.validator.validate(text):
            self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)

            return await self._with_main_pdf(url, page_html, text, name, output_format)

        self._record_strategy_outcome(name, "validation_failed", dlabel, time.perf_counter() - started)
        logger.info("Strategy %s validation failed.", name)

        return None

    async def _execute_strategy(
        self,
        name: str,
        strategy: BaseStrategy,
        url: str,
        output_format: str | None = None,
        extraction_schema: dict[str, Any] | None = None,
        escalate_failures: bool = False,
    ) -> dict[str, Any] | None:
        started = time.perf_counter()
        dlabel = domain_label(url)

        try:
            logger.info("--- Strategy %s STARTED ---", name)

            if output_format == "screenshot":
                return await self._execute_screenshot_format(name, strategy, url, started, dlabel)

            html = await self._novnc_or_tier_html(name, strategy, url)
            if not html:
                self._record_strategy_outcome(name, "empty", dlabel, time.perf_counter() - started)
                logger.info("Strategy %s returned empty HTML.", name)

                return None

            await _second_look(html, url)

            formatted = await self._format_result(
                name, url, html, output_format, extraction_schema, started, dlabel
            )

            return None if formatted is None else PageResult(formatted, html)
        except ChallengeDetectedException as exc:
            _challenge_verdict.set(exc.verdict)
            self._record_strategy_outcome(name, "challenge_detected", dlabel, time.perf_counter() - started)
            logger.info(
                "Strategy %s detected a challenge on %s; falling through to the next tier.",
                name,
                address_without_query(url),
            )

            return None
        except UnsafeUriError:
            self._record_strategy_outcome(name, "unsafe_uri", dlabel, time.perf_counter() - started)

            raise
        except HumanInterventionRequiredException:
            self._record_strategy_outcome(name, "human_intervention", dlabel, time.perf_counter() - started)

            raise
        except NoVNCFlowBusyException:
            self._record_strategy_outcome(name, "novnc_busy", dlabel, time.perf_counter() - started)

            raise
        except ExtractionFailedError as exc:
            self._record_strategy_outcome(name, "exception", dlabel, time.perf_counter() - started)
            if not escalate_failures:
                raise
            logger.info(
                "Strategy %s could not fetch %s (%s); falling through to the next tier.",
                name,
                address_without_query(url),
                exc,
            )

            return None
        except (ExtractionNotConfiguredError, ScreenshotUnavailableError):
            self._record_strategy_outcome(name, "exception", dlabel, time.perf_counter() - started)

            raise
        except Exception as e:
            self._record_strategy_outcome(name, "exception", dlabel, time.perf_counter() - started)
            logger.warning(
                "Strategy %s failed for %s: %s",
                name,
                address_without_query(url),
                exception_text_without_queries(e),
            )

            return None

    async def _execute_html_strategy(
        self,
        name: str,
        strategy: BaseStrategy,
        url: str,
        escalate_failures: bool = False,
    ) -> FetchedHtml | str:
        started = time.perf_counter()
        dlabel = domain_label(url)

        try:
            logger.info("--- Strategy %s STARTED ---", name)
            html = await self._novnc_or_tier_html(name, strategy, url)
            if html:
                await _second_look(html, url)

                self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)

                return html

            self._record_strategy_outcome(name, "empty", dlabel, time.perf_counter() - started)
            logger.info("Strategy %s returned empty HTML.", name)
        except HumanInterventionRequiredException:
            self._record_strategy_outcome(name, "human_intervention", dlabel, time.perf_counter() - started)

            raise
        except UnsafeUriError:
            self._record_strategy_outcome(name, "unsafe_uri", dlabel, time.perf_counter() - started)

            raise
        except NoVNCFlowBusyException:
            self._record_strategy_outcome(name, "novnc_busy", dlabel, time.perf_counter() - started)

            raise
        except ExtractionFailedError as exc:
            self._record_strategy_outcome(name, "exception", dlabel, time.perf_counter() - started)
            if not escalate_failures:
                raise
            logger.info(
                "Strategy %s could not fetch %s (%s); falling through to the next tier.",
                name,
                address_without_query(url),
                exc,
            )

            return ""
        except ExtractionNotConfiguredError:
            self._record_strategy_outcome(name, "exception", dlabel, time.perf_counter() - started)

            raise
        except ChallengeDetectedException as exc:
            _challenge_verdict.set(exc.verdict)
            self._record_strategy_outcome(name, "challenge_detected", dlabel, time.perf_counter() - started)
            logger.info(
                "Strategy %s detected a challenge on %s; falling through to the next tier.",
                name,
                address_without_query(url),
            )

            return ""
        except Exception as e:
            self._record_strategy_outcome(name, "exception", dlabel, time.perf_counter() - started)
            logger.warning(
                "Strategy %s get_html failed for %s: %s",
                name,
                address_without_query(url),
                exception_text_without_queries(e),
            )

        return ""

    @staticmethod
    def _landed_on_login() -> bool:
        """True when the latest challenge verdict of this read came from the login landing rule."""
        verdict = _challenge_verdict.get()

        return verdict is not None and verdict.login_landing

    @staticmethod
    def _create_failure_response(
        url: str, *, budget_exhausted: bool = False, login_required: bool = False
    ) -> dict[str, Any]:
        if login_required:
            return {
                "content": "",
                "status": "error",
                "reason": "login_required",
                "error": f"A login is required to read {url}",
            }
        reason = "budget_exhausted" if budget_exhausted else "all_tiers_failed"

        return {
            "content": "",
            "status": "error",
            "reason": reason,
            "error": f"All extraction methods failed for {url}",
        }
