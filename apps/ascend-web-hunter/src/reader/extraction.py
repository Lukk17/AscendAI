"""HTML content extraction utilities.

Provides two extraction paths:
  - text: the existing flat string (default, backward-compatible)
  - structured: article metadata from the trafilatura and readability-lxml ensemble
"""

import json
import logging
from typing import Any

import trafilatura
from bs4 import BeautifulSoup
from extruct import extract as extruct_extract
from readability import Document

logger = logging.getLogger(__name__)

_EMBEDDED_SYNTAXES = ["json-ld", "microdata", "opengraph"]

_BOILERPLATE_MARKERS = (
    "nav",
    "sidebar",
    "footer",
    "header",
    "menu",
    "comment",
    "related",
    "promo",
    "advert",
    "widget",
)


def extract_embedded_metadata(html: str) -> dict[str, Any]:
    """Parse JSON-LD, OpenGraph and microdata with extruct (design D1).

    A parse error leaves the metadata empty and logs a WARNING. It never fails the read.
    """
    try:
        data = extruct_extract(html, syntaxes=_EMBEDDED_SYNTAXES, uniform=True)
    except Exception:
        logger.warning("extruct embedded-data parse failed", exc_info=True)

        return {}

    return {
        "json-ld": list(data.get("json-ld", [])),
        "microdata": list(data.get("microdata", [])),
        "opengraph": list(data.get("opengraph", [])),
    }


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


def _ensemble_score(content: str) -> float:
    """Score one extraction by text length discounted for links and boilerplate (design D2)."""
    soup = BeautifulSoup(content, "html.parser")
    plain = soup.get_text(" ", strip=True)
    length = len(plain)
    if length == 0:
        return 0.0
    link_chars = sum(len(link.get_text(" ", strip=True)) for link in soup.find_all("a"))
    link_density = min(1.0, link_chars / length)
    boilerplate_chars = 0
    for tag in soup.find_all(True):
        class_value = tag.get("class")
        class_names = " ".join(class_value) if isinstance(class_value, list) else ""
        marker = f"{class_names} {tag.get('id') or ''}".lower()
        if any(part in marker for part in _BOILERPLATE_MARKERS):
            boilerplate_chars += len(tag.get_text(" ", strip=True))
    boilerplate_ratio = min(1.0, boilerplate_chars / length)

    return length * (1.0 - link_density) * (1.0 - boilerplate_ratio)


def _trafilatura_structured(html: str) -> dict[str, Any] | None:
    """Run trafilatura once in JSON mode and return a structured dict, or None on failure."""
    try:
        raw = trafilatura.extract(
            html,
            output_format="json",
            with_metadata=True,
            include_comments=False,
        )
        if not raw:
            return None

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


def _trafilatura_text(html: str) -> str:
    """Run trafilatura once in text mode, returning an empty string on failure."""
    try:
        return trafilatura.extract(html) or ""
    except Exception:
        logger.debug("trafilatura text extraction failed", exc_info=True)

        return ""


def extract_structured(html: str) -> dict[str, Any]:
    """Extract structured article data from HTML.

    Trafilatura and readability-lxml both run on the same HTML and the higher
    scoring ensemble result wins. Ties go to trafilatura.

    Returns a dict with keys: title, content, author, date, sitename, source, metadata.
    The "content" key is the main body text (equivalent to the flat string
    returned by plain extract()).
    """
    metadata = extract_embedded_metadata(html)
    traf = _trafilatura_structured(html)
    read_result = _readability_extract(html)
    traf_content: str = (traf or {}).get("content", "")
    read_content: str = read_result.get("content", "")

    if _ensemble_score(read_content) > _ensemble_score(traf_content):
        return {**read_result, "metadata": metadata}

    if traf is not None:
        return {**traf, "metadata": metadata}

    return {
        "title": "",
        "content": "",
        "author": "",
        "date": "",
        "sitename": "",
        "source": "none",
        "metadata": metadata,
    }


def extract_text_with_fallback(html: str) -> str:
    """Extract text from HTML: both extractors run and the higher scoring result wins.

    Ties go to trafilatura. This is the flat-string equivalent: returns the content only.
    Used for the default output_format=text path.
    """
    traf_text = _trafilatura_text(html)
    read_content: str = _readability_extract(html).get("content", "")

    if _ensemble_score(read_content) > _ensemble_score(traf_text):
        return read_content

    return traf_text
