"""Tasks 5.1, 5.2 and 5.3: formats, tables, screenshot and the schema cache key."""

import base64
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.api.exceptions import ScreenshotUnavailableError
from src.reader.document_router import RouteResult
from src.reader.web_reader import WebReader, _cache_key

_PNG = b"\x89PNG\r\n\x1afake-png-bytes"

_ARTICLE_HTML = (
    "<html><head><title>Article</title></head>"
    "<body><article><p>"
    "This is a genuine paragraph of article content with more than ten words in it. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    "</p></article></body></html>"
)

_TABLE_HTML = (
    "<html><head><title>Data</title></head><body><article>"
    "<p>This opening paragraph explains the quarterly figures in plain sentences for everyone.</p>"
    "<table><tr><th>Product name</th><th>Quarterly revenue</th></tr>"
    "<tr><td>Red Widget</td><td>Nineteen thousand dollars in the first quarter</td></tr>"
    "<tr><td>Blue Widget</td><td>Twenty one thousand dollars in the first quarter</td></tr>"
    "</table></article></body></html>"
)

_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"name": {"type": "string"}, "price": {"type": "number"}},
    "required": ["name", "price"],
}


class _StubStrategy:
    def __init__(self, html: str = _ARTICLE_HTML, png: bytes | None = _PNG) -> None:
        self._html = html
        self._png = png
        self.capture_calls = 0

    async def extract(self, _url: str) -> str:
        return self._html

    async def get_html(self, _url: str) -> str:
        return self._html

    async def screenshot_page(self, _url: str) -> tuple[str, bytes | None] | None:
        self.capture_calls += 1
        if self._png is None:
            return None
        return self._html, self._png


class _PlainStrategy:
    def __init__(self, html: str = _ARTICLE_HTML) -> None:
        self._html = html

    async def extract(self, _url: str) -> str:
        return self._html

    async def get_html(self, _url: str) -> str:
        return self._html


def _strategies(reader: WebReader, stub: Any, name: str = "1-beautifulsoup") -> Any:
    return patch.object(reader, "_select_strategies", new=AsyncMock(return_value={name: stub}))


def test_schema_hash_splits_cache_entries() -> None:
    # when
    first = _cache_key("https://example.com/", False, False, None, "schema", None, "aaa")
    second = _cache_key("https://example.com/", False, False, None, "schema", None, "bbb")
    text = _cache_key("https://example.com/", False, False, None, "text", None, "")

    # then
    assert first != second
    assert first != text


@pytest.mark.asyncio
async def test_screenshot_read_runs_twice_and_is_never_cached() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy()

    # when
    with _strategies(reader, stub, "4-playwright_stealth"):
        first = await reader.read("https://example.com/", output_format="screenshot")
        second = await reader.read("https://example.com/", output_format="screenshot")

    # then
    assert first["content"] == base64.b64encode(_PNG).decode("ascii")
    assert second["content"] == first["content"]
    assert stub.capture_calls == 2
    assert first["status"] == "success"


@pytest.mark.asyncio
async def test_screenshot_served_by_non_browser_tier_is_unavailable() -> None:
    # given
    reader = WebReader()
    stub = _PlainStrategy()

    # when / then
    with (
        _strategies(reader, stub, "1-beautifulsoup"),
        pytest.raises(ScreenshotUnavailableError),
    ):
        await reader.read("https://example.com/", output_format="screenshot")


@pytest.mark.asyncio
async def test_screenshot_capture_failure_fails_the_tier() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(png=None)

    # when
    with _strategies(reader, stub, "4-playwright_stealth"):
        result = await reader.read("https://example.com/", output_format="screenshot")

    # then
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_tables_format_returns_rows_cell_for_cell() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=_TABLE_HTML)

    # when
    with _strategies(reader, stub):
        result = await reader.read("https://example.com/", output_format="tables")

    # then
    assert result["status"] == "success"
    assert result["tables"] == [
        [
            ["Product name", "Quarterly revenue"],
            ["Red Widget", "Nineteen thousand dollars in the first quarter"],
            ["Blue Widget", "Twenty one thousand dollars in the first quarter"],
        ]
    ]


@pytest.mark.asyncio
async def test_tables_format_without_tables_fails_the_tier() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=_ARTICLE_HTML)

    # when
    with _strategies(reader, stub):
        result = await reader.read("https://example.com/", output_format="tables")

    # then
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_tables_format_with_thin_cells_fails_validation() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=_ARTICLE_HTML + "<table><tr><td>Hi</td></tr></table>")

    # when
    with _strategies(reader, stub):
        result = await reader.read("https://example.com/", output_format="tables")

    # then
    assert result["status"] == "error"


@pytest.mark.asyncio
async def test_schema_replay_skips_the_model() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy()
    selectors = {"name": "h1.product", "price": ".price"}
    html = (
        "<html><body><h1 class='product'>Red Widget</h1>"
        "<span class='price'>19.99</span>"
        "<p>This is a genuine paragraph of article content with more than ten words in it.</p>"
        "</body></html>"
    )
    stub._html = html

    # when
    with (
        _strategies(reader, stub),
        patch("src.reader.web_reader.recipe_lookup", new=AsyncMock(return_value=selectors)),
        patch("src.reader.web_reader.run_schema_model", new=AsyncMock()) as model,
    ):
        result = await reader.read("https://example.com/", output_format="schema", extraction_schema=_SCHEMA)

    # then
    assert result["content"]["name"] == "Red Widget"
    assert result["recipe"] == "replay"
    model.assert_not_awaited()


@pytest.mark.asyncio
async def test_schema_drift_rebuilds_the_recipe() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=_ARTICLE_HTML)
    selectors = {"name": "h1.product", "price": ".price"}

    # when
    with (
        _strategies(reader, stub),
        patch("src.reader.web_reader.recipe_lookup", new=AsyncMock(return_value=selectors)),
        patch("src.reader.web_reader.recipe_delete", new=AsyncMock()) as deleted,
        patch(
            "src.reader.web_reader.run_schema_model",
            new=AsyncMock(return_value=({"name": "Red Widget", "price": 19.99}, selectors)),
        ) as model,
        patch("src.reader.web_reader.recipe_store_put", new=AsyncMock()) as stored,
    ):
        result = await reader.read("https://example.com/", output_format="schema", extraction_schema=_SCHEMA)

    # then
    assert result["content"]["name"] == "Red Widget"
    assert result["recipe"] == "model"
    model.assert_awaited_once()
    deleted.assert_awaited_once()
    stored.assert_awaited_once()


@pytest.mark.asyncio
async def test_screenshot_format_direct_route_is_not_cached() -> None:
    # given
    reader = WebReader()

    # when
    with patch(
        "src.reader.web_reader.route_document",
        new=AsyncMock(return_value=RouteResult("pdf", "# Canary PDF text", None)),
    ) as routed:
        first = await reader.read("https://cdn.example.com/doc.pdf", output_format="screenshot")
        second = await reader.read("https://cdn.example.com/doc.pdf", output_format="screenshot")

    # then
    assert first["content"] == "# Canary PDF text"
    assert second["content"] == "# Canary PDF text"
    assert routed.await_count == 2
    assert reader._memory_cache == {}


@pytest.mark.asyncio
async def test_schema_without_schema_fails_the_tier() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy()

    # when
    result = await reader._execute_strategy(
        "1-beautifulsoup", stub, "https://example.com/", output_format="schema"
    )

    # then
    assert result is None


@pytest.mark.asyncio
async def test_schema_without_schema_raises() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy()

    # when / then
    with (
        _strategies(reader, stub),
        pytest.raises(ValueError, match="extraction_schema is required"),
    ):
        await reader.read("https://example.com/", output_format="schema")


@pytest.mark.asyncio
async def test_unknown_format_falls_back_to_text() -> None:
    # given
    from typing import cast

    reader = WebReader()
    stub = _StubStrategy()

    # when
    result = await reader._execute_strategy(
        "1-beautifulsoup", stub, "https://example.com/", output_format=cast("Any", "yaml")
    )

    # then
    assert result is not None
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_screenshot_result_without_capture_raises() -> None:
    # given
    from src.api.exceptions import ScreenshotUnavailableError

    reader = WebReader()
    stub = _PlainStrategy()

    # when / then
    with pytest.raises(ScreenshotUnavailableError, match="cannot produce a screenshot"):
        await reader._execute_strategy(
            "1-beautifulsoup", stub, "https://example.com/", output_format="screenshot"
        )


@pytest.mark.asyncio
async def test_direct_pdf_route_returns_markdown() -> None:
    # given
    reader = WebReader()

    # when
    with patch(
        "src.reader.web_reader.route_document",
        new=AsyncMock(return_value=RouteResult("pdf", "# Canary PDF text", None)),
    ):
        result = await reader.read("https://cdn.example.com/doc.pdf")

    # then
    assert result["status"] == "success"
    assert result["content"] == "# Canary PDF text"
    assert result["route"] == "pdf"


@pytest.mark.asyncio
async def test_direct_route_failure_returns_routing_error() -> None:
    # given
    reader = WebReader()

    # when
    with patch(
        "src.reader.web_reader.route_document",
        new=AsyncMock(return_value=RouteResult("pdf", None, "download_failed")),
    ) as routed:
        result = await reader.read("https://cdn.example.com/doc.pdf")

    # then
    assert result["reason"] == "routing_error"
    assert result["routing_error"] == "download_failed"
    routed.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_pdf_link_routes_and_replaces_content() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=_ARTICLE_HTML + '<a href="https://cdn.example.com/files/doc.pdf">PDF</a>')

    # when
    with (
        _strategies(reader, stub),
        patch(
            "src.reader.web_reader.route_document",
            new=AsyncMock(side_effect=[None, RouteResult("pdf", "# Linked PDF text", None)]),
        ),
    ):
        result = await reader.read("https://example.com/page")

    # then
    assert result["content"] == "# Linked PDF text"
    assert result["route"] == "pdf"


@pytest.mark.asyncio
async def test_blocked_main_pdf_link_keeps_page_text_with_routing_error() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(
        html=_ARTICLE_HTML + '<a href="http://e2e-fake-site-blocked:7031/files/canary.pdf">PDF</a>'
    )

    # when
    with (
        _strategies(reader, stub),
        patch(
            "src.reader.web_reader.route_document",
            new=AsyncMock(side_effect=[None, RouteResult("pdf", None, "download_failed")]),
        ),
    ):
        result = await reader.read("https://example.com/page")

    # then
    assert result["status"] == "success"
    assert result["routing_error"] == "download_failed"
    assert result["route"] == "pdf"


@pytest.mark.asyncio
async def test_page_without_pdf_link_reads_as_before() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=_ARTICLE_HTML + '<a href="https://example.com/other">Other</a>')

    # when
    with (
        _strategies(reader, stub),
        patch("src.reader.web_reader.route_document", new=AsyncMock(return_value=None)) as routed,
    ):
        result = await reader.read("https://example.com/page")

    # then
    assert result["status"] == "success"
    assert "routing_error" not in result
    routed.assert_awaited_once()


@pytest.mark.asyncio
async def test_screenshot_challenge_wall_falls_through() -> None:
    # given
    reader = WebReader()
    wall = "<html><body><div id='cf-challenge-running'></div></body></html>"
    stub = _StubStrategy(html=wall)

    # when
    with _strategies(reader, stub, "4-playwright_stealth"):
        result = await reader.read("https://example.com/", output_format="screenshot")

    # then
    assert result["status"] == "error"
