import json
import logging
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.api.exceptions import CaptchaRequiredException
from src.config.blocklist_loader import BlocklistLoader
from src.config.config import settings
from src.reader.link_annotator import annotate_links
from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.fallback_strategy import FallbackStrategy
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
            "1-fallback_beautifulsoup": FallbackStrategy(self._get_random_user_agent),
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

    async def read(self, url: str) -> Dict[str, Any]:
        logger.info(f"Reading URL: {url}")

        try:
            for name, strategy in self.strategies.items():
                result = await self._execute_strategy(name, strategy, url)
                if result:
                    return result
        except CaptchaRequiredException as e:
            return {"status": "captcha_required", "vnc_url": e.vnc_url, "message": e.message}

        return self._create_failure_response(url)

    async def read_with_links(self, url: str, link_filter: str | None = None) -> Dict[str, Any]:
        logger.info(f"Reading URL with links: {url}")

        try:
            for name, strategy in self.strategies.items():
                html = await self._execute_html_strategy(name, strategy, url)
                if html:
                    content, links = annotate_links(html, url, link_filter)
                    return {"content": content, "links": links, "status": "success"}
        except CaptchaRequiredException as e:
            return {"status": "captcha_required", "vnc_url": e.vnc_url, "message": e.message}

        return self._create_failure_response(url)

    async def _execute_strategy(self, name: str, strategy: BaseStrategy, url: str) -> Optional[Dict[str, Any]]:
        try:
            content = await strategy.extract(url)
            if self.validator.validate(content):
                return {"content": content, "status": "success", "method": name}

            logger.info(f"Strategy {name} validation failed.")
            return None
        except CaptchaRequiredException:
            raise
        except Exception as e:
            logger.warning(f"Strategy {name} failed for {url}: {e}")
            return None

    async def _execute_html_strategy(self, name: str, strategy: BaseStrategy, url: str) -> str:
        try:
            html = await strategy.get_html(url)
            if html:
                return html
            logger.info(f"Strategy {name} returned empty HTML.")
        except CaptchaRequiredException:
            raise
        except Exception as e:
            logger.warning(f"Strategy {name} get_html failed for {url}: {e}")
        return ""

    def _create_failure_response(self, url: str) -> Dict[str, Any]:
        return {"content": "", "status": "error", "error": f"All extraction methods failed for {url}"}
