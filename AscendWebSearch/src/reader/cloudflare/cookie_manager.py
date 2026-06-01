import json
import logging
from typing import Any
from urllib.parse import urlparse

import redis.asyncio as redis
import tldextract

from src.config.config import settings
from src.observability.metrics import REDIS_OPS_TOTAL

logger = logging.getLogger(__name__)


# suffix_list_urls=() disables remote PSL fetches and falls back to the bundled
# snapshot. cache_dir=None means in-memory only so we don't write to a default
# platform-dependent directory.
_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=(), cache_dir=None)


class CookieManager:
    _instance: "CookieManager | None" = None
    _initialized: bool

    # __new__ takes *args/**kwargs to swallow whatever __init__ receives — required
    # by the singleton pattern even though neither is used here.
    def __new__(cls, *args: Any, **kwargs: Any) -> "CookieManager":  # noqa: ARG004
        if cls._instance is None:
            instance = super().__new__(cls)
            # Singleton bootstrap: setting the private attribute on the freshly
            # constructed instance is the only safe place to do so before
            # __init__ runs. SLF001 is silenced for this exact reason.
            instance._initialized = False
            cls._instance = instance

        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.redis_client = None
        if settings.REDIS_URL:
            try:
                self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)

                logger.info("CookieManager connected to Redis")
            except Exception as e:
                self._handle_error("Failed to connect to Redis for CookieManager", e)

        self._memory_store: dict[str, dict[str, Any]] = {}
        self._initialized = True

    @staticmethod
    def _handle_error(message: str, error: Exception) -> None:
        logger.warning(f"{message}: {error}")

    @staticmethod
    def _get_domain(url: str) -> str:
        # PSL-aware registrable-domain extraction so that cookies set on
        # www.linkedin.com and login.linkedin.com hit linkedin.com, while
        # attacker.co.uk and victim.co.uk remain distinct keys (the naive
        # last-two-labels approach collapsed all *.co.uk into one bucket
        # and let one tenant overwrite another's cookies via NoVNC).
        parsed = urlparse(url)
        # Schemeless input (e.g. `evil.com/path`) lands in parsed.path as one string.
        # Re-parse with a synthetic scheme so we extract the host cleanly instead of
        # keying cookies under literal `evil.com/path`, which would create a parallel
        # poisoned bucket distinct from the legitimate `evil.com` entry.
        host = parsed.netloc or urlparse(f"//{url}", scheme="http").netloc or url.split("/", 1)[0]
        host = host.lower().split(":", 1)[0]
        if not host or "/" in host:
            return ""

        extracted = _TLD_EXTRACT(host)
        if extracted.domain and extracted.suffix:
            return f"{extracted.domain}.{extracted.suffix}"

        return host

    async def get_session_data(self, url: str) -> dict[str, Any] | None:
        domain = self._get_domain(url)

        if self.redis_client:
            try:
                data = await self.redis_client.get(f"session_cookies:{domain}")
                if data:
                    REDIS_OPS_TOTAL.labels(op="get", result="hit").inc()
                    parsed: dict[str, Any] = json.loads(data)

                    return parsed
                REDIS_OPS_TOTAL.labels(op="get", result="miss").inc()
            except Exception as e:
                REDIS_OPS_TOTAL.labels(op="get", result="error").inc()
                self._handle_error("Failed to get session data from Redis", e)

        return self._memory_store.get(domain)

    async def save_session_data(
        self,
        url: str,
        cookies: dict[str, str],
        user_agent: str,
        ttl_seconds: int = 7200,
    ) -> None:
        domain = self._get_domain(url)
        payload = {"cookies": cookies, "user_agent": user_agent}

        if self.redis_client:
            try:
                await self.redis_client.setex(
                    f"session_cookies:{domain}",
                    ttl_seconds,
                    json.dumps(payload),
                )
                REDIS_OPS_TOTAL.labels(op="set", result="success").inc()

                logger.info(f"Saved session data to Redis for {domain}")

                return
            except Exception as e:
                REDIS_OPS_TOTAL.labels(op="set", result="error").inc()
                self._handle_error("Failed to save session data to Redis", e)

        self._memory_store[domain] = payload

        logger.info(f"Saved session data to memory for {domain}")


cookie_manager = CookieManager()
