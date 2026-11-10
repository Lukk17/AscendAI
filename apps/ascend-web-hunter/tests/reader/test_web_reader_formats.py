"""Tasks 5.1, 5.2 and 5.3: formats, tables, screenshot and the schema cache key."""

import base64
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import httpx
import pytest

from src.api.exceptions import ExtractionFailedError, ScreenshotUnavailableError
from src.reader.document_router import RouteResult
from src.reader.recipe_store import lookup as recipe_lookup
from src.reader.schema_extraction import schema_hash
from src.reader.web_reader import WebReader, _cache_key

_PNG = b"\x89PNG\r\n\x1afake-png-bytes"

_ARTICLE_HTML = (
    "<html><head><title>Article</title></head>"
    "<body><article><p>"
    "This is a genuine paragraph of article content with more than ten words in it. "
    "It continues with a second sentence so the extractor has plenty of real prose to work with."
    "</p></article></body></html>"
)

_WRAPPER_TEXT = "The HALCYON-PLOVER index lists one sealed PDF under glass."


def _wrapper_html(pdf_href: str) -> str:
    return (
        "<html><head><title>Sealed memorandum</title></head><body><article>"
        f'<p>{_WRAPPER_TEXT}</p><a href="{pdf_href}">sealed memorandum</a>'
        "</article></body></html>"
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
async def test_document_wide_recipe_is_never_replayed() -> None:
    # given
    reader = WebReader()
    html = (
        "<html><body><h1 class='product'>Red Widget</h1><span class='price'>19.99</span>"
        "<p>This is a genuine paragraph of article content with more than ten words in it.</p>"
        "</body></html>"
    )
    stub = _StubStrategy(html=html)

    # when
    with (
        _strategies(reader, stub),
        patch(
            "src.reader.web_reader.recipe_lookup",
            new=AsyncMock(return_value={"name": "body", "price": ".price"}),
        ),
        patch("src.reader.web_reader.recipe_delete", new=AsyncMock()) as deleted,
        patch(
            "src.reader.web_reader.run_schema_model",
            new=AsyncMock(return_value=({"name": "Red Widget", "price": 19.99}, {"name": "h1.product"})),
        ) as model,
        patch("src.reader.web_reader.recipe_store_put", new=AsyncMock()) as stored,
    ):
        result = await reader.read("https://example.com/", output_format="schema", extraction_schema=_SCHEMA)

    # then
    assert result["content"] == {"name": "Red Widget", "price": 19.99}
    assert result["recipe"] == "model"
    deleted.assert_awaited_once()
    model.assert_awaited_once()
    assert stored.await_args is not None
    assert stored.await_args.args[3] == html


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


def _two_tier_ladder(reader: WebReader, html: str = _ARTICLE_HTML) -> tuple[Any, Any, Any]:
    first = MagicMock()
    first.get_html = AsyncMock(return_value=html)
    second = MagicMock()
    second.get_html = AsyncMock(return_value=html)
    selection = patch.object(
        reader,
        "_select_strategies",
        new=AsyncMock(return_value={"1-beautifulsoup": first, "2-trafilatura": second}),
    )

    return selection, first, second


@pytest.mark.asyncio
async def test_oversized_schema_is_refused_before_any_tier_runs() -> None:
    # given
    reader = WebReader()
    selection, first, second = _two_tier_ladder(reader)

    # when / then
    with (
        selection,
        patch("src.reader.schema_extraction.settings.EXTRACTION_SCHEMA_MAX_BYTES", 16),
        pytest.raises(ValueError, match="EXTRACTION_SCHEMA_MAX_BYTES"),
    ):
        await reader.read("https://example.com/", output_format="schema", extraction_schema=_SCHEMA)

    first.get_html.assert_not_awaited()
    second.get_html.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreachable_extraction_model_fails_the_read_once() -> None:
    # given
    reader = WebReader()
    selection, first, second = _two_tier_ladder(reader)

    def refuse(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    real_client = httpx.AsyncClient

    def client_factory(*_args: object, **_kwargs: object) -> httpx.AsyncClient:
        return real_client(transport=httpx.MockTransport(refuse))

    # when / then
    with (
        selection,
        patch("src.reader.schema_extraction.settings.EXTRACTION_LLM_BASE_URL", "https://llm.example.com/v1"),
        patch("src.reader.schema_extraction.httpx.AsyncClient", side_effect=client_factory),
        patch("src.reader.web_reader.recipe_lookup", new=AsyncMock(return_value=None)),
        pytest.raises(ExtractionFailedError, match="ConnectError"),
    ):
        await reader.read("https://example.com/", output_format="schema", extraction_schema=_SCHEMA)

    first.get_html.assert_awaited_once()
    second.get_html.assert_not_awaited()


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
async def test_direct_route_failure_returns_the_html_extraction_with_routing_error() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy()

    # when
    with (
        _strategies(reader, stub),
        patch(
            "src.reader.web_reader.route_document",
            new=AsyncMock(return_value=RouteResult("pdf", None, "download_failed")),
        ) as routed,
    ):
        result = await reader.read("https://cdn.example.com/doc.pdf")

    # then
    assert result["status"] == "success"
    assert "genuine paragraph of article content" in result["content"]
    assert result["mode"] == "1-beautifulsoup"
    assert result["route"] == "pdf"
    assert result["routing_error"] == "download_failed"
    routed.assert_awaited_once()


@pytest.mark.asyncio
async def test_direct_route_failure_is_not_cached() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy()

    # when
    with (
        _strategies(reader, stub),
        patch(
            "src.reader.web_reader.route_document",
            new=AsyncMock(return_value=RouteResult("pdf", None, "download_failed")),
        ) as routed,
    ):
        await reader.read("https://cdn.example.com/doc.pdf")
        await reader.read("https://cdn.example.com/doc.pdf")

    # then
    assert routed.await_count == 2
    assert reader._memory_cache == {}


@pytest.mark.asyncio
async def test_direct_route_failure_with_every_tier_failing_still_names_the_routing_error() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html="")

    # when
    with (
        _strategies(reader, stub),
        patch(
            "src.reader.web_reader.route_document",
            new=AsyncMock(return_value=RouteResult("pdf", None, "download_failed")),
        ),
    ):
        result = await reader.read("https://cdn.example.com/doc.pdf")

    # then
    assert result["status"] == "error"
    assert result["reason"] == "all_tiers_failed"
    assert result["route"] == "pdf"
    assert result["routing_error"] == "download_failed"


def _tier_that_must_not_run() -> MagicMock:
    tier = MagicMock()
    tier.extract = AsyncMock(return_value=_ARTICLE_HTML)
    tier.get_html = AsyncMock(return_value=_ARTICLE_HTML)

    return tier


@pytest.mark.asyncio
async def test_a_document_refused_for_its_size_ends_the_read_with_no_tier() -> None:
    # given
    reader = WebReader()
    tier = _tier_that_must_not_run()

    # when
    with (
        _strategies(reader, tier),
        patch(
            "src.reader.web_reader.route_document",
            new=AsyncMock(return_value=RouteResult("pdf", None, "file_too_large")),
        ),
    ):
        result = await reader.read("http://cdn.example.com/oversized.pdf")

    # then
    assert result == {
        "content": "",
        "status": "error",
        "reason": "routing_error",
        "route": "pdf",
        "routing_error": "file_too_large",
    }
    tier.extract.assert_not_awaited()
    tier.get_html.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_document_refused_for_its_size_is_not_cached() -> None:
    # given
    reader = WebReader()

    # when
    with (
        _strategies(reader, _tier_that_must_not_run()),
        patch(
            "src.reader.web_reader.route_document",
            new=AsyncMock(return_value=RouteResult("pdf", None, "file_too_large")),
        ) as routed,
    ):
        await reader.read("http://cdn.example.com/oversized.pdf")
        await reader.read("http://cdn.example.com/oversized.pdf")

    # then
    assert routed.await_count == 2
    assert reader._memory_cache == {}


@pytest.mark.asyncio
async def test_a_main_pdf_link_refused_for_its_size_keeps_the_page_text() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=_wrapper_html("/files/oversized.pdf"))

    # when
    with (
        _strategies(reader, stub),
        patch(
            "src.reader.web_reader.route_document",
            new=AsyncMock(side_effect=[None, RouteResult("pdf", None, "file_too_large")]),
        ),
    ):
        result = await reader.read("https://example.com/page")

    # then
    assert result["status"] == "success"
    assert "HALCYON-PLOVER" in result["content"]
    assert result["routing_error"] == "file_too_large"


@pytest.mark.asyncio
async def test_document_wrapper_page_routes_its_pdf_and_replaces_content() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=_wrapper_html("/files/doc.pdf"))

    # when
    with (
        _strategies(reader, stub),
        patch(
            "src.reader.web_reader.route_document",
            new=AsyncMock(side_effect=[None, RouteResult("pdf", "# Linked PDF text", None)]),
        ) as routed,
    ):
        result = await reader.read("https://example.com/page")

    # then
    assert result["content"] == "# Linked PDF text"
    assert result["route"] == "pdf"
    assert routed.await_args_list[1].args[0] == "https://example.com/files/doc.pdf"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "html",
    [
        pytest.param(
            _ARTICLE_HTML + '<a href="https://cdn.example.com/files/doc.pdf">PDF</a>',
            id="article-with-one-pdf-link",
        ),
        pytest.param(
            _ARTICLE_HTML.replace(
                "</article>",
                '<a href="https://example.com/">Home</a><a href="https://cdn.example.com/doc.pdf">PDF</a></article>',
            ),
            id="article-with-many-links",
        ),
        pytest.param(
            _wrapper_html("/files/doc.pdf").replace(
                "</article>", '<a href="/files/annex.pdf">annex</a></article>'
            ),
            id="thin-page-with-two-pdfs",
        ),
    ],
)
async def test_pdf_link_on_a_page_that_is_not_a_wrapper_keeps_the_page(html: str) -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=html)

    # when
    with (
        _strategies(reader, stub),
        patch("src.reader.web_reader.route_document", new=AsyncMock(return_value=None)) as routed,
    ):
        result = await reader.read("https://example.com/page")

    # then
    assert result["status"] == "success"
    assert "route" not in result
    assert "routing_error" not in result
    routed.assert_awaited_once_with("https://example.com/page")


@pytest.mark.asyncio
async def test_blocked_main_pdf_link_keeps_page_text_with_routing_error() -> None:
    # given
    reader = WebReader()
    stub = _StubStrategy(html=_wrapper_html("http://e2e-fake-site-blocked:7031/files/canary.pdf"))

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
    assert "HALCYON-PLOVER" in result["content"]
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


_PRODUCT_HTML = (
    "<html><head><title>Red Widget</title><script>track('view')</script>"
    "<style>.price { color: red }</style></head><body><!-- shop page -->"
    "<article><h1 class='product' data-tracking='abc'>Red Widget</h1><span class='price'>19.99</span>"
    "<p>This is a genuine paragraph of product text with more than ten words in it, "
    "so the second look accepts the page as real content.</p></article></body></html>"
)

_PRODUCT_VALUES: dict[str, Any] = {"name": "Red Widget", "price": 19.99}


@pytest.fixture
def recipe_redis() -> Any:
    with patch(
        "src.reader.recipe_store._RecipeClientHolder.client",
        fakeredis.aioredis.FakeRedis(decode_responses=True),
    ) as client:
        yield client


def _schema_reads(html: str, model: AsyncMock) -> Any:
    reader = WebReader()

    return (
        reader,
        patch.object(
            reader,
            "_select_strategies",
            new=AsyncMock(return_value={"1-beautifulsoup": _StubStrategy(html=html)}),
        ),
        patch("src.reader.web_reader.run_schema_model", new=model),
    )


@pytest.mark.asyncio
async def test_the_model_is_given_the_cleaned_markup_of_the_page() -> None:
    # given
    model = AsyncMock(return_value=(_PRODUCT_VALUES, {}))
    reader, selection, patched_model = _schema_reads(_PRODUCT_HTML, model)

    # when
    with selection, patched_model:
        await reader.read("https://markup.example/", output_format="schema", extraction_schema=_SCHEMA)

    # then
    assert model.await_args is not None
    sent = model.await_args.args[0]
    assert '<h1 class="product">Red Widget</h1>' in sent
    assert '<span class="price">19.99</span>' in sent
    assert "<script" not in sent
    assert "<style" not in sent
    assert "shop page" not in sent
    assert "data-tracking" not in sent


@pytest.mark.asyncio
async def test_selectors_that_match_nothing_are_never_stored(recipe_redis: Any) -> None:
    # given
    model = AsyncMock(return_value=(_PRODUCT_VALUES, {"name": "h2", "price": ".cost"}))
    first_reader, first_selection, first_model = _schema_reads(_PRODUCT_HTML, model)
    second_reader, second_selection, second_model = _schema_reads(_PRODUCT_HTML, model)

    # when
    with first_selection, first_model:
        first = await first_reader.read(
            "https://nothing.example/", output_format="schema", extraction_schema=_SCHEMA
        )
    stored = await recipe_lookup("nothing.example", schema_hash(_SCHEMA))
    with second_selection, second_model:
        second = await second_reader.read(
            "https://nothing.example/", output_format="schema", extraction_schema=_SCHEMA
        )

    # then
    assert first["content"] == _PRODUCT_VALUES
    assert first["recipe"] == "model"
    assert stored is None
    assert second["recipe"] == "model"
    assert model.await_count == 2


@pytest.mark.asyncio
async def test_selectors_that_give_other_values_than_the_model_are_never_stored(recipe_redis: Any) -> None:
    # given
    model = AsyncMock(return_value=(_PRODUCT_VALUES, {"name": "title", "price": "p"}))
    reader, selection, patched_model = _schema_reads(_PRODUCT_HTML, model)

    # when
    with selection, patched_model:
        result = await reader.read(
            "https://other.example/", output_format="schema", extraction_schema=_SCHEMA
        )

    # then
    assert result["content"] == _PRODUCT_VALUES
    assert await recipe_lookup("other.example", schema_hash(_SCHEMA)) is None


@pytest.mark.asyncio
async def test_selectors_that_reproduce_the_model_values_are_stored_and_replayed(recipe_redis: Any) -> None:
    # given
    selectors = {"name": "h1.product", "price": ".price"}
    model = AsyncMock(return_value=(_PRODUCT_VALUES, selectors))
    first_reader, first_selection, first_model = _schema_reads(_PRODUCT_HTML, model)
    second_reader, second_selection, second_model = _schema_reads(_PRODUCT_HTML, model)

    # when
    with first_selection, first_model:
        first = await first_reader.read(
            "https://heal.example/", output_format="schema", extraction_schema=_SCHEMA
        )
    with second_selection, second_model:
        second = await second_reader.read(
            "https://heal.example/", output_format="schema", extraction_schema=_SCHEMA
        )

    # then
    assert first["recipe"] == "model"
    assert second["recipe"] == "replay"
    assert second["content"] == _PRODUCT_VALUES
    assert model.await_count == 1
