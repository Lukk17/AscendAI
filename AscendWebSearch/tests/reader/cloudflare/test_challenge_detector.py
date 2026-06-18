from unittest.mock import patch

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
