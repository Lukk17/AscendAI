import re
from collections.abc import Iterator, Sequence
from dataclasses import replace
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from src.config.config import settings
from src.reader.cloudflare.challenge_signals import _CATALOGUE, ChallengeVerdict, as_login_verdict, assess

_LOGIN_REDIRECT_INDICATORS: tuple[str, ...] = ("?login", "continue=", "signin", "login=", "auth?")

_INPUT_TAG_START = re.compile(r"<input\b", re.IGNORECASE)

_PASSWORD_TYPE = re.compile(r"\btype\s*=\s*[\"']?password\b", re.IGNORECASE)

_TITLE_TAG_START = re.compile(r"<title", re.IGNORECASE)

_TITLE_TAG_CLOSE = re.compile(r"</title>", re.IGNORECASE)

_TAG_END = ">"


def _contains_whole_word(text: str, word: str) -> bool:
    """Return True when *word* appears as a whole word inside *text*."""
    return bool(re.search(rf"\b{re.escape(word)}\b", text))


def has_password_input(html_content: str) -> bool:
    """True when an input tag of html_content declares type password, read in one pass over the markup."""
    position = 0
    while (tag := _INPUT_TAG_START.search(html_content, position)) is not None:
        tag_end = html_content.find(_TAG_END, tag.end())
        attributes_end = len(html_content) if tag_end == -1 else tag_end
        if _PASSWORD_TYPE.search(html_content, tag.end(), attributes_end) is not None:
            return True
        if tag_end == -1:
            return False
        position = tag_end + 1

    return False


def _title_texts(markup: str) -> Iterator[str]:
    """Each title element's text in markup, read in one pass, stopping when no closing tag remains."""
    position = 0
    while (tag := _TITLE_TAG_START.search(markup, position)) is not None:
        tag_end = markup.find(_TAG_END, tag.end())
        if tag_end == -1:
            return
        closing = _TITLE_TAG_CLOSE.search(markup, tag_end + 1)
        if closing is None:
            return
        yield markup[tag_end + 1 : closing.start()]
        position = closing.end()


def _has_login_path(url: str) -> bool:
    segments = urlsplit(url).path.lower().split("/")

    return any(segment.split(".", 1)[0] in _CATALOGUE.login_path_segments for segment in segments)


def _has_return_parameter(url: str) -> bool:
    names = (name.casefold() for name, _ in parse_qsl(urlsplit(url).query, keep_blank_values=True))

    return any(name in _CATALOGUE.login_return_parameters for name in names)


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

        for title in _title_texts(prefix):
            title_text = title.strip().lower()
            for pattern in _CATALOGUE.login_title_patterns:
                if _contains_whole_word(title_text, pattern):
                    return True

        return False

    @staticmethod
    def is_login_landing(requested_url: str, final_url: str, html_content: str) -> bool:
        """True when a read of requested_url ended at final_url, a login path the read did not ask
        for, and a second login sign holds: a return address in the query of final_url, or a
        password input in html_content."""
        if not _has_login_path(final_url) or _has_login_path(requested_url):
            return False

        return _has_return_parameter(final_url) or has_password_input(
            html_content[: settings.CHALLENGE_SHAPE_MAX_BYTES]
        )

    @staticmethod
    def login_wall_verdict(
        verdict: ChallengeVerdict, html_content: str, *, requested_url: str, final_url: str
    ) -> ChallengeVerdict | None:
        """The login verdict a tier raises for html_content, or None when the page is
        no login wall. A read that landed on a login page (see is_login_landing) makes a
        login wall at any size, marked login_landing.
        A login title makes one unless the page has rich content or is larger than
        CHALLENGE_SHAPE_MAX_BYTES."""
        if ChallengeDetector.is_login_landing(requested_url, final_url, html_content):
            return replace(as_login_verdict(verdict), login_landing=True)
        if verdict.wall and verdict.intervention_type == "login":
            return verdict
        if len(html_content) > settings.CHALLENGE_SHAPE_MAX_BYTES:
            return None
        if not verdict.has_rich_content and ChallengeDetector.is_login_required(html_content):
            return as_login_verdict(verdict)

        return None

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
    def is_login_redirect_url(url: str) -> bool:
        """
        Pre-emptively checks if the URL itself is a redirect trap designed to force
        an authentication wall.
        """
        if not url:
            return False

        url_lower = url.lower()

        return any(indicator in url_lower for indicator in _LOGIN_REDIRECT_INDICATORS)
