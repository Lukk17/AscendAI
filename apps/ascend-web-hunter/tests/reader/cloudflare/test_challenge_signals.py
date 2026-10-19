"""Unit tests for the scored challenge verdict (tasks 3.1 to 3.4, 4.1 to 4.7, 5.1, 5.4).

Every signal is a pure function of status, headers, cookie names and the
prefix; the tests below pin one positive case per catalogue marker per vendor
with a near-miss negative, the once-per-verdict rule, the worked examples of
design Decision 2 at the default settings, and one boundary moved by an
override.
"""

from dataclasses import FrozenInstanceError
from typing import Any
from unittest.mock import patch

import lxml.html
import pytest

from src.reader.cloudflare.challenge_signals import (
    ChallengeVerdict,
    FiredSignal,
    assess,
    load_catalogue,
    normalise_phrase,
)


def _ids(verdict: ChallengeVerdict) -> list[str]:
    return [signal.id for signal in verdict.signals]


def _words(n: int, word: str = "lorem") -> str:
    return " ".join([word] * n)


def _pad(n: int = 25_000) -> str:
    return "<!-- " + "x" * n + " -->"


def test_normalisation_collapses_variants() -> None:
    # given
    variants = ["Just a moment...", "Just a moment...", "JUST A MOMENT"]

    # when
    normalised = {normalise_phrase(variant) for variant in variants}

    # then
    assert normalised == {"just a moment"}


def test_loader_normalises_with_the_matcher_function() -> None:
    # given
    import json
    from pathlib import Path

    raw = json.loads(Path("src/reader/cloudflare/challenge_dictionary.json").read_text(encoding="utf-8"))

    # when / then
    catalogue = load_catalogue()
    for phrase_id, entry in raw["phrases"].items():
        assert normalise_phrase(entry["en"]) in {
            normalise_phrase(entry["en"]),
            catalogue.phrases[phrase_id]["en"],
        }
        stored = catalogue.phrases[phrase_id]["en"]
        assert normalise_phrase(stored) == normalise_phrase(entry["en"])


def test_dataclasses_are_frozen() -> None:
    # given
    signal = FiredSignal(id="thin_text", family="shape", weight=20, vendor=None, evidence="words-per-kb")
    verdict = assess(200, "<html><body>hello world</body></html>")

    # when / then
    with pytest.raises(FrozenInstanceError):
        signal.weight = 99  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        verdict.wall = True  # type: ignore[misc]


def test_accepted_property() -> None:
    # given / when / then
    assert ChallengeVerdict(200, 100, (), None, True, True, "captcha").accepted is False
    assert ChallengeVerdict(0, 100, (), None, False, False, "captcha").accepted is False
    assert ChallengeVerdict(0, 100, (), None, False, True, "captcha").accepted is True


def test_set_cookie_names_from_mapping_and_combined() -> None:
    # given
    from src.reader.cloudflare.challenge_signals import set_cookie_names

    # when / then
    assert set_cookie_names({"set-cookie": "datadome=abc; Path=/"}) == ["datadome"]
    assert set_cookie_names({}) == []
    assert set_cookie_names(None) == []
    assert set_cookie_names({"set-cookie": "bare-name"}) == []


def test_set_cookie_names_from_get_list() -> None:
    # given
    from curl_cffi.requests import Headers

    from src.reader.cloudflare.challenge_signals import set_cookie_names

    # when
    names = set_cookie_names(Headers({"set-cookie": "datadome=abc; Path=/"}))

    # then
    assert names == ["datadome"]


def test_set_cookie_names_falls_back_when_get_list_raises() -> None:
    # given
    from src.reader.cloudflare.challenge_signals import set_cookie_names

    class _RaisingHeaders:
        def get_list(self, _name: str) -> list[str]:
            raise RuntimeError("no multiples")

        def get(self, _name: str) -> str | None:
            return "datadome=abc; Path=/"

    # when
    names = set_cookie_names(_RaisingHeaders())

    # then
    assert names == ["datadome"]


_DEFINITIVE_CASES = [
    ({"cf-mitigated": "challenge"}, "cloudflare"),
    ({"CF-MITIGATED": "challenge"}, "cloudflare"),
    ({"x-amzn-waf-action": "challenge"}, "aws_waf"),
    ({"x-amzn-waf-action": "captcha"}, "aws_waf"),
]


@pytest.mark.parametrize(("headers", "vendor"), _DEFINITIVE_CASES)
def test_definitive_header_fires_once(headers: dict[str, str], vendor: str) -> None:
    # given
    html = "<html><body>" + _words(200) + "</body></html>"

    # when
    verdict = assess(200, html, headers=headers)

    # then
    assert _ids(verdict).count("definitive_header") == 1
    assert verdict.wall is True
    assert verdict.vendor == vendor


def test_definitive_header_near_miss() -> None:
    # given
    html = "<html><body>hello world</body></html>"

    # when
    verdict = assess(200, html, headers={"cf-mitigated": "pass", "cf-mitigate": "challenge"})

    # then
    assert "definitive_header" not in _ids(verdict)


_PRESENCE_CASES = [
    ({"cf-ray": "abc"}, (), "cloudflare"),
    ({"server": "cloudflare"}, (), "cloudflare"),
    ({}, ("cf_clearance",), "cloudflare"),
    ({}, ("__cf_bm",), "cloudflare"),
    ({"x-dd-b": "1"}, (), "datadome"),
    ({}, ("datadome",), "datadome"),
    ({"server": "AkamaiGHost"}, (), "akamai"),
    ({}, ("_abck",), "akamai"),
    ({}, ("bm_sz",), "akamai"),
    ({}, ("ak_bmsc",), "akamai"),
    ({"x-iinfo": "1-2-3"}, (), "imperva"),
    ({"x-cdn": "Incapsula"}, (), "imperva"),
    ({}, ("incap_ses_123",), "imperva"),
    ({}, ("visid_incap_123",), "imperva"),
    ({"x-kpsdk-ct": "v"}, (), "kasada"),
    ({"x-kpsdk-cd": "v"}, (), "kasada"),
    ({}, ("_px3",), "perimeterx"),
    ({}, ("_px2",), "perimeterx"),
    ({"server": "ddos-guard"}, (), "ddos_guard"),
    ({}, ("__ddg1",), "ddos_guard"),
    ({}, ("__ddg2",), "ddos_guard"),
    ({}, ("__ddgid",), "ddos_guard"),
    ({}, ("__ddgmark",), "ddos_guard"),
    ({}, ("aws-waf-token",), "aws_waf"),
]


@pytest.mark.parametrize(("headers", "cookies", "vendor"), _PRESENCE_CASES)
def test_vendor_presence_fires_once(headers: dict[str, str], cookies: tuple[str, ...], vendor: str) -> None:
    # given
    html = "<html><body>hello world</body></html>"

    # when
    verdict = assess(200, html, headers=headers, cookie_names=list(cookies))

    # then
    assert _ids(verdict).count("vendor_presence") == 1
    assert verdict.vendor == vendor


_PRESENCE_NEAR_MISS = [
    ({"cfray": "abc"}, ()),
    ({"server": "cloudfront"}, ()),
    ({}, ("cf-clearance",)),
    ({}, ("data-dome",)),
    ({"x-dd-c": "1"}, ()),
    ({"server": "akamai-ghosted"}, ()),
    ({}, ("abck",)),
    ({"x-iinf": "1"}, ()),
    ({}, ("incap_sesx",)),
    ({"x-kpsdk-cx": "v"}, ()),
    ({}, ("_px4",)),
    ({"server": "ddos_guard"}, ()),
    ({}, ("aws-waf-toke",)),
]


@pytest.mark.parametrize(("headers", "cookies"), _PRESENCE_NEAR_MISS)
def test_vendor_presence_near_miss(headers: dict[str, str], cookies: tuple[str, ...]) -> None:
    # given
    html = "<html><body>hello world</body></html>"

    # when
    verdict = assess(200, html, headers=headers, cookie_names=list(cookies))

    # then
    assert "vendor_presence" not in _ids(verdict)


_SCRIPT_CASES = [
    ("<script src='https://challenges.cloudflare.com/turnstile/v0/api.js'></script>", "cloudflare"),
    ("<script src='https://js.datadome.co/tags.js'></script>", "datadome"),
    ("<script src='https://js.datadome.co/a.js'></script>", "datadome"),
    ("<script src='https://static.geetest.com/v4/gt4.js'></script>", "geetest"),
    ("<script src='https://gcaptcha4.geetest.com/load'></script>", "geetest"),
    (
        "<script src='https://gcaptcha4.geevisit.com/x'></script>"
        "<script src='https://gcaptcha4.gsensebot.com/x'></script>"
        "<script src='https://static.geevisit.com/x'></script>",
        "geetest",
    ),
    ("<script src='https://service.mtcaptcha.com/mtcv1/client/mtcaptcha.min.js'></script>", "mtcaptcha"),
    ("<script src='https://service2.mtcaptcha.com/load'></script>", "mtcaptcha"),
    ("<script src='https://cdn.example.com/widget.module.min.js'></script>", "friendly_captcha"),
    ("<script src='https://arkoselabs.com/v2/abc/api.js'></script>", "arkose"),
    ("<script src='https://client-api.arkoselabs.com/fc/api.js'></script>", "arkose"),
    ("<script src='https://js.hcaptcha.com/1/api.js'></script>", "hcaptcha"),
    ("<script src='https://www.google.com/recaptcha/api.js'></script>", "recaptcha"),
    ("<script src='https://www.google.com/recaptcha/enterprise.js'></script>", "recaptcha"),
    ("<script src='https://recaptcha.net/recaptcha/api.js'></script>", "recaptcha"),
    ("<script src='https://client.perimeterx.net/px.js'></script>", "perimeterx"),
    ("<script src='https://client.perimeterx.com/px.js'></script>", "perimeterx"),
]


@pytest.mark.parametrize(("snippet", "vendor"), _SCRIPT_CASES)
def test_vendor_script_fires_once_per_vendor(snippet: str, vendor: str) -> None:
    # given
    html = f"<html><body>{snippet}{snippet}</body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert _ids(verdict).count("vendor_script") == 1
    assert verdict.vendor == vendor


def test_vendor_script_near_miss() -> None:
    # given
    html = (
        "<html><body>"
        "<script src='https://js.datadome.com/tags.js'></script>"
        "<script src='https://challenges.cloudflare.com/turnstile/v0/api.j'></script>"
        "</body></html>"
    )

    # when
    verdict = assess(200, html)

    # then
    assert "vendor_script" not in _ids(verdict)


_INTERSTITIAL_CASES = [
    ("<div id='cf-challenge-running'></div>", "cloudflare"),
    ("<div id='cf-please-wait'></div>", "cloudflare"),
    ("<div class='challenge-spinner'></div>", "cloudflare"),
    ("<div id='trk_jschal_js'></div>", "cloudflare"),
    ("<div class='turnstile-wrapper'></div>", "cloudflare"),
    ("<div id='attack-box'></div>", "cloudflare"),
    ("<div id='ray_id'></div>", "cloudflare"),
    ("<div>Ray ID: 89abcdef0123</div>", "cloudflare"),
    ("<script>var dd={host:'geo.captcha-delivery.com'};</script>", "datadome"),
    ("<script src='https://cdn.example.com/_Incapsula_Resource?x=1'></script>", "imperva"),
    ("<div>incapsula incident id 123</div>", "imperva"),
    ("<div>powered by incapsula</div>", "imperva"),
    ("<div id='px-captcha'></div>", "perimeterx"),
    ("<a href='https://perimeterx.net/whywasiblocked'>x</a>", "perimeterx"),
    ("<a href='https://perimeterx.com/whywasiblocked'>x</a>", "perimeterx"),
    ("<form action='/errors/validateCaptcha'></form>", "amazon"),
    ("<form action='/errors_page/validateCaptcha'></form>", "amazon"),
    ("<img src='https://opfcaptcha-prod.s3.amazonaws.com/img.jpg'>", "amazon"),
    ("<form><input name='captchacharacters'></form>", "amazon"),
]


@pytest.mark.parametrize(("snippet", "vendor"), _INTERSTITIAL_CASES)
def test_interstitial_structure_markers(snippet: str, vendor: str) -> None:
    # given
    html = f"<html><body>{snippet}</body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert _ids(verdict).count("interstitial_structure") == 1
    assert verdict.vendor == vendor


_SIGNAL_NEAR_MISS_CASES = [
    ("<script src='https://static-geetest.com/v4/gt4.js'></script>", "vendor_script"),
    ("<script src='https://service.mtcaptcha.com/mtcv1/client/mtcaptcha.min.j'></script>", "vendor_script"),
    ("<script src='https://cdn.example.com/widget.module.min.j'></script>", "vendor_script"),
    ("<script src='https://arkoselabs.co/v2/abc/api.js'></script>", "vendor_script"),
    ("<script src='https://js.hcaptcha.com/1/api.j'></script>", "vendor_script"),
    ("<script src='https://www.google.com/recaptcha/api.j'></script>", "vendor_script"),
    ("<script src='https://client.perimeterx.ne/px.js'></script>", "vendor_script"),
    ("<form action='/errors/validateCaptch'></form>", "interstitial_structure"),
    ("<script src='https://cdn.example.com/_Incapsula_Resourc?x=1'></script>", "interstitial_structure"),
    ("<div id='px-captch'></div>", "interstitial_structure"),
    ("<a href='https://perimeterx.net/whywasiblocke'>x</a>", "interstitial_structure"),
    ("<script>var dd={host:'geo.captcha-delivery.co/'};</script>", "interstitial_structure"),
    ("<div>Ray ID xyz</div>", "interstitial_structure"),
]


@pytest.mark.parametrize(("snippet", "signal_id"), _SIGNAL_NEAR_MISS_CASES)
def test_signal_near_miss_per_vendor(snippet: str, signal_id: str) -> None:
    # given
    html = f"<html><body><p>hello world</p>{snippet}</body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert signal_id not in _ids(verdict)


def test_akamai_reference_gated_on_403() -> None:
    # given
    html = "<html><body><div>Reference #18.abc123def456789</div></body></html>"

    # when
    wall = assess(403, html)
    clean = assess(200, html)

    # then
    assert "interstitial_structure" in _ids(wall)
    assert wall.vendor == "akamai"
    assert "interstitial_structure" not in _ids(clean)


def test_once_per_verdict_rule() -> None:
    # given
    snippet = "<script src='https://www.google.com/recaptcha/api.js'></script>" * 2
    markers = "<div id='cf-challenge-running'></div><div id='ray_id'></div><div>Ray ID: 1</div>"
    html = f"<html><body>{snippet}{markers}</body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert _ids(verdict).count("vendor_script") == 1
    assert _ids(verdict).count("interstitial_structure") == 1


@pytest.mark.parametrize("headers", [{"CF-Mitigated": "challenge"}, {"cf-mitigated": "challenge"}])
def test_header_handling_case_insensitive(headers: dict[str, str]) -> None:
    # given
    html = "<html><body>hello world</body></html>"

    # when
    verdict = assess(200, html, headers=headers)

    # then
    assert "definitive_header" in _ids(verdict)
    assert verdict.wall is True


def test_header_map_none_behaves() -> None:
    # given
    html = "<html><body>hello world</body></html>"

    # when
    verdict = assess(200, html, headers=None, cookie_names=None)

    # then
    assert "definitive_header" not in _ids(verdict)
    assert "vendor_presence" not in _ids(verdict)


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (403, "", "status_empty_body"),
        (429, "", "status_empty_body"),
        (503, "", "status_empty_body"),
        (403, "x" * 100, "status_small_body"),
        (429, "x" * 100, "status_small_body"),
        (503, "x" * 100, "status_small_body"),
        (403, "x" * 50_000, "status_large_body"),
        (429, "x" * 50_000, "status_large_body"),
        (503, "x" * 50_000, "status_large_body"),
    ],
)
def test_status_signals(status: int, body: str, expected: str) -> None:
    # given
    html = f"<html><body>{body}</body></html>" if body else ""

    # when
    verdict = assess(status, html)

    # then
    assert expected in _ids(verdict)


@pytest.mark.parametrize("status", [403, 429, 503])
def test_empty_body_carries_definitive_weight(status: int) -> None:
    # when
    verdict = assess(status, "")

    # then
    assert verdict.wall is True
    assert verdict.has_content is False


@pytest.mark.parametrize("status", [200, 404])
def test_other_statuses_fire_no_status_signal(status: int) -> None:
    # when
    verdict = assess(status, "<html><body>" + "x" * 100 + "</body></html>")

    # then
    assert not [signal for signal in verdict.signals if signal.family == "http"]


@pytest.mark.parametrize("attr", ["name", "id", "autocomplete"])
def test_captcha_input_attributes(attr: str) -> None:
    # given
    html = f"<html><body><form><input {attr}='user-captcha-answer'></form></body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert "captcha_input" in _ids(verdict)


def test_captcha_input_textarea() -> None:
    # given
    html = "<html><body><form><textarea name='captcha_text'></textarea></form></body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert "captcha_input" in _ids(verdict)


@pytest.mark.parametrize(
    "snippet",
    [
        "<div class='my-captcha-box'></div>",
        "<div id='captcha-root'></div>",
        "<div class='geetest_holder'></div>",
        "<div class='frc-captcha'></div>",
        "<div class='g-recaptcha'></div>",
        "<img src='/captcha.jpg'>",
    ],
)
def test_captcha_element_attributes(snippet: str) -> None:
    # given
    html = f"<html><body>{snippet}</body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert "captcha_element" in _ids(verdict)


def test_plain_image_fires_no_captcha_element() -> None:
    # given
    html = "<html><body><p><img src='/logo.jpg' id='logo'></p></body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert "captcha_element" not in _ids(verdict)


def test_form_dominance_boundary() -> None:
    # given
    above = (
        f"<html><body><p>{_words(39, 'outside')}</p><form><p>{_words(61, 'inside')}</p></form></body></html>"
    )
    below = (
        f"<html><body><p>{_words(41, 'outside')}</p><form><p>{_words(59, 'inside')}</p></form></body></html>"
    )

    # when
    verdict_above = assess(200, above)
    verdict_below = assess(200, below)

    # then
    assert "form_dominance" in _ids(verdict_above)
    assert "form_dominance" not in _ids(verdict_below)


def test_script_only_body_with_and_without_noscript() -> None:
    # given
    words = _words(5)
    with_noscript = f"<html><body><p>{words}</p><script>var a=1;</script><noscript></noscript></body></html>"
    without_noscript = f"<html><body><p>{words}</p><script>var a=1;</script></body></html>"

    # when
    verdict_with = assess(200, with_noscript)
    verdict_without = assess(200, without_noscript)

    # then
    assert "script_only_body" in _ids(verdict_with)
    assert "script_only_body" not in _ids(verdict_without)


def test_script_only_body_meta_refresh() -> None:
    # given
    html = (
        "<html><head><meta name='x' content='y'>"
        "<meta http-equiv='refresh' content='0;url=/x'></head><body>hello</body></html>"
    )

    # when
    verdict = assess(200, html)

    # then
    assert "script_only_body" in _ids(verdict)


def test_login_type_when_password_dominates() -> None:
    # given
    form = f"<form>{_words(61, 'inside')}<input name='captcha'><input type='password' name='pw'></form>"
    html = (
        "<html><body>"
        + _pad()
        + "<div id='cf-challenge-running'></div>"
        + f"<p>{_words(39, 'outside')}</p>"
        + form
        + "</body></html>"
    )

    # when
    verdict = assess(200, html)

    # then
    assert verdict.wall is True
    assert verdict.intervention_type == "login"


def test_captcha_type_when_password_not_dominant() -> None:
    # given
    small = "<form>" + _words(10, "small") + "<input type='password' name='pw'></form>"
    big = f"<form>{_words(61, 'inside')}<input name='captcha'></form>"
    html = "<html><body>" + _pad() + "<div id='cf-challenge-running'></div>" + small + big + "</body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert verdict.wall is True
    assert verdict.intervention_type == "captcha"


def test_parse_failure_records_signal_and_others_run(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    def _raise(_prefix: str) -> Any:
        raise lxml.html.ParserError("empty")

    monkeypatch.setattr(lxml.html, "fromstring", _raise)
    body = _words(200)
    links = "".join(f"<a href='/x{i}'>l{i}</a>" for i in range(25))
    html = f"<html><body><article><p>{body}</p>{links}</article></body></html>"
    headers = {"cf-mitigated": "challenge"}

    # when
    verdict = assess(200, html, headers=headers)

    # then
    parsed = [signal for signal in verdict.signals if signal.id == "parse_failed"]
    assert len(parsed) == 1
    assert parsed[0].weight == 0
    assert verdict.wall is True
    assert verdict.has_content is True
    assert "definitive_header" in _ids(verdict)


def test_shape_boundaries() -> None:
    # given
    at_guard = "<html><body><article><p>" + _words(150) + "</p></article></body></html>"
    below_guard = "<html><body><article><p>" + _words(149) + "</p></article></body></html>"

    # when
    verdict_at = assess(200, at_guard)
    verdict_below = assess(200, below_guard)

    # then
    assert "rich_content" in _ids(verdict_at)
    assert "rich_content" not in _ids(verdict_below)


def test_link_count_boundaries() -> None:
    # given
    def _page(n: int) -> str:
        links = "".join(f"<a href='/x{i}'>l{i}</a>" for i in range(n))
        return f"<html><body><article><p>{_words(200)}</p>{links}</article></body></html>"

    # when
    few = assess(200, _page(4))
    enough = assess(200, _page(5))
    many = assess(200, _page(20))
    almost = assess(200, _page(19))

    # then
    assert "few_links" in _ids(few)
    assert "few_links" not in _ids(enough)
    assert "many_links" in _ids(many)
    assert "many_links" not in _ids(almost)


def test_thin_text_ratio_boundary() -> None:
    # given
    thin = "<html><body><div data-pad='" + "x" * 20_000 + "'><p>" + _words(20) + "</p></div></body></html>"
    dense = "<html><body><p>" + _words(40) + "</p></body></html>"

    # when
    verdict_thin = assess(200, thin)
    verdict_dense = assess(200, dense)

    # then
    assert "thin_text" in _ids(verdict_thin)
    assert "thin_text" not in _ids(verdict_dense)


def test_oversized_page_contributes_no_shape_and_passes_floor() -> None:
    # given
    html = "<html><body>" + "x" * 500_001 + "</body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert not [signal for signal in verdict.signals if signal.family == "shape"]
    assert verdict.has_content is True
    assert verdict.wall is False


def test_trafilatura_called_once_per_assess(monkeypatch: pytest.MonkeyPatch) -> None:
    # given
    import trafilatura

    calls: list[str] = []
    real_extract = trafilatura.extract

    def _counting(html: str, *args: Any, **kwargs: Any) -> Any:
        calls.append(html)
        return real_extract(html, *args, **kwargs)

    monkeypatch.setattr(trafilatura, "extract", _counting)

    # when
    assess(200, "<html><body><p>" + _words(30) + "</p></body></html>")

    # then
    assert len(calls) == 1


def test_phrase_title_fires_not_body() -> None:
    # given
    html = (
        "<html><head><title>Attention Required!</title></head><body><p>" + _words(10) + "</p></body></html>"
    )

    # when
    verdict = assess(200, html)

    # then
    assert "phrase_title" in _ids(verdict)
    assert "phrase_body" not in _ids(verdict)


def test_phrase_title_startswith() -> None:
    # given
    html = "<html><head><title>Attention Required! | Example</title></head><body></body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert "phrase_title" in _ids(verdict)


def test_polish_translation_fires() -> None:
    # given
    html = "<html><body><p>Potwierdź, że nie jesteś robotem</p></body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert "phrase_body" in _ids(verdict)


def test_article_quoting_phrase_with_guard_is_content() -> None:
    # given
    html = "<html><body><article><p>" + _words(200) + " Just a moment... </p></article></body></html>"

    # when
    verdict = assess(200, html)

    # then
    assert verdict.wall is False
    assert verdict.accepted is True


def test_definitive_header_beside_guards_is_wall() -> None:
    # given
    links = "".join(f"<a href='/x{i}'>l{i}</a>" for i in range(25))
    html = f"<html><body><article><p>{_words(200)}</p>{links}</article></body></html>"

    # when
    verdict = assess(200, html, headers={"cf-mitigated": "challenge"})

    # then
    assert verdict.wall is True
    assert "definitive_header" in _ids(verdict)
    assert "rich_content" in _ids(verdict)
    assert "many_links" in _ids(verdict)


_WORKED_EXAMPLES = [
    ("cloudflare-curl", 250, True),
    ("cloudflare-browser", 140, True),
    ("geetest-ko", 200, True),
    ("own-captcha-ja", 190, True),
    ("akamai-403", 220, True),
    ("kasada-429", 180, True),
    ("amazon-de", 250, True),
    ("blog-recaptcha", 70, False),
    ("wikipedia-ar", -80, False),
    ("login-tr", 190, True),
    ("notfound-de", 60, False),
    ("turnstile-thin", 160, True),
]


def _worked_page(name: str) -> tuple[int, str, dict[str, str]]:
    if name == "cloudflare-curl":
        links = "".join(f"<a href='/x{i}'>l{i}</a>" for i in range(6))
        return (
            403,
            f"<html><body><article><p>{_words(20)}</p>{links}</article></body></html>",
            {"cf-mitigated": "challenge"},
        )
    if name == "cloudflare-browser":
        return (
            200,
            (
                "<html><body><div id='cf-challenge-running'></div><p>three small words</p>"
                "<script>" + "x" * 3_000 + "</script></body></html>"
            ),
            {},
        )
    if name == "geetest-ko":
        return (
            200,
            (
                "<html><body>" + _pad() + "<script src='https://static.geetest.com/v4/gt4.js'></script>"
                "<div class='geetest_holder'></div><form>" + _words(40, "한국어") + "</form></body></html>"
            ),
            {},
        )
    if name == "own-captcha-ja":
        return (
            200,
            (
                "<html><body>"
                + _pad()
                + "<form><img src='/captcha.jpg'>"
                + f"<input name='captcha_answer'>{_words(40, '日本語')}</form></body></html>"
            ),
            {},
        )
    if name == "akamai-403":
        return (
            403,
            ("<html><body>" + _pad() + "<div>Reference #18.abc123def456789</div></body></html>"),
            {"server": "AkamaiGHost"},
        )
    if name == "kasada-429":
        return (
            429,
            (
                "<html><body>"
                + _pad(5_000)
                + f"<p>{_words(5)}</p><script>var a=1;</script><noscript></noscript></body></html>"
            ),
            {"x-kpsdk-ct": "v"},
        )
    if name == "amazon-de":
        links = "".join(f"<a href='/x{i}'>l{i}</a>" for i in range(6))
        return (
            200,
            (
                "<html><body>" + _pad() + "<form action='/errors/validateCaptcha'>"
                "<img src='https://opfcaptcha-prod.s3.amazonaws.com/img.jpg'>"
                + f"<input name='captchacharacters'>{_words(40, 'wort')}</form><p>{links}</p></body></html>"
            ),
            {},
        )
    if name == "blog-recaptcha":
        links = "".join(f"<a href='/x{i}'>l{i}</a>" for i in range(40))
        article = (
            "<html><body><article>"
            "<script src='https://www.google.com/recaptcha/api.js'></script>"
            "<div class='g-recaptcha'></div>"
            + f"<p>{_words(800)}</p>{links}"
            + "<form><input name='g-recaptcha-response'></form></article></body></html>"
        )
        return 200, article, {}
    if name == "wikipedia-ar":
        links = "".join(f"<a href='/x{i}'>l{i}</a>" for i in range(25))
        return 200, f"<html><body><main><p>{_words(200, 'مقالة')}</p>{links}</main></body></html>", {}
    if name == "login-tr":
        form = (
            "<form><img src='/captcha.jpg'>"
            + f"<input name='captcha_answer'><input type='password' name='pw'>{_words(40, 'Türkçe')}</form>"
        )
        return 200, "<html><body>" + _pad() + form + "</body></html>", {}
    if name == "notfound-de":
        return 404, "<html><body>" + _pad(20_000) + f"<p>{_words(30, 'Wort')}</p></body></html>", {}
    if name == "turnstile-thin":
        return (
            200,
            (
                "<html><body>"
                "<script src='https://challenges.cloudflare.com/turnstile/v0/api.js'></script>"
                "<div class='cf-turnstile'></div>"
                + _pad(60_000)
                + f"<p>{_words(100)}</p><a href='/a'>a</a><a href='/b'>b</a></body></html>"
            ),
            {},
        )
    raise AssertionError(f"unknown worked example {name}")


@pytest.mark.parametrize(("name", "score", "wall"), _WORKED_EXAMPLES)
def test_worked_examples(name: str, score: int, wall: bool) -> None:
    # given
    status, html, headers = _worked_page(name)

    # when
    verdict = assess(status, html, headers=headers)

    # then
    assert verdict.score == score, _ids(verdict)
    assert verdict.wall is wall
    assert verdict.threshold == 100


def test_moved_threshold_flips_boundary() -> None:
    # given
    status, html, headers = _worked_page("turnstile-thin")

    # when
    with patch("src.reader.cloudflare.challenge_signals.settings.CHALLENGE_SCORE_THRESHOLD", 200):
        verdict = assess(status, html, headers=headers)

    # then
    assert verdict.score == 160
    assert verdict.wall is False
