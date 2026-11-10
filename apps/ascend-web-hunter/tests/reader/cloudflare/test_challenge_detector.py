from typing import Any
from unittest.mock import patch

import pytest

from src.config.config import settings
from src.reader.cloudflare.challenge_detector import ChallengeDetector
from src.reader.cloudflare.challenge_signals import ChallengeVerdict, FiredSignal, assess


def test_is_blocked_no_content() -> None:
    # when / then
    assert ChallengeDetector.is_blocked(403, "") is True
    assert ChallengeDetector.is_blocked(429, "") is True
    assert ChallengeDetector.is_blocked(503, "") is True
    assert ChallengeDetector.is_blocked(200, "") is False


def test_is_blocked_large_content() -> None:
    # given
    large_html = "a" * 50001

    # when / then
    assert ChallengeDetector.is_blocked(403, large_html) is False


def test_is_blocked_keywords() -> None:
    """New expectation under the scored verdict: a bare title-only catalogue phrase
    (cf_just_a_moment matches titles, not bodies) in a body of a few bytes fires
    no signal, so the page is content, whatever the status."""
    # given
    html_with_keyword = "<html><body>Just a moment...</body></html>"

    # when / then
    assert ChallengeDetector.is_blocked(200, html_with_keyword) is False
    assert ChallengeDetector.is_blocked(403, html_with_keyword) is False


def test_is_blocked_ray_id() -> None:
    # given
    html_with_ray_id = "<html><body>Ray ID: 890123abc</body></html>"

    # when / then
    assert ChallengeDetector.is_blocked(200, html_with_ray_id) is True


def test_is_blocked_cf_tokens() -> None:
    """New expectation under the scored verdict: a script whose src carries the
    catalogue cf-turnstile marker still fires captcha_element with no size gate,
    so the widget-only interstitial is a wall."""
    # given
    html_turnstile = "<html><body><script src='cf-turnstile'></script></body></html>"

    # when / then
    assert ChallengeDetector.is_blocked(200, html_turnstile) is True


def test_body_mention_of_cookie_name_is_not_vendor_presence() -> None:
    """New expectation under the scored verdict: vendor_presence reads response
    headers and cookie names, so a body-text mention of cf_clearance fires no
    signal and the page is content."""
    # given
    html_clearance = "<html><body>Missing cf_clearance cookie</body></html>"

    # when / then
    assert ChallengeDetector.is_blocked(200, html_clearance) is False


def test_not_blocked() -> None:
    # given
    valid_html = "<html><body>Real website content without blocks</body></html>"

    # when / then
    assert ChallengeDetector.is_blocked(200, valid_html) is False


def test_is_login_required_empty_string_returns_false() -> None:
    # when / then
    assert ChallengeDetector.is_login_required("") is False


def test_is_login_required() -> None:
    # when / then
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


def test_is_login_required_ignores_login_substring_within_words() -> None:
    """Word-boundary match: 'sign in' must not fire on 'design industry'."""
    # when / then
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


def test_is_login_required_svg_bypass() -> None:
    # given
    dirty_html = (
        "<html><body>"
        "<svg><title id='logo'>Indeed Logo</title></svg>"
        "<title dir='ltr'>Sign In | Indeed Accounts</title>"
        "</body></html>"
    )

    # when / then
    assert ChallengeDetector.is_login_required(dirty_html) is True


def test_is_blocked_returns_true_for_catalogue_vendor_script() -> None:
    """New expectation under the scored verdict (migration step 4): a catalogue
    vendor_script marker on a thin page fires vendor_script beside the shape
    signals, which together reach the threshold, so the page is a wall."""
    # given
    html = "<html><body><script src='https://challenges.cloudflare.com/turnstile/v0/api.js'></script></body></html>"

    # when / then
    assert ChallengeDetector.is_blocked(200, html) is True


def test_is_blocked_returns_true_for_catalogue_title_phrase() -> None:
    """New expectation under the scored verdict (migration step 4): a catalogue
    title phrase in the title of a thin page fires phrase_title beside the shape
    signals, which together reach the threshold, so the page is a wall."""
    # given
    html = "<html><head><title>Pardon Our Interruption</title></head><body></body></html>"

    # when / then
    assert ChallengeDetector.is_blocked(200, html) is True


def test_is_blocked_returns_false_on_huge_content() -> None:
    # given
    huge = "a" * 50001

    # when / then
    assert ChallengeDetector.is_blocked(200, huge) is False


def test_is_login_required_returns_false_on_huge_content() -> None:
    # given
    huge = "a" * 50001

    # when / then
    assert ChallengeDetector.is_login_required(huge) is False


def test_is_login_redirect_url_empty_string_returns_false() -> None:
    # when / then
    assert ChallengeDetector.is_login_redirect_url("") is False


# noinspection PyTypeChecker
def test_is_login_redirect_url_none_returns_false() -> None:
    # when / then
    assert ChallengeDetector.is_login_redirect_url(None) is False  # type: ignore[arg-type]


def test_has_real_content_true_for_genuine_article() -> None:
    # given
    html = (
        "<html><body><article><p>"
        "This is a genuine paragraph of article content with more than ten words in it. "
        "It continues with a second sentence so the extractor has plenty of real prose."
        "</p></article></body></html>"
    )

    # when / then
    assert ChallengeDetector.has_real_content(html) is True


def test_has_real_content_false_for_empty_string() -> None:
    # when / then
    assert ChallengeDetector.has_real_content("") is False


def test_has_real_content_false_for_thin_interstitial() -> None:
    """A small page whose only text is a short interstitial paragraph (real content
    once boilerplate is stripped is near zero) must fail the positive-evidence check."""
    # given
    html = "<html><body><p>Please enable JS and disable any ad blocker</p></body></html>"

    # when / then
    assert ChallengeDetector.has_real_content(html) is False


def test_has_real_content_true_for_large_page_regardless_of_shape() -> None:
    """Pages at or above CHALLENGE_WALL_MAX_BYTES pass automatically: a genuine
    interstitial is small, so size alone rules it out."""
    # given
    huge = "a" * 50_000

    # when / then
    assert ChallengeDetector.has_real_content(huge) is True


def test_assess_accepts_bare_title_phrase_beside_prose() -> None:
    """New expectation under the scored verdict (migration step 4): a bare
    title-only catalogue phrase beside a few dozen words of prose fires no
    phrase signal, so the page is content; real walls are pinned by the corpus
    fixtures instead."""
    # given
    html = (
        "<html><body>Just a moment... "
        + "This looks like plenty of real prose to satisfy a naive word count. " * 2
        + "</body></html>"
    )

    # when / then
    assert assess(200, html).accepted is True


def test_assess_rejects_unrecognized_thin_interstitial() -> None:
    """The Allegro regression: a DataDome block page carrying no literal
    'datadome' string and no cf_clearance/turnstile marker must still be
    rejected via the positive-evidence structural check."""
    # given
    html = (
        "<html lang='en'><head><title>allegro.pl</title></head>"
        "<body style='margin:0'><p id='cmsg'>Please enable JS and disable any ad blocker</p>"
        "<script data-cfasync='false'>var dd={'host':'geo.captcha-delivery.com'}</script></body></html>"
    )

    # when / then
    assert assess(200, html).accepted is False


def test_assess_rejects_amazon_style_interstitial() -> None:
    """New expectation under the scored verdict (migration step 4): the catalogue
    Amazon interstitial marker fires over the prefix beside the body phrase, so
    an interstitial rendering the literal dictionary phrase is still rejected."""
    # given
    html = (
        "<html><body><p>Sorry, we just need to make sure you're not a robot.</p>"
        "<a href='/errors/validateCaptcha'>Continue shopping</a></body></html>"
    )

    # when / then
    assert assess(200, html).accepted is False


@pytest.mark.parametrize(
    ("locale", "heading", "button"),
    [
        ("pl", "Kliknij poniższy przycisk, aby kontynuować zakupy", "Kontynuuj zakupy"),
        ("com", "Click the button below to continue shopping", "Continue shopping"),
        ("co.uk", "Click the button below to continue shopping", "Continue shopping"),
        ("se", "Klicka på knappen nedan för att fortsätta handla", "Fortsätt handla"),
    ],
)
def test_assess_rejects_real_amazon_captcha_page_any_locale(locale: Any, heading: Any, button: Any) -> None:
    """The reported bug: Amazon's own captcha page carries no phrase from the
    dictionary in any locale, and its footer boilerplate (terms/privacy links,
    copyright line) alone is enough real prose to clear has_real_content's word
    count. Only the locale-independent structural marker (the fixed internal
    form action Amazon uses for this page in every locale) catches it. This
    fixture is a trimmed faithful copy of the real page fetched from
    amazon.{locale} on 2026-09-04, not a fixture engineered to match the
    dictionary."""
    # given
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

    # when / then
    assert ChallengeDetector.has_real_content(html) is True, (
        "fixture must reproduce the original bug: footer boilerplate alone clears the word count"
    )
    assert ChallengeDetector.is_blocked(200, html) is True
    assert assess(200, html).accepted is False


def test_is_blocked_returns_true_for_catalogue_structural_marker() -> None:
    """New expectation under the scored verdict (migration step 4): the catalogue
    Amazon form-action marker fires interstitial_structure, which beside the shape
    signals reaches the threshold, so the page is a wall."""
    # given
    html = "<html><body><form action='/errors_page/validateCaptcha'></form></body></html>"

    # when / then
    assert ChallengeDetector.is_blocked(200, html) is True


def test_assess_accepts_real_datadome_rendered_page() -> None:
    """A DataDome-protected page that has actually cleared and serves full content
    must not be rejected merely for referencing DataDome infrastructure."""
    # given
    html = "<html><body>" + "real job listings " * 50 + "</body></html>"

    # when / then
    assert assess(200, html).accepted is True


def test_is_login_redirect_url_matches_known_patterns() -> None:
    # when / then
    assert (
        ChallengeDetector.is_login_redirect_url(
            "https://secure.indeed.com/auth?continue=http://indeed.com/jobs"
        )
        is True
    )
    assert ChallengeDetector.is_login_redirect_url("https://example.com/login=true") is True
    assert ChallengeDetector.is_login_redirect_url("https://example.com?auth?data") is True
    assert ChallengeDetector.is_login_redirect_url("https://example.com/dashboard/settings") is False


def _verdict(
    *,
    wall: bool,
    intervention_type: str,
    signals: tuple[FiredSignal, ...] = (),
    login_landing: bool = False,
) -> ChallengeVerdict:
    return ChallengeVerdict(
        score=200 if wall else 20,
        threshold=100,
        signals=signals,
        vendor=None,
        wall=wall,
        has_content=not wall,
        intervention_type=intervention_type,
        login_landing=login_landing,
    )


_URL = "https://example.com/news/council"

_SIGN_IN_TITLE_HTML = "<html><head><title>Sign in</title></head><body></body></html>"

_PLAIN_TITLE_HTML = "<html><head><title>Release notes</title></head><body></body></html>"

_RICH_CONTENT = FiredSignal(
    id="rich_content", family="shape", weight=-70, vendor=None, evidence="rich-content"
)


def test_login_wall_verdict_turns_a_content_verdict_with_a_login_title_into_a_login_verdict() -> None:
    # given
    verdict = _verdict(wall=False, intervention_type="captcha")

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict, _SIGN_IN_TITLE_HTML, requested_url=_URL, final_url=_URL
    )

    # then
    assert login == _verdict(wall=False, intervention_type="login")


def test_login_wall_verdict_keeps_a_scored_login_wall_without_a_login_title() -> None:
    # given
    verdict = _verdict(wall=True, intervention_type="login")

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict, _PLAIN_TITLE_HTML, requested_url=_URL, final_url=_URL
    )

    # then
    assert login == verdict


@pytest.mark.parametrize("wall", [True, False])
def test_login_wall_verdict_is_none_without_a_login_title_or_a_scored_login_wall(wall: bool) -> None:
    # given
    verdict = _verdict(wall=wall, intervention_type="captcha")

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict, _PLAIN_TITLE_HTML, requested_url=_URL, final_url=_URL
    )

    # then
    assert login is None


def test_login_wall_verdict_is_none_for_a_login_title_on_a_page_with_rich_content() -> None:
    # given
    verdict = _verdict(wall=False, intervention_type="captcha", signals=(_RICH_CONTENT,))

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict, _SIGN_IN_TITLE_HTML, requested_url=_URL, final_url=_URL
    )

    # then
    assert login is None


def test_login_wall_verdict_keeps_a_scored_login_wall_on_a_page_with_rich_content() -> None:
    # given
    verdict = _verdict(wall=True, intervention_type="login", signals=(_RICH_CONTENT,))

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict, _SIGN_IN_TITLE_HTML, requested_url=_URL, final_url=_URL
    )

    # then
    assert login == verdict


def _large_article_titled_log_in() -> str:
    paragraph = (
        "<p>The city council met on Tuesday to discuss the new bus routes, the repair of the old"
        ' bridge and the budget for the next year. <a href="/news/council">Council news</a></p>'
    )
    head = "<html><head><title>Log in to read more</title></head><body><main><article><h1>Council</h1>"
    tail = "</article></main></body></html>"
    repeats = (600_000 - len(head) - len(tail)) // len(paragraph) + 1

    return head + paragraph * repeats + tail


def test_login_wall_verdict_is_none_for_a_login_title_on_an_article_above_the_shape_bound() -> None:
    # given
    html = _large_article_titled_log_in()
    verdict = assess(200, html, record_metrics=False)

    # when
    login = ChallengeDetector.login_wall_verdict(verdict, html, requested_url=_URL, final_url=_URL)

    # then
    assert len(html) > settings.CHALLENGE_SHAPE_MAX_BYTES
    assert login is None


_ARTICLE_URL = "https://www.example.com/r/programming/"

_LOGIN_FORM_HTML = (
    "<html><head><title>Example</title></head><body><form method='post'>"
    '<input type="text" name="user"><input type="password" name="secret">'
    "<button>Continue</button></form></body></html>"
)


@pytest.mark.parametrize(
    "final_url",
    [
        "https://www.example.com/login/?reason=lor2&dest=https%3A%2F%2Fwww.example.com%2Fr%2Fprogramming%2F",
        "https://www.example.com/accounts/login/?next=%2Fr%2Fprogramming%2F",
        "https://www.example.com/login?return_to=%2Fr%2Fprogramming%2F",
        "https://www.example.com/signin?returnTo=%2Fr%2Fprogramming%2F",
        "https://www.example.com/m/sign-in?redirect=%2Fr%2Fprogramming%2F",
        "https://www.example.com/log-in?redirect_uri=%2Fr%2Fprogramming%2F",
        "https://www.example.com/logon/?continue=%2Fr%2Fprogramming%2F",
        "https://www.example.com/Login.php?from=%2Fr%2Fprogramming%2F",
    ],
)
def test_login_wall_verdict_turns_a_redirect_to_a_login_path_with_a_return_address_into_a_login_verdict(
    final_url: str,
) -> None:
    # given
    verdict = _verdict(wall=False, intervention_type="captcha", signals=(_RICH_CONTENT,))

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict, _PLAIN_TITLE_HTML, requested_url=_ARTICLE_URL, final_url=final_url
    )

    # then
    assert login == _verdict(
        wall=False, intervention_type="login", signals=(_RICH_CONTENT,), login_landing=True
    )


@pytest.mark.parametrize(
    "final_url",
    [
        "https://www.example.com/Login.php",
        "https://www.example.com/signin",
        "https://www.example.com/log-in",
        "https://www.example.com/logon/",
    ],
)
def test_login_wall_verdict_turns_a_redirect_to_a_login_path_with_a_password_input_into_a_login_verdict(
    final_url: str,
) -> None:
    # given
    verdict = _verdict(wall=False, intervention_type="captcha")

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict, _LOGIN_FORM_HTML, requested_url=_ARTICLE_URL, final_url=final_url
    )

    # then
    assert login == _verdict(wall=False, intervention_type="login", login_landing=True)


@pytest.mark.parametrize(
    ("requested_url", "final_url"),
    [
        pytest.param(
            "https://old.reddit.com/r/programming/",
            "https://old.reddit.com/login/?reason=lor2&dest=https%3A%2F%2Fold.reddit.com%2Fr%2Fprogramming%2F",
            id="old-reddit-dest",
        ),
        pytest.param(
            "https://github.com/settings/profile",
            "https://github.com/login?return_to=https%3A%2F%2Fgithub.com%2Fsettings%2Fprofile",
            id="github-return-to",
        ),
        pytest.param(
            "https://www.instagram.com/accounts/edit/",
            "https://www.instagram.com/accounts/login/?next=https%3A%2F%2Fwww.instagram.com%2Faccounts%2Fedit%2F%3F__coig_login%3D1",
            id="instagram-next",
        ),
    ],
)
def test_is_login_landing_holds_for_the_measured_login_redirects(requested_url: str, final_url: str) -> None:
    # when / then
    assert ChallengeDetector.is_login_landing(requested_url, final_url, _PLAIN_TITLE_HTML) is True


def test_login_wall_verdict_turns_a_scored_captcha_wall_on_a_login_path_into_a_login_verdict() -> None:
    # given
    verdict = _verdict(wall=True, intervention_type="captcha")

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict,
        _PLAIN_TITLE_HTML,
        requested_url=_ARTICLE_URL,
        final_url="https://www.example.com/login/?next=%2Fr%2Fprogramming%2F",
    )

    # then
    assert login == _verdict(wall=True, intervention_type="login", login_landing=True)


@pytest.mark.parametrize(
    "final_url",
    [
        "https://www.example.com/r/programming/",
        "https://www.example.com/r/programming/?login=",
        "https://www.example.com/blog/login-tips/",
        "https://www.example.com/logins/history",
        "https://www.example.com/en/login/reset-password",
        "https://www.example.com/docs/login/sso-setup",
        "https://www.example.com/login/?reason=lor2",
        "https://www.example.com/signin/help?topic=passwords",
    ],
)
def test_login_wall_verdict_is_none_for_a_read_that_did_not_end_on_a_login_page(final_url: str) -> None:
    # given
    verdict = _verdict(wall=False, intervention_type="captcha")

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict, _PLAIN_TITLE_HTML, requested_url=_ARTICLE_URL, final_url=final_url
    )

    # then
    assert login is None


def test_login_wall_verdict_is_none_for_a_return_address_off_a_login_path() -> None:
    # given
    verdict = _verdict(wall=False, intervention_type="captcha")

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict,
        _LOGIN_FORM_HTML,
        requested_url=_ARTICLE_URL,
        final_url="https://www.example.com/r/programming/?next=%2Fr%2Fprogramming%2F",
    )

    # then
    assert login is None


def test_login_wall_verdict_is_none_for_a_login_path_the_read_asked_for() -> None:
    # given
    verdict = _verdict(wall=False, intervention_type="captcha")

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict,
        _LOGIN_FORM_HTML,
        requested_url="https://www.example.com/login",
        final_url="https://www.example.com/login/?next=%2F",
    )

    # then
    assert login is None


def test_login_wall_verdict_is_none_for_an_article_with_a_login_link_read_at_its_own_address() -> None:
    # given
    html = (
        "<html><head><title>Release notes</title></head><body><header>"
        '<a href="https://www.example.com/login/?dest=%2Fnews%2Frelease">Log in</a></header>'
        "<article><p>"
        + "The release adds faster reads and fixes the export of long reports. " * 30
        + "</p></article></body></html>"
    )
    verdict = assess(200, html, record_metrics=False)

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict,
        html,
        requested_url="https://www.example.com/news/release",
        final_url="https://www.example.com/news/release",
    )

    # then
    assert login is None


@pytest.mark.parametrize(("requested_url", "final_url"), [("", ""), (_ARTICLE_URL, "")])
def test_is_login_landing_is_false_without_a_final_address(requested_url: str, final_url: str) -> None:
    # when / then
    assert ChallengeDetector.is_login_landing(requested_url, final_url, _LOGIN_FORM_HTML) is False


def _large_block_page() -> str:
    style = "<style>" + ".a{color:red}" * 5000 + "</style>"

    return (
        "<html><head>" + style + "</head><body><div><p>You've been blocked by network security.</p>"
        "<p>If you think you've been blocked by mistake, file a ticket below and we'll look into it.</p>"
        '<a href="https://support.example.com/requests/new">File a ticket</a></div></body></html>'
    )


def test_assess_judges_a_large_403_block_page_by_its_phrase_a_wall() -> None:
    # given
    html = _large_block_page()

    # when
    verdict = assess(403, html, record_metrics=False)

    # then
    assert len(html) > settings.CHALLENGE_WALL_MAX_BYTES
    assert verdict.wall is True
    assert {"status_large_body", "phrase_body"} <= {signal.id for signal in verdict.signals}


def test_assess_reads_a_block_phrase_behind_a_large_inline_image() -> None:
    # given
    image = (
        '<img alt="" src="data:image/png;base64,'
        + "A" * (settings.CHALLENGE_DETECTION_MAX_BYTES + 1000)
        + '">'
    )
    html = (
        "<html><head><title>Blocked</title></head><body>"
        + image
        + "<p>You've been blocked by network security.</p></body></html>"
    )

    # when
    verdict = assess(403, html, record_metrics=False)

    # then
    assert "phrase_body" in {signal.id for signal in verdict.signals}
    assert verdict.wall is True


def test_assess_keeps_an_article_quoting_the_block_phrase_as_content() -> None:
    # given
    html = (
        "<html><head><title>Why sites block readers</title></head><body><article><h1>Blocked readers</h1><p>"
        + "Readers of large forums sometimes see a page that says you've been blocked by network security. "
        + "The page appears when traffic looks automated and the reader is asked to file a ticket. " * 12
        + "</p></article></body></html>"
    )

    # when
    verdict = assess(200, html, record_metrics=False)

    # then
    assert verdict.accepted is True


def test_login_wall_verdict_marks_a_scored_login_wall_that_landed_on_a_login_path() -> None:
    # given
    verdict = _verdict(wall=True, intervention_type="login")

    # when
    login = ChallengeDetector.login_wall_verdict(
        verdict,
        _PLAIN_TITLE_HTML,
        requested_url=_ARTICLE_URL,
        final_url="https://www.example.com/login/?next=%2Fr%2Fprogramming%2F",
    )

    # then
    assert login == _verdict(wall=True, intervention_type="login", login_landing=True)


def test_login_landing_hands_the_password_check_only_the_shape_prefix() -> None:
    # given a login page far above the shape limit
    limit = settings.CHALLENGE_SHAPE_MAX_BYTES
    html = "x" * (2 * limit)

    # when
    with patch("src.reader.cloudflare.challenge_detector.has_password_input", return_value=False) as spy:
        landing = ChallengeDetector.is_login_landing(
            "https://example.com/a", "https://example.com/login", html
        )

    # then
    assert landing is False
    assert len(spy.call_args.args[0]) == limit
