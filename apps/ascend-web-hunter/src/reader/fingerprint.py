from dataclasses import dataclass

from playwright.async_api import Geolocation


@dataclass(frozen=True)
class Fingerprint:
    """Internally consistent browser identity for a single synthetic persona.

    Every browser-based tier (Playwright, Crawlee, NoVNC) must receive the
    same Fingerprint instance so locale, timezone, geolocation, and UA never
    contradict each other — a mismatch is a bot-detection signal.
    """

    user_agent: str
    locale: str
    timezone_id: str
    geolocation: Geolocation
    viewport_width: int
    viewport_height: int


# One built-in persona: New York, English, Chrome on Windows.
# The locale, timezone, and geo all agree on the US Eastern seaboard.
_NEW_YORK_CHROME_WINDOWS = Fingerprint(
    user_agent=(
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    locale="en-US",
    timezone_id="America/New_York",
    geolocation=Geolocation(latitude=40.7128, longitude=-74.0060),
    viewport_width=1920,
    viewport_height=1080,
)


def get_default_fingerprint() -> Fingerprint:
    """Return the default coherent browser fingerprint."""
    return _NEW_YORK_CHROME_WINDOWS
