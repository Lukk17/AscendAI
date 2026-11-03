"""Catalogued-widget pages with rich prose score content (spec 7 rows af-ah).

friendlycaptcha.com, mtcaptcha.com and hcaptcha.com each render a catalogue
widget beside hundreds of words of real prose. The live reads answered 428;
the intended verdict is 200 success, so the scored verdict must be content
with a margin, not balanced on the threshold.

The fixtures are the homepages as fetched on 2026-10-26 (one plain GET each
from a throwaway container): the friendlycaptcha.com homepage beside this
module, the mtcaptcha.com and hcaptcha.com homepages beside the challenge
corpus (same URLs, captured 2026-10-19). The rendered hCaptcha model adds
the hidden response textarea the widget injects into its in-prefix
placeholder, with the response headers and cookie names the live fetch
observed: that is the stack the browser tiers assess post-render, and it
scores exactly at the threshold before the guard moves.
"""

from pathlib import Path

import trafilatura

from src.reader.cloudflare.challenge_signals import assess

_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "widget_content"
_CORPUS = Path(__file__).resolve().parents[2] / "fixtures" / "challenge_walls"

# Response headers and cookie names of the kind the live fetch of hcaptcha.com
# observed (catalogue markers only: header names and cookie names, never
# values).
_HCAPTCHA_HEADERS = {"server": "cloudflare"}
_HCAPTCHA_COOKIES = ["__cf_bm"]

_WIDGET_PLACEHOLDER = '<div id="h-captcha" class="hcaptcha-beacon-home"></div>'
_WIDGET_RENDERED = (
    '<div id="h-captcha" class="hcaptcha-beacon-home">'
    '<textarea name="h-captcha-response" style="display:none"></textarea></div>'
)


def _rendered_hcaptcha() -> str:
    # given
    html = (_CORPUS / "vendor-content-hcaptcha.html").read_text(encoding="utf-8")

    # when
    assert _WIDGET_PLACEHOLDER in html[:50_000]

    # then
    return html.replace(_WIDGET_PLACEHOLDER, _WIDGET_RENDERED, 1)


def test_friendly_homepage_scores_content() -> None:
    # given
    html = (_FIXTURES / "friendlycaptcha-home.html").read_text(encoding="utf-8")

    # when
    verdict = assess(200, html)

    # then
    assert len((trafilatura.extract(html) or "").split()) >= 400
    assert verdict.wall is False
    assert verdict.accepted is True


def test_mtcaptcha_homepage_scores_content() -> None:
    # given
    html = (_CORPUS / "vendor-content-mtcaptcha.html").read_text(encoding="utf-8")

    # when
    verdict = assess(200, html)

    # then
    assert len((trafilatura.extract(html) or "").split()) >= 400
    assert "vendor_script" in [signal.id for signal in verdict.signals]
    assert verdict.wall is False
    assert verdict.accepted is True


def test_hcaptcha_homepage_scores_content() -> None:
    # given
    html = (_CORPUS / "vendor-content-hcaptcha.html").read_text(encoding="utf-8")

    # when
    verdict = assess(200, html)

    # then
    assert len((trafilatura.extract(html) or "").split()) >= 400
    assert "vendor_script" in [signal.id for signal in verdict.signals]
    assert verdict.wall is False
    assert verdict.accepted is True


def test_hcaptcha_rendered_widget_scores_content() -> None:
    # given
    html = _rendered_hcaptcha()

    # when
    verdict = assess(200, html, _HCAPTCHA_HEADERS, _HCAPTCHA_COOKIES)

    # then
    assert "captcha_input" in [signal.id for signal in verdict.signals]
    assert verdict.wall is False
    assert verdict.accepted is True
