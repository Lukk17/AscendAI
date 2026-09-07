import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from src.api.exceptions import (
    ChallengeDetectedException,
    HumanInterventionRequiredException,
    NoVNCFlowBusyException,
)
from src.config.config import settings
from src.observability.domain_label import domain_label
from src.observability.metrics import (
    READ_BUDGET_EXHAUSTED_TOTAL,
    READ_CACHE_HITS_TOTAL,
    STRATEGY_ATTEMPTS_TOTAL,
    STRATEGY_DURATION_SECONDS,
)
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.cookie_manager import cookie_manager
from src.reader.extraction import extract_structured, extract_text_with_fallback
from src.reader.link_annotator import annotate_links
from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.strategies.beautifulsoup_strategy import BeautifulSoupStrategy
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.flaresolverr_strategy import FlareSolverrStrategy
from src.reader.strategies.novnc_strategy import NoVNCStrategy
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.reader.strategies.trafilatura_strategy import TrafilaturaStrategy
from src.validator.content_validator import ContentValidator
from src.validator.url_validator import url_validator

logger = logging.getLogger(__name__)

NOVNC_STRATEGY_NAME = "6-novnc"


def _cache_key(
    url: str,
    heavy_mode: bool,
    include_links: bool,
    profile: str | None,
    output_format: str | None,
) -> str:
    """Return a string key that uniquely identifies a read request for cache-aside."""
    return (
        f"{url}|heavy={heavy_mode}|links={include_links}"
        f"|profile={profile or ''}|fmt={output_format or 'text'}"
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
        return {
            "1-beautifulsoup": BeautifulSoupStrategy(self._get_random_user_agent, profile),
            "2-trafilatura": TrafilaturaStrategy(self._get_random_user_agent, profile),
            "3-flaresolverr": FlareSolverrStrategy(profile),
            "4-playwright_stealth": PlaywrightStrategy(
                self._get_random_user_agent, self.url_validator, profile
            ),
            "5-crawlee_adaptive": CrawleeStrategy(self.url_validator, profile),
            NOVNC_STRATEGY_NAME: NoVNCStrategy(profile),
        }

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

    def _select_strategies(
        self,
        url: str,
        prefer_browser: bool,
        profile: str | None = None,
    ) -> dict[str, BaseStrategy]:
        strategies = self._build_strategies(profile)

        if ChallengeDetector.is_login_redirect_url(url):
            logger.warning(
                "WebReader: Pre-emptive URL redirect login detected on %s. Forcing NoVNC strategy.", url
            )
            return {NOVNC_STRATEGY_NAME: strategies[NOVNC_STRATEGY_NAME]}

        if prefer_browser:
            return {
                "4-playwright_stealth": strategies["4-playwright_stealth"],
                "5-crawlee_adaptive": strategies["5-crawlee_adaptive"],
                NOVNC_STRATEGY_NAME: strategies[NOVNC_STRATEGY_NAME],
            }

        return strategies

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
            if cookie_manager._get_domain(key.split("|", 1)[0]) == domain  # noqa: SLF001
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
        output_format: str | None = None,
    ) -> dict[str, Any]:
        key = _cache_key(url, heavy_mode, False, profile, output_format)
        cached = self._cache_get(key)
        if cached is not None:
            READ_CACHE_HITS_TOTAL.inc()
            logger.debug("WebReader: cache hit for %s", url)

            return cached

        logger.info("Reading URL: %s (heavy_mode: %s, profile: %s)", url, heavy_mode, profile)
        prefer_browser = await self._prefer_browser(url, heavy_mode, profile)
        strategies_to_run = self._select_strategies(url, prefer_browser, profile)
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
        output_format: str | None = None,
    ) -> dict[str, Any]:
        key = _cache_key(url, heavy_mode, True, profile, output_format)
        cached = self._cache_get(key)
        if cached is not None:
            READ_CACHE_HITS_TOTAL.inc()
            logger.debug("WebReader: cache hit (with links) for %s", url)

            return cached

        logger.info("Reading URL with links: %s (heavy_mode: %s, profile: %s)", url, heavy_mode, profile)
        prefer_browser = await self._prefer_browser(url, heavy_mode, profile)
        strategies_to_run = self._select_strategies(url, prefer_browser, profile)
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
                raise ChallengeDetectedException(intervention_type="captcha")

            if output_format == "structured":
                structured = extract_structured(html)
                content = structured.get("content", "")
                if self.validator.validate(content):
                    self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)

                    return {**structured, "status": "success", "mode": name}

                elapsed = time.perf_counter() - started
                self._record_strategy_outcome(name, "validation_failed", dlabel, elapsed)
                logger.info("Strategy %s structured validation failed.", name)

                return None

            content = extract_text_with_fallback(html)
            if self.validator.validate(content):
                self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)

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
                    raise ChallengeDetectedException(intervention_type="captcha")

                self._record_strategy_outcome(name, "success", dlabel, time.perf_counter() - started)

                return html

            self._record_strategy_outcome(name, "empty", dlabel, time.perf_counter() - started)
            logger.info("Strategy %s returned empty HTML.", name)
        except HumanInterventionRequiredException:
            self._record_strategy_outcome(name, "human_intervention", dlabel, time.perf_counter() - started)

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
