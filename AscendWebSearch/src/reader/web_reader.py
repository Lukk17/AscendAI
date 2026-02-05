import json
import logging
import random
from pathlib import Path
from typing import List, Dict, Any, Optional

from src.config.blocklist_loader import BlocklistLoader
from src.config.config import settings
from src.reader.strategies.base_strategy import BaseStrategy
from src.reader.strategies.crawlee_strategy import CrawleeStrategy
from src.reader.strategies.fallback_strategy import FallbackStrategy
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
            "1-trafilatura": TrafilaturaStrategy(self._get_random_user_agent),
            "2-playwright_stealth": PlaywrightStrategy(self._get_random_user_agent, self.url_validator),
            "3-crawlee_adaptive": CrawleeStrategy(self.url_validator),
            "4-fallback_beautifulsoup": FallbackStrategy(self._get_random_user_agent)
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

        for name, strategy in self.strategies.items():
            result = await self._execute_strategy(name, strategy, url)
            if result:
                return result

        return self._create_failure_response(url)

    async def _execute_strategy(self, name: str, strategy: BaseStrategy, url: str) -> Optional[Dict[str, Any]]:
        try:
            content = await strategy.extract(url)
            if self.validator.validate(content):
                return {"content": content, "status": "success", "method": name}

            logger.info(f"Strategy {name} validation failed.")
            return None

        except Exception as e:
            logger.warning(f"Strategy {name} failed for {url}: {e}")
            return None

    def _create_failure_response(self, url: str) -> Dict[str, Any]:
        return {"content": "", "status": "error", "error": f"All extraction methods failed for {url}"}
