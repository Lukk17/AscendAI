import json
import logging
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.api.exceptions import HumanInterventionRequiredException, ChallengeDetectedException
from src.config.blocklist_loader import BlocklistLoader
from src.config.config import settings
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


class WebReader:
    """
    Advanced WebReader Orchestrator.
    Manages multi-tier extraction strategies.
    dictates the execution order of strategies.
    """

    def __init__(self):
        self.validator = ContentValidator()
        self.user_agents = self._load_user_agents()

        blocklist_loader = BlocklistLoader()
        rules = blocklist_loader.load_rules()
        self.url_validator = URLValidator(rules)

        self.strategies: Dict[str, BaseStrategy] = {
            "1-beautifulsoup": BeautifulSoupStrategy(self._get_random_user_agent),
            "2-trafilatura": TrafilaturaStrategy(self._get_random_user_agent),
            "3-flaresolverr": FlareSolverrStrategy(),
            "4-playwright_stealth": PlaywrightStrategy(self._get_random_user_agent, self.url_validator),
            "5-crawlee_adaptive": CrawleeStrategy(self.url_validator),
            "6-novnc": NoVNCStrategy()
        }

    def _load_user_agents(self) -> List[str]:
        ua_path = Path(settings.USER_AGENTS_PATH)
        if ua_path.exists():
            return self._read_json_file(ua_path)
        return [settings.SEARXNG_USER_AGENT]

    def _read_json_file(self, path: Path) -> List[str]:
        try:
            with open(path, "r", encoding=settings.FILE_ENCODING) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load user agents: {e}")
            return [settings.SEARXNG_USER_AGENT]

    def _get_random_user_agent(self) -> str:
        return random.choice(self.user_agents)

    async def read(self, url: str, heavy_mode: bool = False) -> Dict[str, Any]:
        logger.info(f"Reading URL: {url} (heavy_mode: {heavy_mode})")

        strategies_to_run = self.strategies
        if ChallengeDetector.is_login_redirect_url(url):
            logger.warning(f"WebReader: Pre-emptive URL redirect login detected on {url}. Forcing NoVNC strategy.")
            strategies_to_run = {"6-novnc": self.strategies["6-novnc"]}
        elif heavy_mode:
            strategies_to_run = {
                "4-playwright_stealth": self.strategies["4-playwright_stealth"],
                "5-crawlee_adaptive": self.strategies["5-crawlee_adaptive"],
                "6-novnc": self.strategies["6-novnc"]
            }

        try:
            for name, strategy in strategies_to_run.items():
                result = await self._execute_strategy(name, strategy, url)
                if result:
                    return result
        except HumanInterventionRequiredException as e:
            return {"status": "human_intervention_required", "intervention_type": e.intervention_type,
                    "vnc_url": e.vnc_url, "message": e.message}

        return self._create_failure_response(url)

    async def read_with_links(self, url: str, link_filter: str | None = None, heavy_mode: bool = False) -> Dict[
        str, Any]:
        logger.info(f"Reading URL with links: {url} (heavy_mode: {heavy_mode})")

        strategies_to_run = self.strategies
        if ChallengeDetector.is_login_redirect_url(url):
            logger.warning(f"WebReader: Pre-emptive URL redirect login detected on {url}. Forcing NoVNC strategy.")
            strategies_to_run = {"6-novnc": self.strategies["6-novnc"]}
        elif heavy_mode:
            strategies_to_run = {
                "4-playwright_stealth": self.strategies["4-playwright_stealth"],
                "5-crawlee_adaptive": self.strategies["5-crawlee_adaptive"],
                "6-novnc": self.strategies["6-novnc"]
            }

        try:
            for name, strategy in strategies_to_run.items():
                html = await self._execute_html_strategy(name, strategy, url)
                if html:
                    content, links = annotate_links(html, url, link_filter)
                    return {"content": content, "links": links, "status": "success", "mode": name}
        except HumanInterventionRequiredException as e:
            return {"status": "human_intervention_required", "intervention_type": e.intervention_type,
                    "vnc_url": e.vnc_url, "message": e.message}

        return self._create_failure_response(url)

    async def _execute_strategy(self, name: str, strategy: BaseStrategy, url: str) -> Optional[Dict[str, Any]]:
        try:
            logger.info(f"--- Strategy {name} STARTED ---")
            content = await strategy.extract(url)
            if self.validator.validate(content):
                return {"content": content, "status": "success", "mode": name}

            logger.info(f"Strategy {name} validation failed.")
            return None
        except ChallengeDetectedException as e:
            logger.warning(f"Strategy {name} tripped early circuit breaker! Aborting direct to NoVNC for {url}.")
            return await self._execute_strategy("6-novnc", self.strategies["6-novnc"], url)
        except HumanInterventionRequiredException:
            raise
        except Exception as e:
            logger.warning(f"Strategy {name} failed for {url}: {e}")
            return None

    async def _execute_html_strategy(self, name: str, strategy: BaseStrategy, url: str) -> str:
        try:
            logger.info(f"--- Strategy {name} STARTED ---")
            html = await strategy.get_html(url)
            if html:
                return html
            logger.info(f"Strategy {name} returned empty HTML.")
        except ChallengeDetectedException as e:
            logger.warning(f"Strategy {name} tripped early circuit breaker! Aborting direct to NoVNC for {url}.")
            return await self._execute_html_strategy("6-novnc", self.strategies["6-novnc"], url)
        except HumanInterventionRequiredException:
            raise
        except Exception as e:
            logger.warning(f"Strategy {name} get_html failed for {url}: {e}")
        return ""

    def _create_failure_response(self, url: str) -> Dict[str, Any]:
        return {"content": "", "status": "error", "error": f"All extraction methods failed for {url}"}
