from unittest.mock import AsyncMock, patch

import pytest
from ascend_python_common.uri_guard import UnsafeUriError

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.api.mcp import mcp_server
from src.api.mcp.mcp_server import (
    session_clear,
    session_establish,
    session_interventions,
    session_status,
    web_read,
    web_search,
)
from src.reader.strategies.base_strategy import FetchedHtml
from src.session.session_manager import EstablishedFlow, SessionInfo, SessionManager


@pytest.mark.asyncio
async def test_mcp_web_search_returns_results() -> None:
    # given
    mock_results = [{"title": "MCP", "url": "url"}]

    # when
    with patch(
        "src.api.mcp.mcp_server.search_client.search",
        new_callable=AsyncMock,
    ) as mock_search:
        mock_search.return_value = mock_results
        result = await web_search("query", 5)

    # then
    assert result == mock_results


@pytest.mark.asyncio
async def test_mcp_web_search_empty_query_raises() -> None:
    # given
    bad_query = ""

    # when
    with pytest.raises(Exception, match=r"^validation: .*empty") as exc_info:
        await web_search(bad_query)

    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_mcp_web_search_whitespace_only_raises() -> None:
    # given
    bad_query = "   "

    # when
    with pytest.raises(Exception, match=r"^validation: .*empty") as exc_info:
        await web_search(bad_query)

    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_mcp_web_search_too_long_raises() -> None:
    # given
    bad_query = "x" * 501

    # when
    with pytest.raises(Exception, match=r"^validation: .*maximum length") as exc_info:
        await web_search(bad_query)

    # then
    assert str(exc_info.value).startswith("validation: ")


@pytest.mark.asyncio
async def test_mcp_web_read_unsafe_url_raises() -> None:
    # given
    bad_url = "http://127.0.0.1"

    # when
    with patch(
        "src.api.mcp.mcp_server.check_fetch_uri",
        side_effect=UnsafeUriError("URI resolves to a non-public address"),
    ):
        with pytest.raises(Exception, match=r"^unsafe_uri: ") as exc_info:
            await web_read(bad_url)

    # then
    assert str(exc_info.value).startswith("unsafe_uri: ")


@pytest.mark.asyncio
async def test_mcp_web_read_calls_read_when_include_links_false() -> None:
    # given
    mock_content = {"content": "MCP Content", "status": "success", "mode": "1-beautifulsoup"}

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            return_value=mock_content,
        ) as mock_read,
    ):
        result = await web_read("http://mcp.com")

    # then
    assert result == mock_content
    mock_read.assert_awaited_once_with(
        "http://mcp.com",
        heavy_mode=False,
        profile=None,
        output_format="text",
        tier=None,
        extraction_schema=None,
    )


@pytest.mark.asyncio
async def test_mcp_web_read_calls_read_with_links_when_include_links_true() -> None:
    # given
    mock_result = {
        "content": "Job title [1]",
        "links": {1: "https://example.com/job1"},
        "status": "success",
    }

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read_with_links",
            new_callable=AsyncMock,
            return_value=mock_result,
        ) as mock_read,
    ):
        result = await web_read("http://mcp.com", include_links=True, link_filter="/job/")

    # then
    assert result["status"] == "success"
    mock_read.assert_awaited_once_with(
        "http://mcp.com", "/job/", heavy_mode=False, profile=None, output_format="text", tier=None
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("include_links", [True, False])
async def test_mcp_web_read_result_carries_no_cache_validators(include_links: bool) -> None:
    # given a tier whose final answer carried ETag and Last-Modified
    page = FetchedHtml(
        "<html><body><article><p>"
        + "public answer words " * 20
        + '<a href="/next">next</a></p></article></body></html>',
        {"etag": '"public"', "last-modified": "Mon"},
    )

    async def tier_html(name: object, strategy: object, url: str) -> str:
        return page

    # when
    with (
        patch.object(mcp_server.web_reader, "_novnc_or_tier_html", side_effect=tier_html),
        patch.object(mcp_server.web_reader.validator, "validate", return_value=True),
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
    ):
        result = await web_read(
            f"https://mcp-validators-{include_links}.example.com/", include_links=include_links
        )

    # then
    assert result["status"] == "success"
    assert "etag" not in result
    assert "last_modified" not in result


@pytest.mark.asyncio
async def test_mcp_web_read_catches_human_intervention_and_returns_structured_payload() -> None:
    # given
    exc = HumanInterventionRequiredException(vnc_url="http://vnc/x", intervention_type="captcha")

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://mcp.com")

    # then
    assert result["status"] == "human_intervention_required"
    assert result["intervention_type"] == "captcha"
    assert result["vnc_url"] == "http://vnc/x"
    assert "vnc/x" in result["message"]


@pytest.mark.asyncio
async def test_mcp_web_read_human_intervention_on_links_branch() -> None:
    # given
    exc = HumanInterventionRequiredException(vnc_url="http://vnc/y", intervention_type="login")

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read_with_links",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://mcp.com", include_links=True)

    # then
    assert result["intervention_type"] == "login"


@pytest.mark.asyncio
async def test_mcp_web_read_intervention_carries_flow_fields() -> None:
    # given
    window = {"slot": 1, "x": 48, "y": 48, "width": 1280, "height": 800}
    exc = HumanInterventionRequiredException(
        vnc_url="http://vnc/x",
        intervention_type="captcha",
        flow_id="9f2c41ab77de",
        joined=True,
        window=window,
    )

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://mcp.com")

    # then
    assert result["status"] == "human_intervention_required"
    assert result["intervention_type"] == "captcha"
    assert result["vnc_url"] == "http://vnc/x"
    assert "vnc/x" in result["message"]
    assert result["flow_id"] == "9f2c41ab77de"
    assert result["joined"] is True
    assert result["window"] == window


@pytest.mark.asyncio
async def test_mcp_web_read_intervention_defaults_present_for_plain_raise() -> None:
    # given
    exc = HumanInterventionRequiredException(vnc_url="http://vnc/x", intervention_type="captcha")

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://mcp.com")

    # then
    assert result["status"] == "human_intervention_required"
    assert result["intervention_type"] == "captcha"
    assert result["vnc_url"] == "http://vnc/x"
    assert "vnc/x" in result["message"]
    assert result["flow_id"] is None
    assert result["joined"] is False
    assert result["window"] is None


@pytest.mark.asyncio
async def test_mcp_web_read_catches_novnc_busy_and_returns_structured_payload() -> None:
    # given
    exc = NoVNCFlowBusyException("http://in-flight.example", "default")

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://mcp.com")

    # then
    assert result["status"] == "novnc_busy"
    assert result["holder_url"] == "http://in-flight.example"
    assert result["holder_profile"] == "default"


@pytest.mark.asyncio
async def test_mcp_web_read_busy_carries_cap_fields() -> None:
    # given
    flows = [
        {
            "flow_id": "9f2c41ab77de",
            "url": "https://nowsecure.nl",
            "domain": "nowsecure.nl",
            "profile": "default",
            "intervention_type": "captcha",
            "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
            "age_seconds": 207.3,
            "expires_in_seconds": 412.7,
            "vnc_url": "http://vnc/x",
        }
    ]
    exc = NoVNCFlowBusyException(
        "https://nowsecure.nl",
        "default",
        active_flows=1,
        max_concurrent_flows=4,
        flows=flows,
    )

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new_callable=AsyncMock,
            side_effect=exc,
        ),
    ):
        result = await web_read("http://mcp.com")

    # then
    assert result["status"] == "novnc_busy"
    assert result["holder_url"] == "https://nowsecure.nl"
    assert result["holder_profile"] == "default"
    assert result["active_flows"] == 1
    assert result["max_concurrent_flows"] == 4
    assert result["flows"] == flows


# ---------------------------------------------------------------------------
# session_establish MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_session_establish_returns_human_intervention_payload() -> None:
    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch.object(
            SessionManager,
            "establish",
            new=AsyncMock(
                return_value=EstablishedFlow(
                    vnc_url="http://vnc:7900",
                    intervention_type="login",
                    flow_id="9f2c41ab77de",
                    joined=False,
                    window={"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
                )
            ),
        ),
    ):
        result = await session_establish("http://example.com")

    # then
    assert result["status"] == "human_intervention_required"
    assert result["intervention_type"] == "login"
    assert result["vnc_url"] == "http://vnc:7900"
    assert "http://vnc:7900" in result["message"]


@pytest.mark.asyncio
async def test_mcp_session_establish_answers_the_real_flow_values() -> None:
    """A joined captcha flow answers its own type, flow_id, joined and window."""
    # given
    window = {"slot": 3, "x": 144, "y": 144, "width": 1280, "height": 800}
    established = EstablishedFlow(
        vnc_url="http://vnc:7900",
        intervention_type="captcha",
        flow_id="0123456789ab",
        joined=True,
        window=window,
    )

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "establish", new=AsyncMock(return_value=established)),
    ):
        result = await session_establish("http://example.com")

    # then
    assert result == {
        "status": "human_intervention_required",
        "intervention_type": "captcha",
        "vnc_url": "http://vnc:7900",
        "flow_id": "0123456789ab",
        "joined": True,
        "window": window,
        "message": "Login required. Please visit: http://vnc:7900",
    }


@pytest.mark.asyncio
async def test_mcp_session_establish_unsafe_url_raises() -> None:
    # given
    bad_url = "http://10.0.0.1"

    # when
    with patch(
        "src.api.mcp.mcp_server.check_fetch_uri",
        side_effect=UnsafeUriError("URI resolves to a non-public address"),
    ):
        with pytest.raises(Exception, match=r"^unsafe_uri: ") as exc_info:
            await session_establish(bad_url)

    # then
    assert str(exc_info.value).startswith("unsafe_uri: ")


@pytest.mark.asyncio
async def test_mcp_session_establish_returns_novnc_busy_payload() -> None:
    # given
    exc = NoVNCFlowBusyException("http://in-flight.example", "default")

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "establish", new=AsyncMock(side_effect=exc)),
    ):
        result = await session_establish("http://example.com")

    # then
    assert result["status"] == "novnc_busy"
    assert result["holder_url"] == "http://in-flight.example"
    assert result["holder_profile"] == "default"


@pytest.mark.asyncio
async def test_mcp_session_establish_busy_carries_cap_fields() -> None:
    # given
    flows = [
        {
            "flow_id": "9f2c41ab77de",
            "url": "https://nowsecure.nl",
            "domain": "nowsecure.nl",
            "profile": "default",
            "intervention_type": "captcha",
            "window": {"slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800},
            "age_seconds": 207.3,
            "expires_in_seconds": 412.7,
            "vnc_url": "http://vnc/x",
        }
    ]
    exc = NoVNCFlowBusyException(
        "https://nowsecure.nl",
        "default",
        active_flows=1,
        max_concurrent_flows=4,
        flows=flows,
    )

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "establish", new=AsyncMock(side_effect=exc)),
    ):
        result = await session_establish("http://example.com")

    # then
    assert result["status"] == "novnc_busy"
    assert result["active_flows"] == 1
    assert result["max_concurrent_flows"] == 4
    assert result["flows"] == flows


# ---------------------------------------------------------------------------
# session_interventions MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_session_interventions_empty_registry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from src.reader.novnc.flow_registry import novnc_flow_registry
    from tests.reader.novnc.test_flow_registry import FakeRedis

    monkeypatch.setattr(novnc_flow_registry, "_redis", FakeRedis())

    # when
    result = await session_interventions()

    # then
    assert result["active_flows"] == 0
    assert result["flows"] == []


@pytest.mark.asyncio
async def test_mcp_session_interventions_lists_flows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from src.reader.novnc.flow_registry import flow_key_for, novnc_flow_registry
    from tests.reader.novnc.test_flow_registry import FakeRedis

    fake = FakeRedis()
    monkeypatch.setattr(novnc_flow_registry, "_redis", fake)
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for("https://listed-site.com/1", "default"),
        url="https://listed-site.com/1",
        profile="default",
        intervention_type="captcha",
        resolve_vnc_url=AsyncMock(return_value="http://vnc/vnc.html"),
    )

    # when
    result = await session_interventions()

    # then
    assert result["active_flows"] == 1
    assert len(result["flows"]) == 1
    entry = result["flows"][0]
    assert entry["flow_id"] == flow.flow_id
    assert entry["window"]["slot"] == flow.window.slot
    assert entry["expires_in_seconds"] > 0
    assert "cookies" not in str(result)
    assert "storage_state" not in str(result)
    assert "content" not in str(entry)

    # cleanup
    await novnc_flow_registry.release(flow.flow_id)


# ---------------------------------------------------------------------------
# tool docstrings name vnc_url and status
# ---------------------------------------------------------------------------


def test_tool_docstrings_name_vnc_url_and_status() -> None:
    # given / when
    web_read_doc = web_read.__doc__ or ""
    establish_doc = session_establish.__doc__ or ""

    # then
    assert "vnc_url" in web_read_doc
    assert "status" in web_read_doc
    assert "slot" in web_read_doc
    assert "vnc_url" in establish_doc
    assert "status" in establish_doc
    assert "slot" in establish_doc


def test_session_establish_docstring_names_every_field_it_returns() -> None:
    # given / when
    establish_doc = session_establish.__doc__ or ""

    # then
    for field in ("flow_id", "joined", "window", "intervention_type", "novnc_busy"):
        assert field in establish_doc


# ---------------------------------------------------------------------------
# session_status MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_session_status_returns_info() -> None:
    # given
    info = SessionInfo(
        status="active", auth_ttl_remaining=3600.0, last_validated=1_000_000.0, profile="default"
    )

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "status", new=AsyncMock(return_value=info)),
    ):
        result = await session_status("http://example.com")

    # then
    assert result["url"] == "http://example.com"
    assert result["status"] == "active"
    assert result["auth_ttl_remaining_seconds"] == 3600.0


@pytest.mark.asyncio
async def test_mcp_session_status_unsafe_url_raises() -> None:
    # given
    bad_url = "http://10.0.0.1"

    # when
    with patch(
        "src.api.mcp.mcp_server.check_fetch_uri",
        side_effect=UnsafeUriError("URI resolves to a non-public address"),
    ):
        with pytest.raises(Exception, match=r"^unsafe_uri: ") as exc_info:
            await session_status(bad_url)

    # then
    assert str(exc_info.value).startswith("unsafe_uri: ")


# ---------------------------------------------------------------------------
# session_clear MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_session_clear_returns_cleared_status() -> None:
    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "clear", new=AsyncMock(return_value=True)),
        patch("src.api.mcp.mcp_server.web_reader.clear_cache_for_domain", return_value=1),
    ):
        result = await session_clear("http://example.com")

    # then
    assert result["status"] == "cleared"
    assert result["existed"] is True
    assert result["cleared_cache_entries"] == 1


@pytest.mark.asyncio
async def test_mcp_session_clear_is_idempotent_when_nothing_stored() -> None:
    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", return_value=True),
        patch.object(SessionManager, "clear", new=AsyncMock(return_value=False)),
        patch("src.api.mcp.mcp_server.web_reader.clear_cache_for_domain", return_value=0),
    ):
        result = await session_clear("http://never-stored.example.com")

    # then
    assert result["existed"] is False


@pytest.mark.asyncio
async def test_mcp_session_clear_unsafe_url_raises() -> None:
    # given
    bad_url = "http://10.0.0.1"

    # when
    with patch(
        "src.api.mcp.mcp_server.check_fetch_uri",
        side_effect=UnsafeUriError("URI resolves to a non-public address"),
    ):
        with pytest.raises(Exception, match=r"^unsafe_uri: ") as exc_info:
            await session_clear(bad_url)

    # then
    assert str(exc_info.value).startswith("unsafe_uri: ")


@pytest.mark.asyncio
async def test_mcp_web_search_unexpected_failure_maps_to_internal() -> None:
    # given
    failure = RuntimeError("upstream blew up")

    # when
    with patch(
        "src.api.mcp.mcp_server.search_client.search",
        new=AsyncMock(side_effect=failure),
    ):
        with pytest.raises(Exception, match=r"^internal: ") as exc_info:
            await web_search("query")

    # then
    assert str(exc_info.value).startswith("internal: ")


@pytest.mark.asyncio
async def test_mcp_web_read_unexpected_failure_maps_to_internal() -> None:
    # given
    failure = RuntimeError("reader blew up")

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", new_callable=AsyncMock),
        patch(
            "src.api.mcp.mcp_server.web_reader.read",
            new=AsyncMock(side_effect=failure),
        ),
    ):
        with pytest.raises(Exception, match=r"^internal: ") as exc_info:
            await web_read("http://mcp.com")

    # then
    assert str(exc_info.value).startswith("internal: ")


@pytest.mark.asyncio
async def test_mcp_session_establish_unexpected_failure_maps_to_internal() -> None:
    # given
    failure = RuntimeError("session blew up")

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", new_callable=AsyncMock),
        patch.object(SessionManager, "establish", new=AsyncMock(side_effect=failure)),
    ):
        with pytest.raises(Exception, match=r"^internal: ") as exc_info:
            await session_establish("http://example.com")

    # then
    assert str(exc_info.value).startswith("internal: ")


@pytest.mark.asyncio
async def test_mcp_session_status_unexpected_failure_maps_to_internal() -> None:
    # given
    failure = RuntimeError("status blew up")

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", new_callable=AsyncMock),
        patch.object(SessionManager, "status", new=AsyncMock(side_effect=failure)),
    ):
        with pytest.raises(Exception, match=r"^internal: ") as exc_info:
            await session_status("http://example.com")

    # then
    assert str(exc_info.value).startswith("internal: ")


@pytest.mark.asyncio
async def test_mcp_session_clear_unexpected_failure_maps_to_internal() -> None:
    # given
    failure = RuntimeError("clear blew up")

    # when
    with (
        patch("src.api.mcp.mcp_server.check_fetch_uri", new_callable=AsyncMock),
        patch.object(SessionManager, "clear", new=AsyncMock(side_effect=failure)),
    ):
        with pytest.raises(Exception, match=r"^internal: ") as exc_info:
            await session_clear("http://example.com")

    # then
    assert str(exc_info.value).startswith("internal: ")


# ---------------------------------------------------------------------------
# session_cancel_intervention MCP tool
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_session_cancel_intervention_closes_the_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from src.api.mcp.mcp_server import session_cancel_intervention
    from src.reader.novnc.flow_registry import flow_key_for, novnc_flow_registry
    from tests.reader.novnc.test_flow_registry import FakeRedis

    monkeypatch.setattr(novnc_flow_registry, "_redis", FakeRedis())
    flow = await novnc_flow_registry.reserve(
        key=flow_key_for("https://mcp-close.com/1", "default"),
        url="https://mcp-close.com/1",
        profile="default",
        intervention_type="login",
    )

    # when
    result = await session_cancel_intervention(flow.flow_id)

    # then
    assert result == {"status": "cancelled", "flow_id": flow.flow_id}
    assert novnc_flow_registry.local() == []
    last = await novnc_flow_registry.last_result(flow.key)
    assert last is not None
    assert last.outcome == "cancelled"


@pytest.mark.asyncio
async def test_mcp_session_cancel_intervention_of_an_unknown_flow_is_a_flow_not_found_tool_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # given
    from fastmcp.exceptions import ToolError

    from src.api.mcp.mcp_server import session_cancel_intervention
    from src.reader.novnc.flow_registry import novnc_flow_registry
    from tests.reader.novnc.test_flow_registry import FakeRedis

    monkeypatch.setattr(novnc_flow_registry, "_redis", FakeRedis())

    # when / then
    expected = r"^flow_not_found: No open intervention window has flow_id 0123456789ab\.$"
    with pytest.raises(ToolError, match=expected):
        await session_cancel_intervention("0123456789ab")
