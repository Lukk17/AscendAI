"""Tests for structured extraction and readability fallback (tasks 5.1, 5.2)."""

from unittest.mock import patch

from src.reader.extraction import extract_structured, extract_text_with_fallback

_GOOD_HTML = """
<html>
<head><title>Test Article</title></head>
<body>
<article>
<h1>Test Article</h1>
<p>Author: Jane Doe</p>
<p>Published on 2024-01-15</p>
<p>This is the main body of the article with enough text to pass the threshold.
The article covers interesting topics and provides valuable information to the reader.
It has multiple sentences to ensure it clears any minimum length requirement.</p>
</article>
</body>
</html>
"""

_THIN_HTML = "<html><body><p>short</p></body></html>"


def test_extract_structured_returns_required_keys() -> None:
    result = extract_structured(_GOOD_HTML)
    assert "title" in result
    assert "content" in result
    assert "author" in result
    assert "date" in result
    assert "sitename" in result
    assert "source" in result


def test_extract_structured_content_not_empty_for_good_html() -> None:
    result = extract_structured(_GOOD_HTML)
    assert result["content"]


def test_extract_structured_falls_back_to_readability_when_trafilatura_thin() -> None:
    """When trafilatura returns content below the threshold, readability is tried."""
    with patch("src.reader.extraction.settings.READABILITY_FALLBACK_MIN_CHARS", 10_000):
        result = extract_structured(_GOOD_HTML)
    assert result["source"] in ("readability", "trafilatura")


def test_extract_structured_returns_readability_when_traf_fails() -> None:
    """When trafilatura itself returns None, readability provides the content."""
    with patch("src.reader.extraction.trafilatura.extract", return_value=None):
        result = extract_structured(_GOOD_HTML)
    assert result["source"] == "readability"


def test_extract_text_with_fallback_returns_string() -> None:
    result = extract_text_with_fallback(_GOOD_HTML)
    assert isinstance(result, str)
    assert len(result) > 0


def test_extract_text_with_fallback_uses_readability_when_traf_thin() -> None:
    """When trafilatura returns fewer chars than the threshold, readability is tried."""
    with patch("src.reader.extraction.settings.READABILITY_FALLBACK_MIN_CHARS", 10_000):
        result = extract_text_with_fallback(_GOOD_HTML)
    assert isinstance(result, str)


def test_extract_text_with_fallback_returns_traf_when_longer() -> None:
    """When trafilatura result is longer than readability, trafilatura wins."""
    long_traf = "x" * 1000
    short_read = {
        "content": "short",
        "title": "",
        "author": "",
        "date": "",
        "sitename": "",
        "source": "readability",
    }
    with (
        patch("src.reader.extraction.trafilatura.extract", return_value=long_traf),
        patch("src.reader.extraction._readability_extract", return_value=short_read),
        patch("src.reader.extraction.settings.READABILITY_FALLBACK_MIN_CHARS", 50),
    ):
        result = extract_text_with_fallback(_GOOD_HTML)
    assert result == long_traf


def test_extract_structured_handles_trafilatura_json_exception() -> None:
    """When trafilatura raises during JSON extraction the exception is caught and readability runs."""
    with patch("src.reader.extraction.trafilatura.extract", side_effect=ValueError("bad json")):
        result = extract_structured(_GOOD_HTML)
    assert "content" in result
    assert result["source"] == "readability"


def test_extract_structured_prefers_traf_when_traf_below_threshold_but_longer_than_readability() -> None:
    """When trafilatura is below threshold but still longer than readability, trafilatura wins."""
    very_short_read: dict[str, str] = {
        "content": "y" * 10,
        "title": "",
        "author": "",
        "date": "",
        "sitename": "",
        "source": "readability",
    }
    traf_json = f'{{"text": "{"x" * 50}", "title": "", "author": null, "date": null, "sitename": null}}'
    with (
        patch("src.reader.extraction.trafilatura.extract", return_value=traf_json),
        patch("src.reader.extraction._readability_extract", return_value=very_short_read),
        patch("src.reader.extraction.settings.READABILITY_FALLBACK_MIN_CHARS", 200),
    ):
        result = extract_structured(_GOOD_HTML)
    # traf_len (50) < threshold (200) but traf_len (50) >= read_len (10) → trafilatura wins
    assert result["source"] == "trafilatura"


def test_extract_text_with_fallback_prefers_traf_below_threshold_when_longer_than_readability() -> None:
    """traf below threshold but still longer than readability → traf text is returned."""
    short_traf = "x" * 50
    very_short_read: dict[str, str] = {
        "content": "y" * 10,
        "title": "",
        "author": "",
        "date": "",
        "sitename": "",
        "source": "readability",
    }
    with (
        patch("src.reader.extraction.trafilatura.extract", return_value=short_traf),
        patch("src.reader.extraction._readability_extract", return_value=very_short_read),
        patch("src.reader.extraction.settings.READABILITY_FALLBACK_MIN_CHARS", 200),
    ):
        result = extract_text_with_fallback(_GOOD_HTML)
    assert result == short_traf


def test_extract_structured_prefers_readability_when_it_scores_higher() -> None:
    """When readability content is longer, readability wins."""
    short_traf_json = '{"text": "x", "title": "", "author": "", "date": "", "sitename": ""}'
    long_read: dict[str, str] = {
        "content": "y" * 500,
        "title": "title",
        "author": "",
        "date": "",
        "sitename": "",
        "source": "readability",
    }
    with (
        patch("src.reader.extraction.trafilatura.extract", return_value=short_traf_json),
        patch("src.reader.extraction._readability_extract", return_value=long_read),
        patch("src.reader.extraction.settings.READABILITY_FALLBACK_MIN_CHARS", 50),
    ):
        result = extract_structured(_GOOD_HTML)
    assert result["source"] == "readability"
    assert result["content"] == long_read["content"]
