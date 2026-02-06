import pytest
from contextlib import asynccontextmanager
import anyio

@pytest.fixture(scope="session", autouse=True)
def mock_mcp_lifespan_global():
    """
    Global session-scoped patch for MCP session manager.
    Prevents ALL tests from launching the persistent background loop.
    Stable configuration: Patch applied once per session.
    """
    # Lazy import to avoid collection-time side effects (CPU dispatcher errors)
    import src.api.mcp.mcp_server as mcp_server_module

    original_run = mcp_server_module.mcp.session_manager.run

    @asynccontextmanager
    async def _mock_run():
        # FastMCP requires an active TaskGroup for tool execution
        async with anyio.create_task_group() as tg:
            # Manually inject the task group into the session manager so it can spawn tasks
            setattr(mcp_server_module.mcp.session_manager, "_task_group", tg)
            try:
                yield tg
            finally:
                # Force cancel all tasks to ensure instant teardown and prevent Timeouts
                tg.cancel_scope.cancel()
                
                # Cleanup task group immediately after context exits to allow re-entry
                if hasattr(mcp_server_module.mcp.session_manager, "_task_group"):
                    delattr(mcp_server_module.mcp.session_manager, "_task_group")

    # Apply patch
    mcp_server_module.mcp.session_manager.run = _mock_run
    
    yield
    
    # Restore patch
    mcp_server_module.mcp.session_manager.run = original_run
