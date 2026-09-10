"""HTML content extraction utilities.

Provides two extraction paths:
  - text: the existing flat string (default, backward-compatible)
  - structured: article metadata from trafilatura + readability-lxml fallback
"""

import logging
from collections.abc import Callable
from typing import Any

import trafilatura
from bs4 import BeautifulSoup
from readability import Document

from src.config.config import settings
from src.reader.html_utils import remove_noise_tags

logger = logging.getLogger(__name__)


def _readability_extract(html: str) -> dict[str, Any]:
    """Extract main content via readability-lxml and return a structured dict."""
    doc = Document(html)

    return {
        "title": doc.title() or "",
        "content": doc.summary() or "",
        "author": "",
        "date": "",
        "sitename": "",
        "source": "readability",
    }


def _plain_text_length(html: str) -> int:
    soup = BeautifulSoup(html, "html.parser")
    remove_noise_tags(soup)

    return len(soup.get_text(" ", strip=True))


def _longer_of_two_passes[T](html: str, run_pass: Callable[[bool], T], length_of: Callable[[T], int]) -> T:
    """Run a precision pass, then a recall pass when the first is thin against the page.

    The first pass is thin when it is shorter than CONTENT_RECALL_FALLBACK_RATIO times the
    page's plain text. The longer of the two passes wins.
    """
    precision_result = run_pass(False)
    if length_of(precision_result) >= settings.CONTENT_RECALL_FALLBACK_RATIO * _plain_text_length(html):
        return precision_result

    recall_result = run_pass(True)

    return recall_result if length_of(recall_result) > length_of(precision_result) else precision_result


def _structured_content_length(result: dict[str, Any] | None) -> int:
    content: str = (result or {}).get("content", "")

    return len(content)


def _trafilatura_structured(html: str, favor_recall: bool = False) -> dict[str, Any] | None:
    """Run trafilatura in JSON mode and return a structured dict, or None on failure."""
    try:
        raw = trafilatura.extract(
            html,
            output_format="json",
            with_metadata=True,
            include_comments=False,
            favor_recall=favor_recall,
        )
        if not raw:
            return None

        import json  # local import to avoid top-level json dep ordering issue

        parsed: dict[str, Any] = json.loads(raw)

        return {
            "title": parsed.get("title") or "",
            "content": parsed.get("text") or "",
            "author": parsed.get("author") or "",
            "date": parsed.get("date") or "",
            "sitename": parsed.get("sitename") or "",
            "source": "trafilatura",
        }
    except Exception:
        logger.debug("trafilatura structured extraction failed", exc_info=True)

        return None


def extract_structured(html: str) -> dict[str, Any]:
    """Extract structured article data from HTML.

    Tries trafilatura first.  When the result is shorter than
    READABILITY_FALLBACK_MIN_CHARS, readability-lxml is tried and the
    longer result (by character count of the content field) wins.

    Returns a dict with keys: title, content, author, date, sitename, source.
    The "content" key is the main body text (equivalent to the flat string
    returned by plain extract()).
    """
    traf = _longer_of_two_passes(
        html,
        lambda favor_recall: _trafilatura_structured(html, favor_recall),
        _structured_content_length,
    )
    traf_len = _structured_content_length(traf)

    if traf_len >= settings.READABILITY_FALLBACK_MIN_CHARS:
        return traf or {
            "title": "",
            "content": "",
            "author": "",
            "date": "",
            "sitename": "",
            "source": "none",
        }

    read_result = _readability_extract(html)
    read_len = len(read_result.get("content", ""))

    if traf is not None and traf_len >= read_len:
        return traf

    return read_result


def _extract_text_with_recall_fallback(html: str) -> str:
    return _longer_of_two_passes(
        html,
        lambda favor_recall: trafilatura.extract(html, favor_recall=favor_recall) or "",
        len,
    )


def extract_text_with_fallback(html: str) -> str:
    """Extract text from HTML, falling back to readability when trafilatura is thin.

    This is the flat-string equivalent: returns the content field only.
    Used for the default output_format=text path.
    """
    traf_text = _extract_text_with_recall_fallback(html)
    traf_len = len(traf_text)

    if traf_len >= settings.READABILITY_FALLBACK_MIN_CHARS:
        return traf_text

    read_result = _readability_extract(html)
    read_content: str = read_result.get("content", "")
    read_len = len(read_content)

    if traf_text and traf_len >= read_len:
        return traf_text

    return read_content
