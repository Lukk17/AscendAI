import logging
from typing import Any

from adblockparser import AdblockRules

from src.config.blocklist_loader import blocklist_loader

logger = logging.getLogger(__name__)


class URLValidator:
    def __init__(self, rules: AdblockRules) -> None:
        self.rules = rules

    def should_block(self, url: str) -> bool:
        result: bool = self.rules.should_block(url)
        return result

    async def route_handler(self, route: Any) -> None:
        url = route.request.url
        if self.should_block(url):
            await route.abort()
        else:
            await route.continue_()


# Process-wide singleton: every WebReader (REST and MCP) shares this one instance,
# so a successful POST /api/v1/blocklist/refresh -- which reassigns `.rules` below --
# is picked up by every consumer immediately, without needing to reach into each
# WebReader individually.
url_validator = URLValidator(blocklist_loader.load_rules())
