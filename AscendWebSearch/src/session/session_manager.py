"""SessionManager: proactive session lifecycle for authenticated scraping.

Exposes three operations:
- establish(url, profile): open the NoVNC flow for a domain/profile on demand.
- status(url, profile): query auth TTL remaining + last-validated timestamp.
- validate(url, profile): probe whether the stored session is still live.

Complements the passive capture that happens inside NoVNCStrategy; callers
can pre-emptively establish a session before attempting a read.
"""

import logging
from typing import Literal

from src.config.config import settings
from src.reader.cloudflare.cookie_manager import (
    cookie_manager,
)

logger = logging.getLogger(__name__)

SessionStatus = Literal["active", "expired", "none"]


class SessionInfo:
    """Value object returned by SessionManager.status()."""

    __slots__ = ("auth_ttl_remaining", "last_validated", "profile", "status")

    def __init__(
        self,
        status: SessionStatus,
        auth_ttl_remaining: float,
        last_validated: float | None,
        profile: str,
    ) -> None:
        self.status: SessionStatus = status
        self.auth_ttl_remaining: float = auth_ttl_remaining
        self.last_validated: float | None = last_validated
        self.profile: str = profile

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "auth_ttl_remaining_seconds": round(self.auth_ttl_remaining, 1),
            "last_validated": self.last_validated,
            "profile": self.profile,
        }


class SessionManager:
    """High-level session lifecycle manager.

    The low-level store is CookieManager; SessionManager adds the proactive
    establish/status/validate API on top.
    """

    async def establish(self, url: str, _profile: str | None = None) -> str:
        """Open the NoVNC flow for *url* and return the VNC URL.

        The browser monitor will capture and persist the session once the
        human completes the login/CAPTCHA.
        """
        from src.api.exceptions import HumanInterventionRequiredException
        from src.reader.strategies.novnc_strategy import NoVNCStrategy

        strategy = NoVNCStrategy()
        try:
            await strategy.get_html(url)
        except HumanInterventionRequiredException as exc:
            return exc.vnc_url

        raise RuntimeError("NoVNC flow did not surface a VNC URL")

    async def status(self, url: str, profile: str | None = None) -> SessionInfo:
        """Return auth status for *url* + *profile*."""
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        ttl_remaining = await cookie_manager.get_auth_ttl_remaining(url, effective_profile)

        if ttl_remaining <= 0:
            domain = cookie_manager._get_domain(url)  # noqa: SLF001
            record = await cookie_manager._load_record(domain, effective_profile)  # noqa: SLF001
            auth_status: SessionStatus = "none" if record is None else "expired"
            return SessionInfo(
                status=auth_status,
                auth_ttl_remaining=0.0,
                last_validated=None,
                profile=effective_profile,
            )

        domain = cookie_manager._get_domain(url)  # noqa: SLF001
        record = await cookie_manager._load_record(domain, effective_profile)  # noqa: SLF001
        last_validated: float | None = None
        if record and "auth" in record:
            last_validated = record["auth"].get("saved_at")

        return SessionInfo(
            status="active",
            auth_ttl_remaining=ttl_remaining,
            last_validated=last_validated,
            profile=effective_profile,
        )

    async def validate(self, url: str, profile: str | None = None) -> bool:
        """Check whether the stored session is still live.

        On success, slides the auth TTL.  On failure, returns False so the
        caller can report 'session_expired' rather than serving anonymous
        content as success.

        This is a lightweight TTL-based check; a full network probe would
        require knowing the site's logged-in indicator URL/selector.
        """
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        ttl_remaining = await cookie_manager.get_auth_ttl_remaining(url, effective_profile)
        if ttl_remaining <= 0:
            logger.info("[SessionManager] Session expired for %s (profile=%s)", url, effective_profile)
            return False

        state = await cookie_manager.get_storage_state(url, effective_profile)
        if state is None or not state.get("cookies"):
            logger.info("[SessionManager] No cookies found for %s (profile=%s)", url, effective_profile)
            return False

        await cookie_manager.slide_auth_ttl(url, effective_profile)
        logger.debug("[SessionManager] Auth TTL slid for %s (profile=%s)", url, effective_profile)
        return True


session_manager = SessionManager()
