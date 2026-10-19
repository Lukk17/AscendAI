import re
from collections.abc import Sequence
from typing import Any

from src.config.config import settings
from src.reader.cloudflare.challenge_signals import _CATALOGUE, assess

_LOGIN_REDIRECT_INDICATORS: tuple[str, ...] = ("?login", "continue=", "signin", "login=", "auth?")


def _contains_whole_word(text: str, word: str) -> bool:
    """Return True when *word* appears as a whole word inside *text*."""
    return bool(re.search(rf"\b{re.escape(word)}\b", text))


class ChallengeDetector:
    @staticmethod
    def is_blocked(
        status_code: int,
        html_content: str,
        headers: Any | None = None,
        cookie_names: Sequence[str] | None = (),
    ) -> bool:
        """
        Read the shared verdict: a page is blocked when the scored verdict is a
        wall, whatever the threshold and weights currently say.
        """
        return assess(status_code, html_content, headers, cookie_names).wall

    @staticmethod
    def is_login_required(html_content: str) -> bool:
        """
        Checks if the response HTML title indicates an authentication wall.

        Scans a bounded prefix so large authenticated pages are not silently
        skipped by the old >50 000 byte short-circuit.
        """
        if not html_content:
            return False

        prefix = html_content[: settings.CHALLENGE_DETECTION_MAX_BYTES]

        title_matches = re.finditer(r"<title[^>]*>(.*?)</title>", prefix, re.IGNORECASE | re.DOTALL)
        for match in title_matches:
            title_text = match.group(1).strip().lower()
            for pattern in _CATALOGUE.login_title_patterns:
                if _contains_whole_word(title_text, pattern):
                    return True

        return False

    @staticmethod
    def has_real_content(html_content: str) -> bool:
        """
        Positive evidence that html_content is genuine content rather than a
        block/interstitial page: read the word floor of the shared verdict.
        """
        if not html_content:
            return False

        if len(html_content) >= settings.CHALLENGE_WALL_MAX_BYTES:
            return True

        return assess(200, html_content).has_content

    @staticmethod
    def is_content_accepted(
        status_code: int,
        html_content: str,
        headers: Any | None = None,
        cookie_names: Sequence[str] | None = (),
    ) -> bool:
        """
        Single shared decision point for whether html_content is acceptable as
        real content. Used both by the read pipeline before accepting a tier's
        output as success and by the NoVNC monitor before declaring a challenge
        cleared, so the two can never disagree about the same page. Requires
        both the absence of a wall verdict and positive evidence of real
        content, never the mere absence of a signal.
        """
        return assess(status_code, html_content, headers, cookie_names).accepted

    @staticmethod
    def is_login_redirect_url(url: str) -> bool:
        """
        Pre-emptively checks if the URL itself is a redirect trap designed to force
        an authentication wall.
        """
        if not url:
            return False

        url_lower = url.lower()

        return any(indicator in url_lower for indicator in _LOGIN_REDIRECT_INDICATORS)
