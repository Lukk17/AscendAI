import json
import logging
from typing import Dict, Any, Optional
from urllib.parse import urlparse

import redis.asyncio as redis

from src.config.config import settings

logger = logging.getLogger(__name__)


class CookieManager:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(CookieManager, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self.redis_client = None
        if settings.REDIS_URL:
            try:
                self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
                logger.info("CookieManager connected to Redis")
            except Exception as e:
                self._handle_error("Failed to connect to Redis for CookieManager", e)

        self._memory_store: Dict[str, Dict[str, Any]] = {}
        self._initialized = True

    def _handle_error(self, message: str, error: Exception) -> None:
        logger.warning(f"{message}: {error}")

    def _get_domain(self, url: str) -> str:
        parsed = urlparse(url)
        domain = parsed.netloc if parsed.netloc else parsed.path.split('/')[0]
        return domain.lower()

    async def get_clearance_data(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Returns a dict containing 'cookies' (dict) and 'user_agent' (str) if available.
        """
        domain = self._get_domain(url)

        if self.redis_client:
            try:
                data = await self.redis_client.get(f"cf_clearance:{domain}")
                if data:
                    return json.loads(data)
            except Exception as e:
                self._handle_error("Failed to get clearance data from Redis", e)

        return self._memory_store.get(domain)

    async def save_clearance_data(self, url: str, cookies: Dict[str, str], user_agent: str,
                                  ttl_seconds: int = 7200) -> None:
        """
        Saves clearance cookies and the exact User-Agent used to acquire them.
        """
        domain = self._get_domain(url)
        payload = {
            "cookies": cookies,
            "user_agent": user_agent
        }

        if self.redis_client:
            try:
                await self.redis_client.setex(
                    f"cf_clearance:{domain}",
                    ttl_seconds,
                    json.dumps(payload)
                )
                logger.info(f"Saved clearance data to Redis for {domain}")
                return
            except Exception as e:
                self._handle_error("Failed to save clearance data to Redis", e)

        self._memory_store[domain] = payload
        logger.info(f"Saved clearance data to memory for {domain}")


cookie_manager = CookieManager()
