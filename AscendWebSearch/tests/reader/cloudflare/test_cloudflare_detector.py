from src.reader.cloudflare.cloudflare_detector import CloudflareDetector


def test_is_blocked_no_content():
    assert CloudflareDetector.is_blocked(403, "") is True
    assert CloudflareDetector.is_blocked(429, "") is True
    assert CloudflareDetector.is_blocked(503, "") is True
    assert CloudflareDetector.is_blocked(200, "") is False


def test_is_blocked_large_content():
    large_html = "a" * 50001
    assert CloudflareDetector.is_blocked(403, large_html) is False


def test_is_blocked_keywords():
    html_with_keyword = "<html><body>Please wait while your request is being verified</body></html>"
    assert CloudflareDetector.is_blocked(200, html_with_keyword) is True
    assert CloudflareDetector.is_blocked(403, html_with_keyword) is True


def test_is_blocked_ray_id():
    html_with_ray_id = "<html><body>Ray ID: 890123abc</body></html>"
    assert CloudflareDetector.is_blocked(200, html_with_ray_id) is True


def test_is_blocked_cf_tokens():
    html_turnstile = "<html><body><script src='cf-turnstile'></script></body></html>"
    assert CloudflareDetector.is_blocked(200, html_turnstile) is True

    html_clearance = "<html><body>Missing cf_clearance cookie</body></html>"
    assert CloudflareDetector.is_blocked(200, html_clearance) is True


def test_not_blocked():
    valid_html = "<html><body>Real website content without blocks</body></html>"
    assert CloudflareDetector.is_blocked(200, valid_html) is False
