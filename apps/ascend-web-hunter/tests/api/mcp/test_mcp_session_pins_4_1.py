"""Pin today's MCP behaviour for ascend-web-hunter (task 4.1).

This suite mocks the top-level `fastmcp` module in `tests/conftest.py`, so the
in-memory `fastmcp.Client` and the raw `/mcp` session used by the memory and
audio-scribe pin tests cannot run here. The pins below call the same tool
functions the MCP server registers and assert the same contract: the six tool
names with no explicit rename, every input schema, and the content of each
tool result, including the `human_intervention_required`, `novnc_busy` and
`session_expired` result objects of `web_read`.
"""

import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import src.api.mcp.mcp_server as mcp_module
from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.api.mcp.mcp_server import (
    session_clear,
    session_establish,
    session_interventions,
    session_status,
    web_read,
    web_search,
)
from src.config.config import settings
from src.reader.novnc.flow_registry import novnc_flow_registry
from src.session.session_manager import SessionInfo, session_manager

EXPECTED_TOOL_NAMES = {
    "web_search",
    "web_read",
    "session_establish",
    "session_interventions",
    "session_status",
    "session_clear",
}


def test_tool_functions_keep_their_mcp_names() -> None:
    tools = {
        "web_search": web_search,
        "web_read": web_read,
        "session_establish": session_establish,
        "session_interventions": session_interventions,
        "session_status": session_status,
        "session_clear": session_clear,
    }

    assert set(tools) == EXPECTED_TOOL_NAMES
    assert {tool.__name__ for tool in tools.values()} == EXPECTED_TOOL_NAMES


def test_tool_registration_uses_no_explicit_name() -> None:
    calls: Any = getattr(mcp_module.mcp.tool, "call_args_list", [])

    assert len(calls) == len(EXPECTED_TOOL_NAMES)
    assert all(call.kwargs.get("name") is None for call in calls)


def _required_and_optional(tool: Any) -> tuple[set[str], set[str]]:
    parameters = inspect.signature(tool).parameters
    required = {
        name for name, parameter in parameters.items() if parameter.default is inspect.Parameter.empty
    }
    return required, set(parameters) - required


def test_tool_input_schemas_pin_required_fields() -> None:
    assert _required_and_optional(web_search) == ({"query"}, {"limit"})
    assert _required_and_optional(web_read) == (
        {"url"},
        {"include_links", "link_filter", "heavy_mode", "profile", "output_format", "tier"},
    )
    assert _required_and_optional(session_establish) == ({"url"}, {"profile"})
    assert _required_and_optional(session_interventions) == (set(), set())
    assert _required_and_optional(session_status) == ({"url"}, {"profile"})
    assert _required_and_optional(session_clear) == ({"url"}, {"profile"})


async def test_call_web_search_pins_today_body() -> None:
    mock_results = [{"title": "MCP", "url": "http://mcp.com"}]
    with patch.object(mcp_module.search_client, "search", new=AsyncMock(return_value=mock_results)):
        result = await web_search("query", 5)

    assert result == mock_results


async def test_call_web_read_pins_today_body() -> None:
    mock_content = {"content": "MCP Content", "status": "success", "mode": "1-beautifulsoup"}
    with (
        patch.object(mcp_module, "check_fetch_uri", new=AsyncMock(return_value=True)),
        patch.object(mcp_module.web_reader, "read", new=AsyncMock(return_value=mock_content)),
    ):
        result = await web_read("http://mcp.com")

    assert result == mock_content


async def test_call_web_read_pins_human_intervention_required_object() -> None:
    with (
        patch.object(mcp_module, "check_fetch_uri", new=AsyncMock(return_value=True)),
        patch.object(
            mcp_module.web_reader,
            "read",
            new=AsyncMock(
                side_effect=HumanInterventionRequiredException(
                    vnc_url="http://vnc:7900", intervention_type="captcha"
                )
            ),
        ),
    ):
        result = await web_read("http://example.com")

    assert result == {
        "status": "human_intervention_required",
        "intervention_type": "captcha",
        "vnc_url": "http://vnc:7900",
        "flow_id": None,
        "joined": False,
        "window": None,
        "message": "Manual Captcha resolution required. Please visit: http://vnc:7900",
    }


async def test_call_web_read_pins_novnc_busy_object() -> None:
    with (
        patch.object(mcp_module, "check_fetch_uri", new=AsyncMock(return_value=True)),
        patch.object(
            mcp_module.web_reader,
            "read",
            new=AsyncMock(side_effect=NoVNCFlowBusyException("http://in-flight.example", "default")),
        ),
    ):
        result = await web_read("http://example.com")

    assert result["status"] == "novnc_busy"
    assert result["holder_url"] == "http://in-flight.example"
    assert result["holder_profile"] == "default"
    assert "message" in result


async def test_call_web_read_pins_session_expired_object() -> None:
    expected = {
        "content": "",
        "status": "session_expired",
        "profile": "work",
        "message": "Stored session lapsed.",
    }
    with (
        patch.object(mcp_module, "check_fetch_uri", new=AsyncMock(return_value=True)),
        patch.object(mcp_module.web_reader, "read", new=AsyncMock(return_value=expected)),
    ):
        result = await web_read("http://example.com/feed")

    assert result == expected


async def test_call_session_establish_pins_today_status_object() -> None:
    with (
        patch.object(mcp_module, "check_fetch_uri", new=AsyncMock(return_value=True)),
        patch.object(
            session_manager,
            "establish",
            new=AsyncMock(return_value="http://vnc:7900"),
        ),
    ):
        result = await session_establish("http://example.com/")

    assert result == {
        "status": "human_intervention_required",
        "intervention_type": "login",
        "vnc_url": "http://vnc:7900",
        "message": "Login required. Please visit: http://vnc:7900",
    }


async def test_call_session_interventions_pins_today_body() -> None:
    with patch.object(novnc_flow_registry, "active", new=AsyncMock(return_value=[])):
        result = await session_interventions()

    assert result == {
        "active_flows": 0,
        "max_concurrent_flows": settings.NOVNC_MAX_CONCURRENT_FLOWS,
        "flows": [],
    }


async def test_call_session_status_pins_today_body() -> None:
    info = SessionInfo(status="active", auth_ttl_remaining=60.0, last_validated=None, profile="default")
    with (
        patch.object(mcp_module, "check_fetch_uri", new=AsyncMock(return_value=True)),
        patch.object(session_manager, "status", new=AsyncMock(return_value=info)),
    ):
        result = await session_status("http://example.com/")

    assert result == {
        "url": "http://example.com/",
        "status": "active",
        "auth_ttl_remaining_seconds": 60.0,
        "last_validated": None,
        "profile": "default",
    }


async def test_call_session_clear_pins_today_body() -> None:
    with (
        patch.object(mcp_module, "check_fetch_uri", new=AsyncMock(return_value=True)),
        patch.object(session_manager, "clear", new=AsyncMock(return_value=True)),
        patch.object(mcp_module.web_reader, "clear_cache_for_domain", new=MagicMock(return_value=2)),
    ):
        result = await session_clear("http://example.com/")

    assert result["status"] == "cleared"
    assert result["url"] == "http://example.com/"
    assert result["existed"] is True
    assert result["cleared_cache_entries"] == 2
