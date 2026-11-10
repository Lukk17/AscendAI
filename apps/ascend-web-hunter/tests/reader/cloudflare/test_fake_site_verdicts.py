"""Unit verdicts for the shared fake-site challenge pages (task 11.12).

Runs assess over every file of e2e/fake-site/pages/ with its served status
and headers, and asserts the verdict of task 11.8: the wall pages score a
wall (with the intervention type task 11.8 names where it names one) and the
content pages do not. A page that flips to the other verdict fails here
before any container starts.
"""

from pathlib import Path

import pytest
import trafilatura

from src.config.config import settings
from src.reader.cloudflare.challenge_signals import assess

_PAGES_DIR = Path(__file__).resolve().parents[3] / "e2e" / "fake-site" / "pages"

# File name to the (status, headers) app.py serves it with.
_SERVING: dict[str, tuple[int, dict[str, str]]] = {
    "wall-ko.html": (200, {}),
    "wall-tr.html": (200, {}),
    "wall-vendor-thin.html": (200, {}),
    "wall-header.html": (403, {"cf-mitigated": "challenge"}),
    "wall-oversized.html": (200, {}),
    "captcha-wall.html": (200, {}),
    "article-ja.html": (200, {}),
    "article-ar.html": (200, {}),
    "prose-captcha.html": (200, {}),
    "rich-403.html": (403, {}),
    "turnstile-wall.html": (200, {}),
}

# Wall file name to the intervention type task 11.8 names for it, if any.
_WALL: dict[str, str | None] = {
    "wall-ko.html": "captcha",
    "wall-tr.html": "login",
    "wall-vendor-thin.html": None,
    "wall-header.html": None,
    "wall-oversized.html": None,
    "turnstile-wall.html": None,
}

_CONTENT = [
    "captcha-wall.html",
    "article-ja.html",
    "article-ar.html",
    "prose-captcha.html",
    "rich-403.html",
]

_CANARIES: dict[str, str] = {
    "wall-ko.html": "로봇이 아님을 확인하십시오. 계속하려면 상자를 선택하십시오.",
    "wall-tr.html": "Giriş yapmak için kutuyu işaretleyin.",
    "wall-vendor-thin.html": "Loading, please wait.",
    "wall-header.html": "Full article text behind the wall.",
    "wall-oversized.html": "Type the letters shown in the image above to continue.",
    "captcha-wall.html": (
        "The QUARRY-THRUSH survey logged 47 nesting pairs along the basalt cliffs of Lake Mirell on June 9th."
    ),
    "article-ja.html": "QUARRY-THRUSHの調査で47組の営巣を確認した。",
    "article-ar.html": "سجل مسح QUARRY-THRUSH 47 زوجا معششا.",
    "prose-captcha.html": "The essay uses the word captcha only as prose.",
    "rich-403.html": "Long rich member article text.",
    "turnstile-wall.html": "Please confirm you are human to continue.",
}

_CANARY_WALL_WORDS = (
    "The QUARRY-THRUSH survey logged 47 nesting pairs along the basalt cliffs of Lake Mirell on June 9th."
)


def _html(name: str) -> str:
    # given
    return (_PAGES_DIR / name).read_text(encoding="utf-8")


def test_pages_folder_holds_exactly_the_served_pages() -> None:
    # given
    names = sorted(path.name for path in _PAGES_DIR.glob("*.html"))

    # when / then
    assert names == sorted(_SERVING)


@pytest.mark.parametrize("name", sorted(_WALL))
def test_wall_pages_score_wall(name: str) -> None:
    # given
    status, headers = _SERVING[name]

    # when
    verdict = assess(status, _html(name), headers)

    # then
    assert verdict.wall, f"{name} must score a wall, got score {verdict.score}"
    expected_type = _WALL[name]
    if expected_type is not None:
        assert verdict.intervention_type == expected_type


@pytest.mark.parametrize("name", _CONTENT)
def test_content_pages_score_no_wall(name: str) -> None:
    # given
    status, headers = _SERVING[name]

    # when
    verdict = assess(status, _html(name), headers)

    # then
    assert not verdict.wall, f"{name} must not score a wall, got score {verdict.score}"


@pytest.mark.parametrize("name", sorted(_CANARIES))
def test_every_page_carries_its_canary(name: str) -> None:
    # given / when / then
    assert _CANARIES[name] in _html(name), f"{name} lost its canary sentence"


def test_captcha_wall_counts_150_extracted_words() -> None:
    # given
    html = _html("captcha-wall.html")

    # when
    words = (trafilatura.extract(html) or "").split()

    # then
    assert _CANARY_WALL_WORDS in html
    assert len(words) >= settings.CHALLENGE_RICH_CONTENT_WORDS, (
        f"captcha-wall must extract at least 150 words, got {len(words)}"
    )


def test_wall_vendor_thin_names_the_datadome_script() -> None:
    # given
    html = _html("wall-vendor-thin.html")
    status, headers = _SERVING["wall-vendor-thin.html"]

    # when
    verdict = assess(status, html, headers)

    # then
    assert "js.datadome.co/tags.js" in html
    assert verdict.vendor == "datadome"
    assert verdict.wall


def test_wall_oversized_marker_sits_inside_the_scanned_prefix() -> None:
    # given
    html = _html("wall-oversized.html")
    status, headers = _SERVING["wall-oversized.html"]
    limit = settings.CHALLENGE_DETECTION_MAX_BYTES

    # when
    verdict = assess(status, html, headers)

    # then
    assert len(html.encode("utf-8")) > limit
    assert html.index("www.google.com/recaptcha/api.js") < limit
    assert verdict.wall
