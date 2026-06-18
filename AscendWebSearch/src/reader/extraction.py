"""HTML content extraction utilities.

Provides two extraction paths:
  - text: the existing flat string (default, backward-compatible)
  - structured: article metadata from trafilatura + readability-lxml fallback
"""

import logging
from typing import Any

import trafilatura
from readability import Document

from src.config.config import settings

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


def _trafilatura_structured(html: str) -> dict[str, Any] | None:
    """Run trafilatura in JSON mode and return a structured dict, or None on failure."""
    try:
        raw = trafilatura.extract(
            html,
            output_format="json",
            with_metadata=True,
            include_comments=False,
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
    traf = _trafilatura_structured(html)
    traf_content = (traf or {}).get("content", "")
    traf_len = len(traf_content)

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


def extract_text_with_fallback(html: str) -> str:
    """Extract text from HTML, falling back to readability when trafilatura is thin.

    This is the flat-string equivalent: returns the content field only.
    Used for the default output_format=text path.
    """
    traf_text: str | None = trafilatura.extract(html)
    traf_len = len(traf_text) if traf_text else 0

    if traf_len >= settings.READABILITY_FALLBACK_MIN_CHARS:
        return traf_text or ""

    read_result = _readability_extract(html)
    read_content: str = read_result.get("content", "")
    read_len = len(read_content)

    if traf_text and traf_len >= read_len:
        return traf_text

    return read_content
