"""Tests for the D2 ensemble: trafilatura and readability-lxml both run, higher score wins."""

from pathlib import Path
from unittest.mock import patch

from src.reader.extraction import (
    _ensemble_score,
    _readability_extract,
    _trafilatura_structured,
    extract_embedded_metadata,
    extract_structured,
    extract_tables,
    extract_text_with_fallback,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_BOOKS_LISTING_HTML = (_FIXTURES / "books_toscrape_index.html").read_text(encoding="utf-8")
_ARTICLE_HTML = (_FIXTURES / "gnu_free_sw_article.html").read_text(encoding="utf-8")
_PRODUCT_HTML = (_FIXTURES / "embedded_product.html").read_text(encoding="utf-8")
_READABILITY_WINS_HTML = (_FIXTURES / "ensemble_readability_wins.html").read_text(encoding="utf-8")
_TIE_HTML = (_FIXTURES / "ensemble_tie.html").read_text(encoding="utf-8")

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


def _structured(content: str, source: str) -> dict[str, str]:
    return {
        "title": "t",
        "content": content,
        "author": "",
        "date": "",
        "sitename": "",
        "source": source,
    }


def test_extract_structured_returns_required_keys() -> None:
    # when
    result = extract_structured(_GOOD_HTML)

    # then
    assert "title" in result
    assert "content" in result
    assert "author" in result
    assert "date" in result
    assert "sitename" in result
    assert "source" in result
    assert "metadata" in result


def test_extract_structured_content_not_empty_for_good_html() -> None:
    # when
    result = extract_structured(_GOOD_HTML)

    # then
    assert result["content"]


def test_ensemble_prefers_trafilatura_on_the_article_page() -> None:
    """On a full article trafilatura's cleaner extraction outscores readability."""
    # when
    result = extract_structured(_ARTICLE_HTML)

    # then
    assert result["source"] == "trafilatura"
    assert "The four essential freedoms" in result["content"]


def test_ensemble_prefers_trafilatura_on_the_listing_page() -> None:
    """On the books listing trafilatura's 319 characters outscore readability's 131."""
    # when
    result = extract_structured(_BOOKS_LISTING_HTML)

    # then
    assert result["source"] == "trafilatura"


def test_ensemble_prefers_readability_when_trafilatura_fails() -> None:
    """When trafilatura returns nothing, readability's real extraction wins."""
    # when
    with patch("src.reader.extraction.trafilatura.extract", return_value=None):
        result = extract_structured(_GOOD_HTML)

    # then
    assert result["source"] == "readability"
    assert "Test Article" in result["content"]


def test_ensemble_prefers_readability_on_the_aside_page() -> None:
    """Trafilatura drops the aside, readability keeps it, so readability outscores it."""
    # when
    result = extract_structured(_READABILITY_WINS_HTML)

    # then
    assert result["source"] == "readability"
    assert "Visiting hours" in result["content"]


def test_ensemble_readability_win_scores_rank_unmocked() -> None:
    """Pin the fixture property: on the aside page the readability score is higher."""
    # when
    traf = _trafilatura_structured(_READABILITY_WINS_HTML)
    read_content: str = _readability_extract(_READABILITY_WINS_HTML).get("content", "")

    # then
    assert traf is not None
    assert _ensemble_score(read_content) > _ensemble_score(traf.get("content", ""))


def test_ensemble_tie_goes_to_trafilatura_on_the_tie_fixture() -> None:
    """Both extractors return the same short note, so the scores tie and trafilatura wins."""
    # when
    traf = _trafilatura_structured(_TIE_HTML)
    read_content: str = _readability_extract(_TIE_HTML).get("content", "")
    result = extract_structured(_TIE_HTML)

    # then
    assert traf is not None
    assert _ensemble_score(read_content) == _ensemble_score(traf.get("content", ""))
    assert result["source"] == "trafilatura"


def test_ensemble_tie_goes_to_trafilatura() -> None:
    """Identical contents score the same, so trafilatura wins the tie."""
    # given
    content = "Same clean content in both extractors."

    # when
    with (
        patch(
            "src.reader.extraction._trafilatura_structured",
            return_value=_structured(content, "trafilatura"),
        ),
        patch(
            "src.reader.extraction._readability_extract",
            return_value=_structured(content, "readability"),
        ),
    ):
        result = extract_structured(_GOOD_HTML)

    # then
    assert result["source"] == "trafilatura"


def test_ensemble_returns_none_source_when_both_extractors_are_empty() -> None:
    """Two empty extractions tie at zero with no trafilatura result, so the none fallback answers."""
    # when
    with (
        patch("src.reader.extraction._trafilatura_structured", return_value=None),
        patch(
            "src.reader.extraction._readability_extract",
            return_value=_structured("", "readability"),
        ),
    ):
        result = extract_structured(_GOOD_HTML)

    # then
    assert result["source"] == "none"
    assert result["content"] == ""


def test_ensemble_link_density_penalty_flips_the_winner() -> None:
    """A longer but fully linked readability result loses to a shorter clean trafilatura one."""
    # given
    linked = "<p>Listing: " + " ".join(f'<a href="/item{i}">item {i}</a>' for i in range(20)) + "</p>"
    assert len(linked) > len("Clean result here with enough words to count.")

    # when
    with (
        patch(
            "src.reader.extraction._trafilatura_structured",
            return_value=_structured("Clean result here with enough words to count.", "trafilatura"),
        ),
        patch(
            "src.reader.extraction._readability_extract",
            return_value=_structured(linked, "readability"),
        ),
    ):
        result = extract_structured(_GOOD_HTML)

    # then
    assert result["source"] == "trafilatura"


def test_ensemble_boilerplate_penalty_flips_the_winner() -> None:
    """A longer readability result wrapped in sidebar markup loses to clean trafilatura text."""
    # given
    boilerplate = '<div class="sidebar">' + "<p>Promo words here.</p>" * 20 + "</div>"
    assert len(boilerplate) > len("Clean result here with enough words to count.")

    # when
    with (
        patch(
            "src.reader.extraction._trafilatura_structured",
            return_value=_structured("Clean result here with enough words to count.", "trafilatura"),
        ),
        patch(
            "src.reader.extraction._readability_extract",
            return_value=_structured(boilerplate, "readability"),
        ),
    ):
        result = extract_structured(_GOOD_HTML)

    # then
    assert result["source"] == "trafilatura"


def test_ensemble_score_is_zero_for_empty_content() -> None:
    # when / then
    assert _ensemble_score("") == 0.0
    assert _ensemble_score("<div></div>") == 0.0


def test_extract_structured_handles_trafilatura_json_exception() -> None:
    """When trafilatura raises during JSON extraction the exception is caught and readability wins."""
    # when
    with patch("src.reader.extraction.trafilatura.extract", side_effect=ValueError("bad json")):
        result = extract_structured(_GOOD_HTML)

    # then
    assert "content" in result
    assert result["source"] == "readability"


def test_extract_text_returns_string_for_good_html() -> None:
    # when
    result = extract_text_with_fallback(_GOOD_HTML)

    # then
    assert isinstance(result, str)
    assert len(result) > 0


def test_extract_text_prefers_trafilatura_on_the_article_page() -> None:
    # when
    result = extract_text_with_fallback(_ARTICLE_HTML)

    # then
    assert "The four essential freedoms" in result


def test_extract_text_prefers_readability_when_trafilatura_returns_none() -> None:
    # when
    with patch("src.reader.extraction.trafilatura.extract", return_value=None):
        result = extract_text_with_fallback(_GOOD_HTML)

    # then
    assert "Test Article" in result


def test_extract_text_returns_empty_string_when_both_extractors_fail() -> None:
    # when
    with (
        patch("src.reader.extraction.trafilatura.extract", side_effect=ValueError("bad html")),
        patch(
            "src.reader.extraction._readability_extract",
            return_value=_structured("", "readability"),
        ),
    ):
        result = extract_text_with_fallback(_GOOD_HTML)

    # then
    assert result == ""


def test_embedded_metadata_holds_the_product_block_in_every_syntax() -> None:
    # when
    metadata = extract_embedded_metadata(_PRODUCT_HTML)

    # then
    assert metadata["json-ld"][0]["name"] == "Northwind Lamp"
    assert metadata["json-ld"][0]["offers"]["price"] == "45.99"
    assert metadata["microdata"][0]["name"] == "Northwind Lamp"
    assert metadata["microdata"][0]["price"] == "45.99"
    assert metadata["opengraph"][0]["og:title"] == "Northwind Lamp"


def test_embedded_metadata_parse_error_leaves_metadata_empty() -> None:
    # when
    with patch("src.reader.extraction.extruct_extract", side_effect=ValueError("bad markup")):
        metadata = extract_embedded_metadata(_GOOD_HTML)

    # then
    assert metadata == {}


def test_extract_structured_carries_metadata_beside_the_article_fields() -> None:
    # when
    result = extract_structured(_PRODUCT_HTML)

    # then
    assert result["metadata"]["json-ld"][0]["name"] == "Northwind Lamp"
    assert result["title"] or result["content"]


_TABLE_HTML = """
<html><body><article>
<p>This opening paragraph explains the quarterly figures in plain sentences for everyone.</p>
<table><tr><th>Product name</th><th>Quarterly revenue</th></tr>
<tr><td>Red Widget</td><td>Nineteen thousand dollars in the first quarter</td></tr>
<tr><td>Blue Widget</td><td>Twenty one thousand dollars in the first quarter</td></tr>
</table>
<table><tr><td>Lonely cell</td></tr></table>
</article></body></html>
"""


def test_extract_tables_returns_rows_cell_for_cell() -> None:
    # when
    tables = extract_tables(_TABLE_HTML)

    # then
    assert tables == [
        [
            ["Product name", "Quarterly revenue"],
            ["Red Widget", "Nineteen thousand dollars in the first quarter"],
            ["Blue Widget", "Twenty one thousand dollars in the first quarter"],
        ],
        [["Lonely cell"]],
    ]


def test_extract_tables_skips_empty_rows_and_tables() -> None:
    # when
    tables = extract_tables("<html><body><table><tr></tr><tr><th></th></tr></table></body></html>")

    # then
    assert tables == []


def test_extract_tables_without_tables_is_empty() -> None:
    assert extract_tables(_GOOD_HTML) == []


def test_extract_tables_parse_error_is_empty() -> None:
    # when
    with patch("src.reader.extraction.BeautifulSoup", side_effect=ValueError("bad markup")):
        tables = extract_tables(_GOOD_HTML)

    # then
    assert tables == []
