"""SessionManager: proactive session lifecycle for authenticated scraping.

Exposes three operations:
- establish(url, profile): open the NoVNC flow for a domain/profile on demand.
- status(url, profile): query auth TTL remaining, last-validated timestamp and
  how the last intervention window for the site and profile ended.
- validate(url, profile): probe whether the stored session is still live.

Complements the passive capture that happens inside NoVNCStrategy; callers
can pre-emptively establish a session before attempting a read.
"""

import logging
from dataclasses import dataclass
from typing import Literal

from src.config.config import settings
from src.observability.metrics import HUMAN_INTERVENTION_TOTAL
from src.observability.safe_address import address_without_query
from src.reader.cloudflare.cookie_manager import (
    cookie_manager,
    holds_login_state,
)
from src.reader.novnc.flow_registry import flow_key_for, novnc_flow_registry

logger = logging.getLogger(__name__)

SessionStatus = Literal["active", "expired", "none"]


class SessionInfo:
    """Value object returned by SessionManager.status()."""

    __slots__ = ("auth_ttl_remaining", "last_validated", "last_window", "profile", "status")

    def __init__(
        self,
        status: SessionStatus,
        auth_ttl_remaining: float,
        last_validated: float | None,
        profile: str,
        last_window: dict[str, object] | None = None,
    ) -> None:
        self.status: SessionStatus = status
        self.auth_ttl_remaining: float = auth_ttl_remaining
        self.last_validated: float | None = last_validated
        self.profile: str = profile
        self.last_window: dict[str, object] | None = last_window

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "auth_ttl_remaining_seconds": round(self.auth_ttl_remaining, 1),
            "last_validated": self.last_validated,
            "profile": self.profile,
            "last_window": self.last_window,
        }


@dataclass(frozen=True, slots=True)
class EstablishedFlow:
    """The intervention flow an establish call opened or joined."""

    vnc_url: str
    intervention_type: str
    flow_id: str | None
    joined: bool
    window: dict[str, int] | None


class SessionManager:
    """High-level session lifecycle manager.

    The low-level store is CookieManager; SessionManager adds the proactive
    establish/status/validate API on top.
    """

    async def establish(self, url: str, profile: str | None = None) -> EstablishedFlow:
        """Open or join the NoVNC login flow for *url* + *profile*.

        The browser monitor captures and persists the session once the human
        completes the login, under the requested profile.

        Raises:
            NoVNCFlowBusyException: when every local window slot is taken.
        """
        from src.api.exceptions import HumanInterventionRequiredException
        from src.reader.strategies.novnc_strategy import NoVNCStrategy

        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        strategy = NoVNCStrategy(effective_profile)
        try:
            await strategy.get_html(url, intervention_type="login")
        except HumanInterventionRequiredException as exc:
            HUMAN_INTERVENTION_TOTAL.labels(
                intervention_type=exc.intervention_type, joined=str(exc.joined).lower()
            ).inc()

            return EstablishedFlow(
                vnc_url=exc.vnc_url,
                intervention_type=exc.intervention_type,
                flow_id=exc.flow_id,
                joined=exc.joined,
                window=exc.window,
            )

        raise RuntimeError("NoVNC flow did not surface a VNC URL")

    async def status(self, url: str, profile: str | None = None) -> SessionInfo:
        """Return auth status for *url* + *profile*, with how its last intervention window ended."""
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        ttl_remaining = await cookie_manager.get_auth_ttl_remaining(url, effective_profile)
        last_result = await novnc_flow_registry.last_result(flow_key_for(url, effective_profile))
        last_window = last_result.to_dict() if last_result is not None else None

        if ttl_remaining <= 0:
            stored = await cookie_manager.has_session_record(url, effective_profile)
            auth_status: SessionStatus = "expired" if stored else "none"
            return SessionInfo(
                status=auth_status,
                auth_ttl_remaining=0.0,
                last_validated=None,
                profile=effective_profile,
                last_window=last_window,
            )

        last_validated = await cookie_manager.get_auth_saved_at(url, effective_profile)

        return SessionInfo(
            status="active",
            auth_ttl_remaining=ttl_remaining,
            last_validated=last_validated,
            profile=effective_profile,
            last_window=last_window,
        )

    async def clear(self, url: str, profile: str | None = None) -> bool:
        """Delete the stored session for *url* + *profile*.

        Idempotent: returns whether a record existed, but clearing an absent
        session is not an error and always succeeds.
        """
        effective_profile = profile or settings.SESSION_DEFAULT_PROFILE
        existed = await cookie_manager.clear_session(url, effective_profile)
        logger.info(
            "[SessionManager] Cleared session for %s (profile=%s, existed=%s)",
            address_without_query(url),
            effective_profile,
            existed,
        )

        return existed

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
            logger.info(
                "[SessionManager] Session expired for %s (profile=%s)",
                address_without_query(url),
                effective_profile,
            )
            return False

        state = await cookie_manager.get_storage_state(url, effective_profile)
        if state is None or not holds_login_state(state, cookie_manager.registrable_domain(url)):
            logger.info(
                "[SessionManager] No login state found for %s (profile=%s)",
                address_without_query(url),
                effective_profile,
            )
            return False

        await cookie_manager.slide_auth_ttl(url, effective_profile)
        logger.debug(
            "[SessionManager] Auth TTL slid for %s (profile=%s)",
            address_without_query(url),
            effective_profile,
        )
        return True


session_manager = SessionManager()
