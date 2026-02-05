import logging

from adblockparser import AdblockRules

logger = logging.getLogger(__name__)


class URLValidator:
    def __init__(self, rules: AdblockRules):
        self.rules = rules

    def should_block(self, url: str) -> bool:
        return self.rules.should_block(url)

    async def route_handler(self, route) -> None:
        url = route.request.url
        if self.should_block(url):
            await route.abort()
        else:
            await route.continue_()
