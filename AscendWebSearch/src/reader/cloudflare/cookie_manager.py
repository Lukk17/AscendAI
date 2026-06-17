import json
import logging
import time
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


def _is_waf_cookie(name: str) -> bool:
    """Return True for known short-lived WAF-clearance cookie names."""
    return name in {"cf_clearance", "__cf_bm", "_cfuvid"}


def _split_storage_state(
    storage_state: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Partition a full storage_state into auth vs WAF sub-states."""
    all_cookies: list[dict[str, Any]] = storage_state.get("cookies", [])
    origins: list[dict[str, Any]] = storage_state.get("origins", [])

    auth_cookies = [c for c in all_cookies if not _is_waf_cookie(c.get("name", ""))]
    waf_cookies = [c for c in all_cookies if _is_waf_cookie(c.get("name", ""))]

    auth_state: dict[str, Any] = {"cookies": auth_cookies, "origins": origins}
    waf_state: dict[str, Any] = {"cookies": waf_cookies, "origins": []}
    return auth_state, waf_state


def _merge_storage_states(
    auth_state: dict[str, Any] | None,
    waf_state: dict[str, Any] | None,
) -> dict[str, Any]:
    """Merge auth and WAF sub-states into a single Playwright storage_state dict."""
    cookies: list[dict[str, Any]] = []
    origins: list[dict[str, Any]] = []

    if auth_state:
        cookies.extend(auth_state.get("cookies", []))
        origins.extend(auth_state.get("origins", []))
    if waf_state:
        cookies.extend(waf_state.get("cookies", []))

    return {"cookies": cookies, "origins": origins}


def _extract_flat_cookies(storage_state: dict[str, Any]) -> dict[str, str]:
    """Return a name→value dict from a storage_state for use in HTTP headers."""
    return {c["name"]: c["value"] for c in storage_state.get("cookies", []) if "name" in c and "value" in c}


class CookieManager:
    _instance: "CookieManager | None" = None
    _initialized: bool

    def __new__(cls, *args: Any, **kwargs: Any) -> "CookieManager":  # noqa: ARG004
        if cls._instance is None:
            instance = super().__new__(cls)
            instance._initialized = False
            cls._instance = instance

        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return

        self.redis_client: redis.Redis | None = None
        if settings.REDIS_URL:
            try:
                self.redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
                logger.info("[CookieManager] Redis backend configured")
            except Exception as e:
                logger.warning(
                    "[CookieManager] Redis configured but unreachable (%s); using in-memory fallback", e
                )

        if self.redis_client is None and settings.REDIS_URL:
            logger.info("[CookieManager] configured, using in-memory fallback")

        self._memory_store: dict[str, dict[str, Any]] = {}
        self._initialized = True

    @staticmethod
    def _handle_error(message: str, error: Exception) -> None:
        logger.warning("%s: %s", message, error)

    @staticmethod
    def _get_domain(url: str) -> str:
        parsed = urlparse(url)
        host = parsed.netloc or urlparse(f"//{url}", scheme="http").netloc or url.split("/", 1)[0]
        host = host.lower().split(":", 1)[0]
        if not host or "/" in host:
            return ""

        extracted = _TLD_EXTRACT(host)
        if extracted.domain and extracted.suffix:
            return f"{extracted.domain}.{extracted.suffix}"

        return host

    @staticmethod
    def _redis_key(domain: str, profile: str) -> str:
        return f"session:{domain}:{profile}"

    @staticmethod
    def _memory_key(domain: str, profile: str) -> str:
        return f"{domain}:{profile}"

    async def get_storage_state(
        self,
        url: str,
        profile: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a merged Playwright storage_state for the given URL + profile, or None."""
        domain = self._get_domain(url)
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        record = await self._load_record(domain, effective_profile)
        if record is None:
            return None

        now = time.time()
        auth_entry = record.get("auth")
        waf_entry = record.get("waf")

        auth_state: dict[str, Any] | None = None
        waf_state: dict[str, Any] | None = None

        if auth_entry and (now - auth_entry.get("saved_at", 0)) < settings.SESSION_AUTH_TTL_SECONDS:
            auth_state = auth_entry.get("storage_state")
        if waf_entry and (now - waf_entry.get("saved_at", 0)) < settings.SESSION_WAF_TTL_SECONDS:
            waf_state = waf_entry.get("storage_state")

        if auth_state is None and waf_state is None:
            return None

        return _merge_storage_states(auth_state, waf_state)

    async def get_flat_cookies(
        self,
        url: str,
        profile: str | None = None,
    ) -> dict[str, str]:
        """Return a name→value cookie dict suitable for HTTP request headers."""
        state = await self.get_storage_state(url, profile)
        if state is None:
            return {}
        return _extract_flat_cookies(state)

    async def get_user_agent(
        self,
        url: str,
        profile: str | None = None,
    ) -> str | None:
        """Return stored user-agent for this domain/profile, or None."""
        domain = self._get_domain(url)
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        record = await self._load_record(domain, effective_profile)
        if record is None:
            return None
        auth_entry = record.get("auth") or record.get("waf")
        if auth_entry:
            user_agent = auth_entry.get("user_agent")
            return user_agent if isinstance(user_agent, str) else None
        return None

    async def save_storage_state(
        self,
        url: str,
        storage_state: dict[str, Any],
        user_agent: str,
        profile: str | None = None,
    ) -> None:
        """Persist a full Playwright storage_state, split into auth/WAF sub-records."""
        domain = self._get_domain(url)
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        auth_state, waf_state = _split_storage_state(storage_state)
        now = time.time()

        record: dict[str, Any] = {}
        existing = await self._load_record(domain, effective_profile)
        if existing:
            record = dict(existing)

        record["auth"] = {
            "storage_state": auth_state,
            "user_agent": user_agent,
            "saved_at": now,
        }
        if waf_state["cookies"]:
            record["waf"] = {
                "storage_state": waf_state,
                "user_agent": user_agent,
                "saved_at": now,
            }

        await self._save_record(domain, effective_profile, record)

    async def slide_auth_ttl(
        self,
        url: str,
        profile: str | None = None,
    ) -> None:
        """Slide the auth TTL on a successful authenticated read."""
        domain = self._get_domain(url)
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        record = await self._load_record(domain, effective_profile)
        if record is None or "auth" not in record:
            return

        record["auth"]["saved_at"] = time.time()
        await self._save_record(domain, effective_profile, record)

    async def get_auth_ttl_remaining(
        self,
        url: str,
        profile: str | None = None,
    ) -> float:
        """Return seconds remaining on the auth TTL, or 0 if expired/absent."""
        domain = self._get_domain(url)
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        record = await self._load_record(domain, effective_profile)
        if record is None or "auth" not in record:
            return 0.0
        auth_entry = record["auth"]
        saved_at = float(auth_entry.get("saved_at", 0) or 0)
        elapsed = time.time() - saved_at
        remaining = settings.SESSION_AUTH_TTL_SECONDS - elapsed
        return max(remaining, 0.0)

    # ---------------------------------------------------------------------------
    # Legacy compatibility: still used by FlareSolverrStrategy which receives a
    # flat cookie dict + user_agent from FlareSolverr's response.
    # ---------------------------------------------------------------------------
    async def save_flat_cookies(
        self,
        url: str,
        cookies: dict[str, str],
        user_agent: str,
        profile: str | None = None,
    ) -> None:
        """Convert a flat cookie dict to Playwright storage_state format and persist."""
        playwright_cookies = [
            {
                "name": name,
                "value": value,
                "domain": self._get_domain(url),
                "path": "/",
                "expires": -1,
                "httpOnly": False,
                "secure": url.startswith("https"),
                "sameSite": "Lax",
            }
            for name, value in cookies.items()
        ]
        storage_state: dict[str, Any] = {"cookies": playwright_cookies, "origins": []}
        await self.save_storage_state(url, storage_state, user_agent, profile)

    # ---------------------------------------------------------------------------
    # Backward compat alias used by the old get_session_data callers
    # ---------------------------------------------------------------------------
    async def get_session_data(
        self,
        url: str,
        profile: str | None = None,
    ) -> dict[str, Any] | None:
        """Legacy: return {cookies: dict, user_agent: str} or None.

        Kept so existing tests pass; new callers should use get_storage_state().
        """
        state = await self.get_storage_state(url, profile)
        if state is None:
            return None
        ua = await self.get_user_agent(url, profile)
        return {
            "cookies": _extract_flat_cookies(state),
            "user_agent": ua or "",
        }

    async def save_session_data(
        self,
        url: str,
        cookies: dict[str, str],
        user_agent: str,
        ttl_seconds: int = 7200,  # noqa: ARG002 - TTL now driven by auth/WAF split
        profile: str | None = None,
    ) -> None:
        """Legacy: accept flat cookie dict and persist via save_flat_cookies."""
        await self.save_flat_cookies(url, cookies, user_agent, profile)

    # ---------------------------------------------------------------------------
    # Internal storage helpers
    # ---------------------------------------------------------------------------
    async def _load_record(
        self,
        domain: str,
        profile: str,
    ) -> dict[str, Any] | None:
        if self.redis_client:
            try:
                raw = await self.redis_client.get(self._redis_key(domain, profile))
                if raw:
                    REDIS_OPS_TOTAL.labels(op="get", result="hit").inc()
                    loaded: dict[str, Any] = json.loads(raw)
                    return loaded
                REDIS_OPS_TOTAL.labels(op="get", result="miss").inc()
            except Exception as e:
                REDIS_OPS_TOTAL.labels(op="get", result="error").inc()
                self._handle_error("Failed to load session from Redis", e)

        return self._memory_store.get(self._memory_key(domain, profile))

    async def _save_record(
        self,
        domain: str,
        profile: str,
        record: dict[str, Any],
    ) -> None:
        if self.redis_client:
            try:
                await self.redis_client.setex(
                    self._redis_key(domain, profile),
                    settings.SESSION_AUTH_TTL_SECONDS,
                    json.dumps(record),
                )
                REDIS_OPS_TOTAL.labels(op="set", result="success").inc()
                logger.info("[CookieManager] Saved session to Redis for %s", domain)
                return
            except Exception as e:
                REDIS_OPS_TOTAL.labels(op="set", result="error").inc()
                self._handle_error("Failed to save session to Redis, falling back to memory", e)

        self._memory_store[self._memory_key(domain, profile)] = record
        logger.info("[CookieManager] Saved session to memory for %s", domain)


cookie_manager = CookieManager()
