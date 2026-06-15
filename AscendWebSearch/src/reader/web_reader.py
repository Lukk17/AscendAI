import json
import logging
import random
import time
from pathlib import Path
from typing import Any

from src.api.exceptions import ChallengeDetectedException, HumanInterventionRequiredException
from src.config.blocklist_loader import BlocklistLoader
from src.config.config import settings
from src.observability.metrics import (
    READ_BUDGET_EXHAUSTED_TOTAL,
    STRATEGY_ATTEMPTS_TOTAL,
    STRATEGY_DURATION_SECONDS,
)
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.link_annotator import annotate_links
from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.strategies.beautifulsoup_strategy import BeautifulSoupStrategy
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.flaresolverr_strategy import FlareSolverrStrategy
from src.reader.strategies.novnc_strategy import NoVNCStrategy
from src.reader.strategies.playwright_strategy import PlaywrightStrategy
from src.reader.strategies.trafilatura_strategy import TrafilaturaStrategy
from src.validator.content_validator import ContentValidator
from src.validator.url_validator import URLValidator

logger = logging.getLogger(__name__)

NOVNC_STRATEGY_NAME = "6-novnc"


class WebReader:
    """
    Advanced WebReader Orchestrator.
    Manages multi-tier extraction strategies.
    dictates the execution order of strategies.
    """

    def __init__(self) -> None:
        self.validator = ContentValidator()
        self.user_agents = self._load_user_agents()

        blocklist_loader = BlocklistLoader()
        rules = blocklist_loader.load_rules()
        self.url_validator = URLValidator(rules)

    def _build_strategies(self, profile: str | None = None) -> dict[str, BaseStrategy]:
        return {
            "1-beautifulsoup": BeautifulSoupStrategy(self._get_random_user_agent, profile),
            "2-trafilatura": TrafilaturaStrategy(self._get_random_user_agent, profile),
            "3-flaresolverr": FlareSolverrStrategy(profile),
            "4-playwright_stealth": PlaywrightStrategy(self._get_random_user_agent, self.url_validator, profile),
            "5-crawlee_adaptive": CrawleeStrategy(self.url_validator, profile),
            NOVNC_STRATEGY_NAME: NoVNCStrategy(),
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
        heavy_mode: bool,
        profile: str | None = None,
    ) -> dict[str, BaseStrategy]:
        strategies = self._build_strategies(profile)

        if ChallengeDetector.is_login_redirect_url(url):
            logger.warning(
                "WebReader: Pre-emptive URL redirect login detected on %s. Forcing NoVNC strategy.", url
            )
            return {NOVNC_STRATEGY_NAME: strategies[NOVNC_STRATEGY_NAME]}

        if heavy_mode:
            return {
                "4-playwright_stealth": strategies["4-playwright_stealth"],
                "5-crawlee_adaptive": strategies["5-crawlee_adaptive"],
                NOVNC_STRATEGY_NAME: strategies[NOVNC_STRATEGY_NAME],
            }

        return strategies

    @staticmethod
    def _budget_exceeded(started_at: float, name: str) -> bool:
        # NoVNC returns 428 immediately, so it is exempt from the wall-clock budget.
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

    async def read(
        self,
        url: str,
        heavy_mode: bool = False,
        profile: str | None = None,
    ) -> dict[str, Any]:
        logger.info("Reading URL: %s (heavy_mode: %s, profile: %s)", url, heavy_mode, profile)
        strategies_to_run = self._select_strategies(url, heavy_mode, profile)
        novnc_strategy = self._build_strategies(profile)[NOVNC_STRATEGY_NAME]
        started_at = time.perf_counter()
        budget_exhausted = False

        for name, strategy in strategies_to_run.items():
            if self._budget_exceeded(started_at, name):
                budget_exhausted = True
                break

            result = await self._execute_strategy(name, strategy, url, novnc_strategy=novnc_strategy)
            if result:
                return result

        return self._create_failure_response(url, budget_exhausted=budget_exhausted)

    async def read_with_links(
        self,
        url: str,
        link_filter: str | None = None,
        heavy_mode: bool = False,
        profile: str | None = None,
    ) -> dict[str, Any]:
        logger.info("Reading URL with links: %s (heavy_mode: %s, profile: %s)", url, heavy_mode, profile)
        strategies_to_run = self._select_strategies(url, heavy_mode, profile)
        novnc_strategy = self._build_strategies(profile)[NOVNC_STRATEGY_NAME]
        started_at = time.perf_counter()
        budget_exhausted = False

        for name, strategy in strategies_to_run.items():
            if self._budget_exceeded(started_at, name):
                budget_exhausted = True
                break

            html = await self._execute_html_strategy(name, strategy, url, novnc_strategy=novnc_strategy)
            if html:
                content, links = annotate_links(html, url, link_filter)
                if self.validator.validate(content):
                    return {"content": content, "links": links, "status": "success", "mode": name}

                logger.info("Strategy %s validation failed after annotation.", name)

        return self._create_failure_response(url, budget_exhausted=budget_exhausted)

    async def _execute_strategy(
        self,
        name: str,
        strategy: BaseStrategy,
        url: str,
        escalating: bool = False,
        novnc_strategy: BaseStrategy | None = None,
    ) -> dict[str, Any] | None:
        started = time.perf_counter()

        try:
            logger.info("--- Strategy %s STARTED ---", name)
            content = await strategy.extract(url)
            if self.validator.validate(content):
                STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="success").inc()
                STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)

                return {"content": content, "status": "success", "mode": name}

            STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="validation_failed").inc()
            STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)

            logger.info("Strategy %s validation failed.", name)

            return None
        except ChallengeDetectedException:
            STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="challenge_detected").inc()
            STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)

            if escalating:
                logger.exception(
                    "Strategy %s raised ChallengeDetectedException during escalation. "
                    "Aborting to avoid recursion.",
                    name,
                )

                return None

            logger.warning("Strategy %s tripped early circuit breaker. Aborting to NoVNC for %s.", name, url)

            _novnc = novnc_strategy or self._build_strategies()[NOVNC_STRATEGY_NAME]
            return await self._execute_strategy(
                NOVNC_STRATEGY_NAME, _novnc, url, escalating=True
            )
        except HumanInterventionRequiredException:
            STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="human_intervention").inc()
            STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)
            raise
        except Exception as e:
            STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="exception").inc()
            STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)

            logger.warning("Strategy %s failed for %s: %s", name, url, e)

            return None

    async def _execute_html_strategy(
        self,
        name: str,
        strategy: BaseStrategy,
        url: str,
        escalating: bool = False,
        novnc_strategy: BaseStrategy | None = None,
    ) -> str:
        started = time.perf_counter()

        try:
            logger.info("--- Strategy %s STARTED ---", name)
            html = await strategy.get_html(url)
            if html:
                STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="success").inc()
                STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)

                return html

            STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="empty").inc()
            STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)

            logger.info("Strategy %s returned empty HTML.", name)
        except HumanInterventionRequiredException:
            STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="human_intervention").inc()
            STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)
            raise
        except ChallengeDetectedException:
            STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="challenge_detected").inc()
            STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)

            if escalating:
                logger.exception(
                    "Strategy %s raised ChallengeDetectedException during escalation. "
                    "Aborting to avoid recursion.",
                    name,
                )

                return ""

            logger.warning("Strategy %s tripped early circuit breaker. Aborting to NoVNC for %s.", name, url)

            _novnc = novnc_strategy or self._build_strategies()[NOVNC_STRATEGY_NAME]
            return await self._execute_html_strategy(
                NOVNC_STRATEGY_NAME, _novnc, url, escalating=True
            )
        except Exception as e:
            STRATEGY_ATTEMPTS_TOTAL.labels(strategy=name, outcome="exception").inc()
            STRATEGY_DURATION_SECONDS.labels(strategy=name).observe(time.perf_counter() - started)

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
