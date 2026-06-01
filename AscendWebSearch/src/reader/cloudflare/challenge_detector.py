import json
import re
from pathlib import Path

DICT_PATH = Path(__file__).parent / "challenge_dictionary.json"
try:
    with DICT_PATH.open(encoding="utf-8") as f:
        _BOT_DICT = json.load(f)
except Exception:
    _BOT_DICT = {
        "waf_script_signatures": [],
        "waf_strict_phrases": [],
        "login_title_patterns": [],
    }


class ChallengeDetector:
    @staticmethod
    def is_blocked(status_code: int, html_content: str) -> bool:
        """
        Checks if the response indicates a WAF/Cloudflare block.
        """
        if not html_content:
            return status_code in (403, 429, 503)

        if len(html_content) > 50000:
            return False

        for signature in _BOT_DICT.get("waf_script_signatures", []):
            if signature in html_content:
                return True

        for phrase in _BOT_DICT.get("waf_strict_phrases", []):
            if phrase in html_content:
                return True

        if re.search(r"Ray ID: \w+", html_content, re.IGNORECASE):
            return True

        if "cf-turnstile" in html_content:
            return True

        return "cf_clearance" in html_content

    @staticmethod
    def is_login_required(url: str, html_content: str) -> bool:  # noqa: ARG004
        """
        Checks if the response HTML title indicates an authentication wall.
        """
        if not html_content:
            return False

        if len(html_content) > 50000:
            return False

        title_matches = re.finditer(r"<title[^>]*>(.*?)</title>", html_content, re.IGNORECASE | re.DOTALL)
        for match in title_matches:
            title_text = match.group(1).strip().lower()
            for pattern in _BOT_DICT.get("login_title_patterns", []):
                if pattern in title_text:
                    return True

        return False

    @staticmethod
    def is_login_redirect_url(url: str) -> bool:
        """
        Pre-emptively checks if the URL itself is a redirect trap designed to force
        an authentication wall.
        """
        if not url:
            return False

        url_lower = url.lower()
        redirect_indicators = ["?login", "continue=", "signin", "login=", "auth?"]

        return any(indicator in url_lower for indicator in redirect_indicators)
