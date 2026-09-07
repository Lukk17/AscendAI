from unittest.mock import patch

import pytest

from src.reader.cloudflare.challenge_detector import ChallengeDetector


def test_is_blocked_no_content():
    assert ChallengeDetector.is_blocked(403, "") is True
    assert ChallengeDetector.is_blocked(429, "") is True
    assert ChallengeDetector.is_blocked(503, "") is True
    assert ChallengeDetector.is_blocked(200, "") is False


def test_is_blocked_large_content():
    large_html = "a" * 50001
    assert ChallengeDetector.is_blocked(403, large_html) is False


def test_is_blocked_keywords():
    html_with_keyword = "<html><body>Just a moment...</body></html>"
    assert ChallengeDetector.is_blocked(200, html_with_keyword) is True
    assert ChallengeDetector.is_blocked(403, html_with_keyword) is True


def test_is_blocked_ray_id():
    html_with_ray_id = "<html><body>Ray ID: 890123abc</body></html>"
    assert ChallengeDetector.is_blocked(200, html_with_ray_id) is True


def test_is_blocked_cf_tokens():
    html_turnstile = "<html><body><script src='cf-turnstile'></script></body></html>"
    assert ChallengeDetector.is_blocked(200, html_turnstile) is True

    html_clearance = "<html><body>Missing cf_clearance cookie</body></html>"
    assert ChallengeDetector.is_blocked(200, html_clearance) is True


def test_not_blocked():
    valid_html = "<html><body>Real website content without blocks</body></html>"
    assert ChallengeDetector.is_blocked(200, valid_html) is False


def test_is_login_required():
    assert (
        ChallengeDetector.is_login_required(
            "<html><head><title>Sign In | Indeed Accounts</title></head><body></body></html>",
        )
        is True
    )
    assert (
        ChallengeDetector.is_login_required(
            "<html><head><title>Log In | Example</title></head><body></body></html>",
        )
        is True
    )
    assert (
        ChallengeDetector.is_login_required(
            "<html><head><title>Welcome to the home page</title></head>"
            "<body>Sign in to continue</body></html>",
        )
        is False
    )
    assert (
        ChallengeDetector.is_login_required(
            "<html><head><title>Login - Portal</title></head><body>Enter your password</body></html>",
        )
        is True
    )
    assert ChallengeDetector.is_login_required("<html><body>Sign in to continue</body></html>") is False
    assert ChallengeDetector.is_login_required("<html><body>Enter your password</body></html>") is False
    assert (
        ChallengeDetector.is_login_required("<html><head><title>Welcome</title></head><body></body></html>")
        is False
    )


def test_is_login_required_ignores_login_substring_within_words():
    """Word-boundary match: 'sign in' must not fire on 'design industry'."""
    assert (
        ChallengeDetector.is_login_required(
            "<html><head><title>Web Design Industry News</title></head><body></body></html>",
        )
        is False
    )
    assert (
        ChallengeDetector.is_login_required(
            "<html><head><title>Sign in to your account</title></head><body></body></html>",
        )
        is True
    )


def test_is_login_required_svg_bypass():
    dirty_html = (
        "<html><body>"
        "<svg><title id='logo'>Indeed Logo</title></svg>"
        "<title dir='ltr'>Sign In | Indeed Accounts</title>"
        "</body></html>"
    )
    assert ChallengeDetector.is_login_required(dirty_html) is True


def test_is_blocked_returns_true_for_waf_script_signature():
    with patch(
        "src.reader.cloudflare.challenge_detector._BOT_DICT",
        {
            "waf_script_signatures": ["custom-waf-marker"],
            "waf_strict_phrases": [],
            "login_title_patterns": [],
        },
    ):
        html = "<html>custom-waf-marker</html>"
        assert ChallengeDetector.is_blocked(200, html) is True


def test_is_blocked_returns_true_for_waf_strict_phrase():
    with patch(
        "src.reader.cloudflare.challenge_detector._BOT_DICT",
        {
            "waf_script_signatures": [],
            "waf_strict_phrases": ["please verify you are human"],
            "login_title_patterns": [],
        },
    ):
        html = "<html><body>please verify you are human</body></html>"
        assert ChallengeDetector.is_blocked(200, html) is True


def test_is_blocked_returns_false_on_huge_content():
    huge = "a" * 50001
    assert ChallengeDetector.is_blocked(200, huge) is False


def test_is_login_required_returns_false_on_huge_content():
    huge = "a" * 50001
    assert ChallengeDetector.is_login_required(huge) is False


def test_is_login_redirect_url_empty_string_returns_false():
    assert ChallengeDetector.is_login_redirect_url("") is False


# noinspection PyTypeChecker
def test_is_login_redirect_url_none_returns_false():
    assert ChallengeDetector.is_login_redirect_url(None) is False  # type: ignore[arg-type]


def test_has_real_content_true_for_genuine_article():
    html = (
        "<html><body><article><p>"
        "This is a genuine paragraph of article content with more than ten words in it. "
        "It continues with a second sentence so the extractor has plenty of real prose."
        "</p></article></body></html>"
    )
    assert ChallengeDetector.has_real_content(html) is True


def test_has_real_content_false_for_empty_string():
    assert ChallengeDetector.has_real_content("") is False


def test_has_real_content_false_for_thin_interstitial():
    """A small page whose only text is a short interstitial paragraph (real content
    once boilerplate is stripped is near zero) must fail the positive-evidence check."""
    html = "<html><body><p>Please enable JS and disable any ad blocker</p></body></html>"
    assert ChallengeDetector.has_real_content(html) is False


def test_has_real_content_true_for_large_page_regardless_of_shape():
    """Pages at or above CHALLENGE_WALL_MAX_BYTES pass automatically: a genuine
    interstitial is small, so size alone rules it out."""
    huge = "a" * 50_000
    assert ChallengeDetector.has_real_content(huge) is True


def test_is_content_accepted_false_when_blocked_even_with_real_content():
    """A known block signature rejects the page even if it also contains
    enough words to otherwise pass the structural check."""
    html = (
        "<html><body>Just a moment... "
        + "This looks like plenty of real prose to satisfy a naive word count. " * 2
        + "</body></html>"
    )
    assert ChallengeDetector.is_content_accepted(200, html) is False


def test_is_content_accepted_false_for_unrecognized_thin_interstitial():
    """The Allegro regression: a DataDome block page carrying no literal
    'datadome' string and no cf_clearance/turnstile marker must still be
    rejected via the positive-evidence structural check."""
    html = (
        "<html lang='en'><head><title>allegro.pl</title></head>"
        "<body style='margin:0'><p id='cmsg'>Please enable JS and disable any ad blocker</p>"
        "<script data-cfasync='false'>var dd={'host':'geo.captcha-delivery.com'}</script></body></html>"
    )
    assert ChallengeDetector.is_content_accepted(200, html) is False


def test_is_content_accepted_false_for_amazon_style_interstitial():
    """Regression guard for a phrase-dictionary hit: an interstitial that renders
    the literal dictionary phrase must still be rejected."""
    html = (
        "<html><body><p>Sorry, we just need to make sure you're not a robot.</p>"
        "<a href='/errors/validateCaptcha'>Continue shopping</a></body></html>"
    )
    assert ChallengeDetector.is_content_accepted(200, html) is False


@pytest.mark.parametrize(
    ("locale", "heading", "button"),
    [
        ("pl", "Kliknij poniższy przycisk, aby kontynuować zakupy", "Kontynuuj zakupy"),
        ("com", "Click the button below to continue shopping", "Continue shopping"),
        ("co.uk", "Click the button below to continue shopping", "Continue shopping"),
        ("se", "Klicka på knappen nedan för att fortsätta handla", "Fortsätt handla"),
    ],
)
def test_is_content_accepted_false_for_real_amazon_captcha_page_any_locale(locale, heading, button):
    """The reported bug: Amazon's own captcha page carries no phrase from the
    dictionary in any locale, and its footer boilerplate (terms/privacy links,
    copyright line) alone is enough real prose to clear has_real_content's word
    count. Only the locale-independent structural marker (the fixed internal
    form action Amazon uses for this page in every locale) catches it. This
    fixture is a trimmed faithful copy of the real page fetched from
    amazon.{locale} on 2026-09-04, not a fixture engineered to match the
    dictionary."""
    html = (
        f"<html lang='{locale}'><head><title>Amazon.{locale}</title></head><body>"
        f"<div class='a-box a-alert a-alert-info'><h4>{heading}</h4></div>"
        "<form method='get' action='/errors_page/validateCaptcha' name=''>"
        f"<button type='submit'>{button}</button><button type='submit'>{button}</button>"
        "</form>"
        "<a href='/gp/help/customer/display.html?nodeId=508088'>Terms of Use &amp; Sale</a>"
        "<a href='/gp/help/customer/display.html?nodeId=468496'>Privacy Notice</a>"
        "<div>&#169; 1996-2025 Amazon.com, Inc. or its affiliates</div>"
        "</body></html>"
    )
    assert ChallengeDetector.has_real_content(html) is True, (
        "fixture must reproduce the original bug: footer boilerplate alone clears the word count"
    )
    assert ChallengeDetector.is_blocked(200, html) is True
    assert ChallengeDetector.is_content_accepted(200, html) is False


def test_is_blocked_returns_true_for_waf_structural_marker():
    with patch(
        "src.reader.cloudflare.challenge_detector._BOT_DICT",
        {
            "waf_script_signatures": [],
            "waf_strict_phrases": [],
            "waf_structural_markers": ["/errors_page/validateCaptcha"],
            "login_title_patterns": [],
        },
    ):
        html = "<html><body><form action='/errors_page/validateCaptcha'></form></body></html>"
        assert ChallengeDetector.is_blocked(200, html) is True


def test_is_content_accepted_true_for_real_datadome_rendered_page():
    """A DataDome-protected page that has actually cleared and serves full content
    must not be rejected merely for referencing DataDome infrastructure."""
    html = "<html><body>" + "real job listings " * 50 + "</body></html>"
    assert ChallengeDetector.is_content_accepted(200, html) is True


def test_is_login_redirect_url_matches_known_patterns():
    assert (
        ChallengeDetector.is_login_redirect_url(
            "https://secure.indeed.com/auth?continue=http://indeed.com/jobs"
        )
        is True
    )
    assert ChallengeDetector.is_login_redirect_url("https://example.com/login=true") is True
    assert ChallengeDetector.is_login_redirect_url("https://example.com?auth?data") is True
    assert ChallengeDetector.is_login_redirect_url("https://example.com/dashboard/settings") is False
