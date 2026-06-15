"""Tests for challenge detection on pages >50 KB (task 6.3).

Before the fix, pages larger than 50 000 bytes were silently returned as
'clean' — any challenge wall on a large page was missed.  After the fix,
the detector scans a bounded prefix so challenge markers in the head/title
section are still detected regardless of total page size.
"""
from unittest.mock import patch

import pytest

from src.reader.cloudflare.challenge_detector import ChallengeDetector


@pytest.fixture
def _large_cf_page() -> str:
    """A page >50 KB whose <title> is a Cloudflare challenge, followed by lots of body text."""
    title_block = "<html><head><title>Sign In | LinkedIn</title></head><body>"
    padding = "a" * 60_000
    return title_block + padding + "</body></html>"


@pytest.fixture
def _large_waf_page() -> str:
    """A page >50 KB with Ray ID in the first few hundred bytes."""
    header = "<html><body>Ray ID: 89abcdef0123 "
    padding = "x" * 60_000
    return header + padding + "</body></html>"


def test_is_login_required_detects_marker_in_large_page(_large_cf_page: str):
    with patch(
        "src.reader.cloudflare.challenge_detector._BOT_DICT",
        {"waf_script_signatures": [], "waf_strict_phrases": [], "login_title_patterns": ["sign in"]},
    ):
        assert ChallengeDetector.is_login_required("https://linkedin.com", _large_cf_page) is True


def test_is_blocked_detects_ray_id_in_large_page(_large_waf_page: str):
    assert ChallengeDetector.is_blocked(200, _large_waf_page) is True


def test_is_login_required_clean_large_page_returns_false():
    """A genuinely clean large page must not be misidentified as a login wall."""
    big_clean = "<html><head><title>LinkedIn Feed</title></head><body>" + "content " * 10_000 + "</body></html>"
    with patch(
        "src.reader.cloudflare.challenge_detector._BOT_DICT",
        {"waf_script_signatures": [], "waf_strict_phrases": [], "login_title_patterns": ["sign in"]},
    ):
        assert ChallengeDetector.is_login_required("https://linkedin.com/feed", big_clean) is False


def test_challenge_detection_max_bytes_setting_respected():
    """
    When CHALLENGE_DETECTION_MAX_BYTES is small, a marker placed after the prefix
    must NOT be detected (detector correctly limits its scan).
    """
    marker = "cf_clearance"
    # Place marker after the scan window
    prefix = "a" * 100
    html = prefix + marker

    with patch("src.reader.cloudflare.challenge_detector.settings.CHALLENGE_DETECTION_MAX_BYTES", 100):
        result = ChallengeDetector.is_blocked(200, html)

    assert result is False


def test_challenge_detection_fires_when_marker_within_max_bytes():
    """When the marker falls inside the prefix window, detection must fire."""
    marker = "cf_clearance"
    html = "prefix " + marker + " suffix " + "a" * 60_000

    with patch("src.reader.cloudflare.challenge_detector.settings.CHALLENGE_DETECTION_MAX_BYTES", 50_000):
        result = ChallengeDetector.is_blocked(200, html)

    assert result is True
