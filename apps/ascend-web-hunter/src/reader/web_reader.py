import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Literal, cast

from ascend_python_common.uri_guard import UnsafeUriError

from src.api.exceptions import (
    ChallengeDetectedException,
    HumanInterventionRequiredException,
    NoVNCFlowBusyException,
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
from src.reader import tier_memory
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.challenge_signals import assess, log_verdict, record_verdict
from src.reader.cloudflare.cookie_manager import PRODUCED_BY_FLARESOLVERR, cookie_manager
from src.reader.extraction import extract_structured, extract_text_with_fallback
from src.reader.link_annotator import annotate_links
from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.strategies.beautifulsoup_strategy import BeautifulSoupStrategy
from src.reader.strategies.camoufox_strategy import CamoufoxStrategy
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.flaresolverr_strategy import FlareSolverrStrategy
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

TierName = Literal[
    "1-beautifulsoup",
    "2-trafilatura",
    "3-flaresolverr",
    "4-playwright_stealth",
    "4a-patchright",
    "4b-camoufox",
    "5-crawlee_adaptive",
    "6-novnc",
]
OutputFormat = Literal["text", "structured"]

# The ladder order. The escalation chain follows this tuple, never a sort on
# the tier name, so a new tier is inserted here and nowhere else.
TIER_ORDER: tuple[TierName, ...] = (
    "1-beautifulsoup",
    "2-trafilatura",
    "3-flaresolverr",
    "4-playwright_stealth",
    "4a-patchright",
    "4b-camoufox",
    "5-crawlee_adaptive",
    "6-novnc",
)

_PATCHRIGHT_TIER_NAME: TierName = "4a-patchright"
_CAMOUFOX_TIER_NAME: TierName = "4b-camoufox"


def _cache_key(
    url: str,
    heavy_mode: bool,
    include_links: bool,
    profile: str | None,
    output_format: str | None,
    tier: TierName | None = None,
) -> str:
    """Return a string key that uniquely identifies a read request for cache-aside."""
    return (
        f"{url}|heavy={heavy_mode}|links={include_links}"
        f"|profile={profile or ''}|fmt={output_format or 'text'}|tier={tier or ''}"
    )


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

        self._memory_cache: dict[str, tuple[dict[str, Any], float]] = {}

    def _build_strategies(self, profile: str | None = None) -> dict[str, BaseStrategy]:
        all_strategies: dict[str, BaseStrategy] = {
            "1-beautifulsoup": BeautifulSoupStrategy(self._get_random_user_agent, profile),
            "2-trafilatura": TrafilaturaStrategy(self._get_random_user_agent, profile),
            PRODUCED_BY_FLARESOLVERR: FlareSolverrStrategy(profile),
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
        """Skip tiers the operator switched off. A caller that names a disabled
        tier explicitly is answered by the caller, not by silently running past
        it, so the drop applies only to the unselected chain."""
        if not settings.FLARESOLVERR_ENABLED:
            strategies = {
                name: strategy
                for name, strategy in strategies.items()
                if name != PRODUCED_BY_FLARESOLVERR
            }
        if not settings.CAMOUFOX_ENABLED:
            strategies = {
                name: strategy for name, strategy in strategies.items() if name != _CAMOUFOX_TIER_NAME
            }

        return strategies

    @staticmethod
    def _from_tier(strategies: dict[str, BaseStrategy], tier: TierName) -> dict[str, BaseStrategy]:
        """Return *tier* and every tier after it, so escalation still runs from there."""
        names = list(strategies)

        return {name: strategies[name] for name in names[names.index(tier) :]}

    @staticmethod
    def _require_tier_enabled(tier: str) -> None:
        """Refuse a caller-selected tier the operator switched off. The drop in
        `_drop_disabled_tiers` only applies to the unselected chain; naming a
        disabled tier is answered, never silently run past."""
        if tier == PRODUCED_BY_FLARESOLVERR and not settings.FLARESOLVERR_ENABLED:
            raise TierDisabledError(PRODUCED_BY_FLARESOLVERR)
        if tier == _CAMOUFOX_TIER_NAME and not settings.CAMOUFOX_ENABLED:
            raise TierDisabledError(_CAMOUFOX_TIER_NAME)

    async def _select_strategies(
        self,
        url: str,
        heavy_mode: bool,
        profile: str | None = None,
        tier: TierName | None = None,
    ) -> dict[str, BaseStrategy]:
        strategies = self._build_strategies(profile)

        if ChallengeDetector.is_login_redirect_url(url):
            logger.warning(
                "WebReader: Pre-emptive URL redirect login detected on %s. Forcing NoVNC strategy.", url
            )
            return {NOVNC_STRATEGY_NAME: strategies[NOVNC_STRATEGY_NAME]}

        # An explicit tier is the most specific instruction a caller can give, so it
        # outranks heavy_mode and the producer-aware routing below (ADR-011).
        if tier is not None:
            self._require_tier_enabled(tier)

            return self._from_tier(strategies, tier)

        strategies = self._drop_disabled_tiers(strategies)

        if not await self._prefer_browser(url, heavy_mode, profile):
            remembered = await tier_memory.get(url)
            if remembered is not None and remembered in strategies:
                return self._from_tier(strategies, cast("TierName", remembered))

            return strategies

        if not heavy_mode:
            producer = await cookie_manager.get_stored_session_producer(url, profile)
            if producer == PRODUCED_BY_FLARESOLVERR and settings.FLARESOLVERR_ENABLED:
                return {
                    PRODUCED_BY_FLARESOLVERR: strategies[PRODUCED_BY_FLARESOLVERR],
                    **self._browser_tiers(strategies),
                }
            if producer == PRODUCED_BY_FLARESOLVERR:
                return self._browser_tiers(strategies)

        return self._browser_tiers(strategies)

    @staticmethod
    async def _session_expired(url: str, profile: str | None) -> bool:
        """True when a login was captured for this target and no longer validates.

        A target nobody logged into, including one holding only a WAF clearance,
        is never gated here: it has no session to expire and reads anonymously
        exactly as it always did.
        """
        if not await cookie_manager.has_auth_cookies(url, profile):
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
    # Cache-aside helpers (7.1)
    # ------------------------------------------------------------------

    def _cache_get(self, key: str) -> dict[str, Any] | None:
        entry = self._memory_cache.get(key)
        if entry is None:
            return None

        result, stored_at = entry
        if time.monotonic() - stored_at > settings.READ_CACHE_TTL_SECONDS:
            del self._memory_cache[key]

            return None

        return result

    def _cache_put(self, key: str, result: dict[str, Any]) -> None:
        self._memory_cache[key] = (result, time.monotonic())

    def clear_cache_for_domain(self, domain: str) -> int:
        """Purge in-process read-result cache entries whose URL belongs to *domain*.

        Used when a stored session for that domain is cleared, so a stale
        cached read captured before the session was known-bad is not served
        for the remainder of its TTL. Returns the number of entries removed.
        """
        stale_keys = [
            key
            for key in self._memory_cache
            if cookie_manager.registrable_domain(key.split("|", 1)[0]) == domain
        ]
        for key in stale_keys:
            del self._memory_cache[key]

        return len(stale_keys)

    # ------------------------------------------------------------------
    # Public read methods
    # ------------------------------------------------------------------

    async def read(
        self,
        url: str,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
    ) -> dict[str, Any]:
        if await self._session_expired(url, profile):
            return self._create_session_expired_response(url, profile)

        key = _cache_key(url, heavy_mode, False, profile, output_format, tier)
        cached = self._cache_get(key)
        if cached is not None:
            READ_CACHE_HITS_TOTAL.inc()
            logger.debug("WebReader: cache hit for %s", url)

            return cached

        logger.info("Reading URL: %s (heavy_mode: %s, profile: %s, tier: %s)", url, heavy_mode, profile, tier)
        strategies_to_run = await self._select_strategies(url, heavy_mode, profile, tier)
        started_at = time.perf_counter()
        budget_exhausted = False

        for name, strategy in strategies_to_run.items():
            if self._budget_exceeded(started_at, name):
                budget_exhausted = True
                break

            result = await self._execute_strategy(name, strategy, url, output_format=output_format)
            if result:
                self._cache_put(key, result)

                return result

        if budget_exhausted and NOVNC_STRATEGY_NAME in strategies_to_run:
            novnc_result = await self._execute_strategy(
                NOVNC_STRATEGY_NAME,
                strategies_to_run[NOVNC_STRATEGY_NAME],
                url,
                output_format=output_format,
            )
            if novnc_result:
                self._cache_put(key, novnc_result)

                return novnc_result

        return self._create_failure_response(url, budget_exhausted=budget_exhausted)

    async def read_with_links(
        self,
        url: str,
        link_filter: str | None = None,
        heavy_mode: bool = False,
        profile: str | None = None,
        output_format: OutputFormat | None = None,
        tier: TierName | None = None,
    ) -> dict[str, Any]:
        if await self._session_expired(url, profile):
            return self._create_session_expired_response(url, profile)

        key = _cache_key(url, heavy_mode, True, profile, output_format, tier)
        cached = self._cache_get(key)
        if cached is not None:
            READ_CACHE_HITS_TOTAL.inc()
            logger.debug("WebReader: cache hit (with links) for %s", url)

            return cached

        logger.info(
            "Reading URL with links: %s (heavy_mode: %s, profile: %s, tier: %s)",
            url,
            heavy_mode,
            profile,
            tier,
        )
        strategies_to_run = await self._select_strategies(url, heavy_mode, profile, tier)
        started_at = time.perf_counter()
        budget_exhausted = False

        for name, strategy in strategies_to_run.items():
            if self._budget_exceeded(started_at, name):
                budget_exhausted = True
                break

            html = await self._execute_html_strategy(name, strategy, url)
            if html:
                content, links = annotate_links(html, url, link_filter)
                if self.validator.validate(content):
                    result = {"content": content, "links": links, "status": "success", "mode": name}
                    await tier_memory.record(url, name)
                    self._cache_put(key, result)

                    return result

                logger.info("Strategy %s validation failed after annotation.", name)

        if budget_exhausted and NOVNC_STRATEGY_NAME in strategies_to_run:
            html = await self._execute_html_strategy(
                NOVNC_STRATEGY_NAME, strategies_to_run[NOVNC_STRATEGY_NAME], url
            )
            if html:
                content, links = annotate_links(html, url, link_filter)
                if self.validator.validate(content):
                    result = {
                        "content": content,
                        "links": links,
                        "status": "success",
                        "mode": NOVNC_STRATEGY_NAME,
                    }
                    await tier_memory.record(url, NOVNC_STRATEGY_NAME)
                    self._cache_put(key, result)

                    return result

        return self._create_failure_response(url, budget_exhausted=budget_exhausted)

    # ------------------------------------------------------------------
    # Internal execution helpers
    # ------------------------------------------------------------------

    async def _execute_strategy(
        self,
        name: str,
        strategy: BaseStrategy,
        url: str,
        output_format: str | None = None,
    ) -> dict[str, Any] | None:
        started = time.perf_counter()
        dlabel = domain_label(url)

        try:
            logger.info("--- Strategy %s STARTED ---", name)

            html = await strategy.get_html(url)
            if not html:
                self._record_strategy_outcome(name, "empty", dlabel, time.perf_counter() - started)
                logger.info("Strategy %s returned empty HTML.", name)

                return None

            if not ChallengeDetector.is_content_accepted(200, html):
                verdict = assess(200, html)
                record_verdict(verdict, "reader")
                log_verdict(verdict, "reader", url)
                raise ChallengeDetectedException(verdict)

            if output_format == "structured":
                structured = extract_structured(html)
                content = structured.get("content", "")
                if self.validator.validate(content):
                    self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)
                    await tier_memory.record(url, name)

                    return {**structured, "status": "success", "mode": name}

                elapsed = time.perf_counter() - started
                self._record_strategy_outcome(name, "validation_failed", dlabel, elapsed)
                logger.info("Strategy %s structured validation failed.", name)

                return None

            content = extract_text_with_fallback(html)
            if self.validator.validate(content):
                self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)
                await tier_memory.record(url, name)

                return {"content": content, "status": "success", "mode": name}

            self._record_strategy_outcome(name, "validation_failed", dlabel, time.perf_counter() - started)
            logger.info("Strategy %s validation failed.", name)

            return None
        except ChallengeDetectedException:
            self._record_strategy_outcome(name, "challenge_detected", dlabel, time.perf_counter() - started)
            logger.info(
                "Strategy %s detected a challenge on %s; falling through to the next tier.", name, url
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
        except Exception as e:
            self._record_strategy_outcome(name, "exception", dlabel, time.perf_counter() - started)
            logger.warning("Strategy %s failed for %s: %s", name, url, e)

            return None

    async def _execute_html_strategy(
        self,
        name: str,
        strategy: BaseStrategy,
        url: str,
    ) -> str:
        started = time.perf_counter()
        dlabel = domain_label(url)

        try:
            logger.info("--- Strategy %s STARTED ---", name)
            html = await strategy.get_html(url)
            if html:
                if not ChallengeDetector.is_content_accepted(200, html):
                    verdict = assess(200, html)
                    record_verdict(verdict, "reader")
                    log_verdict(verdict, "reader", url)
                    raise ChallengeDetectedException(verdict)

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
        except ChallengeDetectedException:
            self._record_strategy_outcome(name, "challenge_detected", dlabel, time.perf_counter() - started)
            logger.info(
                "Strategy %s detected a challenge on %s; falling through to the next tier.", name, url
            )

            return ""
        except Exception as e:
            self._record_strategy_outcome(name, "exception", dlabel, time.perf_counter() - started)
            logger.warning("Strategy %s get_html failed for %s: %s", name, url, e)

        return ""

    @staticmethod
    def _create_failure_response(url: str, *, budget_exhausted: bool = False) -> dict[str, Any]:
        reason = "budget_exhausted" if budget_exhausted else "all_tiers_failed"

        return {
            "content": "",
            "status": "error",
            "reason": reason,
            "error": f"All extraction methods failed for {url}",
        }
