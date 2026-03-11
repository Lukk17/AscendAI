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
    # Only tests <title> tags now
    assert ChallengeDetector.is_login_required("https://example.com/auth",
                                               "<html><head><title>Sign In | Indeed Accounts</title></head><body></body></html>") is True
    assert ChallengeDetector.is_login_required("https://example.com/login",
                                               "<html><head><title>Log In | Example</title></head><body></body></html>") is True
    assert ChallengeDetector.is_login_required("https://example.com/signin",
                                               "<html><head><title>Welcome to the home page</title></head><body>Sign in to continue</body></html>") is False
    assert ChallengeDetector.is_login_required("https://example.com",
                                               "<html><head><title>Login - Portal</title></head><body>Enter your password</body></html>") is True
    assert ChallengeDetector.is_login_required("https://example.com",
                                               "<html><body>Sign in to continue</body></html>") is False
    assert ChallengeDetector.is_login_required("https://example.com",
                                               "<html><body>Enter your password</body></html>") is False
    assert ChallengeDetector.is_login_required("https://example.com",
                                               "<html><head><title>Welcome</title></head><body></body></html>") is False


def test_is_login_required_svg_bypass():
    # Proves the finditer logic prevents <svg> title tags from masking the real <title>
    dirty_html = "<html><body><svg><title id='logo'>Indeed Logo</title></svg><title dir='ltr'>Sign In | Indeed Accounts</title></body></html>"
    assert ChallengeDetector.is_login_required("https://indeed.com/auth", dirty_html) is True


def test_is_login_redirect_url():
    # Proves URL parameter stripping works for preemptive exits
    assert ChallengeDetector.is_login_redirect_url(
        "https://secure.indeed.com/auth?continue=http://indeed.com/jobs") is True
    assert ChallengeDetector.is_login_redirect_url("https://example.com/login=true") is True
    assert ChallengeDetector.is_login_redirect_url("https://example.com?auth?data") is True
    assert ChallengeDetector.is_login_redirect_url("https://example.com/dashboard/settings") is False
