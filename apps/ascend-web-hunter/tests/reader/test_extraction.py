"""Tests for structured extraction and readability fallback (tasks 5.1, 5.2)."""

from pathlib import Path
from unittest.mock import patch

import trafilatura

from src.reader.extraction import (
    _extract_text_with_recall_fallback,
    extract_structured,
    extract_text_with_fallback,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_BOOKS_LISTING_HTML = (_FIXTURES / "books_toscrape_index.html").read_text(encoding="utf-8")
_ARTICLE_HTML = (_FIXTURES / "gnu_free_sw_article.html").read_text(encoding="utf-8")

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


def test_extract_text_with_fallback_returns_listing_titles_through_recall_pass() -> None:
    """The books listing loses every title in precision mode and the recall pass restores them."""
    result = extract_text_with_fallback(_BOOKS_LISTING_HTML)
    assert "Tipping the Velvet" in result
    assert "Sharp Objects" in result
    assert "£51.77" in result


def test_extract_text_with_fallback_precision_pass_alone_drops_listing_titles() -> None:
    """With the ratio at 0 the recall pass never runs and the listing comes back as prices only."""
    with patch("src.reader.extraction.settings.CONTENT_RECALL_FALLBACK_RATIO", 0.0):
        result = extract_text_with_fallback(_BOOKS_LISTING_HTML)
    assert "Tipping the Velvet" not in result
    assert "£51.77" in result


def test_extract_text_with_fallback_article_page_uses_precision_pass_only() -> None:
    """An article page clears the ratio on the first pass, so trafilatura runs exactly once."""
    with patch("src.reader.extraction.trafilatura.extract", wraps=trafilatura.extract) as extract:
        result = extract_text_with_fallback(_ARTICLE_HTML)
    assert "The four essential freedoms" in result
    extract.assert_called_once_with(_ARTICLE_HTML, favor_recall=False)


def test_extract_text_with_fallback_keeps_precision_pass_when_recall_pass_is_not_longer() -> None:
    """A recall pass that returns less than the precision pass is discarded."""
    passes = ["precision text", "short"]
    with (
        patch("src.reader.extraction.trafilatura.extract", side_effect=passes) as extract,
        patch("src.reader.extraction.settings.READABILITY_FALLBACK_MIN_CHARS", 0),
    ):
        result = extract_text_with_fallback(_GOOD_HTML)
    assert result == "precision text"
    assert extract.call_count == 2
    assert extract.call_args_list[1].kwargs == {"favor_recall": True}


def test_recall_pass_is_skipped_when_the_page_has_no_text() -> None:
    """A page whose plain text is empty never triggers the second pass, and no division happens."""
    with patch("src.reader.extraction.trafilatura.extract", return_value=None) as extract:
        result = _extract_text_with_recall_fallback("<html><body><script>1</script></body></html>")
    assert result == ""
    extract.assert_called_once()


def test_extract_structured_returns_listing_titles_through_recall_pass() -> None:
    """The structured path shares the two-pass rule, so the books listing keeps its titles there too."""
    result = extract_structured(_BOOKS_LISTING_HTML)
    assert result["source"] == "trafilatura"
    assert "Tipping the Velvet" in result["content"]
    assert "Sharp Objects" in result["content"]


def test_extract_structured_keeps_precision_pass_when_recall_pass_fails() -> None:
    """A recall pass that yields nothing leaves the precision pass in place."""
    precision_json = '{"text": "precision text", "title": "t", "author": "", "date": "", "sitename": ""}'
    passes = [precision_json, None]
    with (
        patch("src.reader.extraction.trafilatura.extract", side_effect=passes) as extract,
        patch("src.reader.extraction.settings.READABILITY_FALLBACK_MIN_CHARS", 0),
    ):
        result = extract_structured(_GOOD_HTML)
    assert result["content"] == "precision text"
    assert result["title"] == "t"
    assert extract.call_count == 2
    assert extract.call_args_list[0].kwargs["favor_recall"] is False
    assert extract.call_args_list[1].kwargs["favor_recall"] is True


def test_extract_structured_uses_recall_pass_when_precision_pass_fails() -> None:
    """A precision pass that yields nothing is replaced by a recall pass that yields content."""
    recall_json = '{"text": "recall text", "title": "t", "author": "", "date": "", "sitename": ""}'
    passes = [None, recall_json]
    with (
        patch("src.reader.extraction.trafilatura.extract", side_effect=passes),
        patch("src.reader.extraction.settings.READABILITY_FALLBACK_MIN_CHARS", 0),
    ):
        result = extract_structured(_GOOD_HTML)
    assert result["content"] == "recall text"
    assert result["source"] == "trafilatura"
