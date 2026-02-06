import sys
from unittest.mock import MagicMock, AsyncMock

# Mock mem0ai dependencies
mock_mem0 = MagicMock()
mock_memory_instance = MagicMock()
mock_mem0.Memory.from_config.return_value = mock_memory_instance
sys.modules["mem0"] = mock_mem0
sys.modules["mem0.llms.openai"] = MagicMock()

# Mock Qdrant Client (used in config/memory client)
sys.modules["qdrant_client"] = MagicMock()

# Mock FastMCP (prevents runtime session errors)
mock_fastmcp_module = MagicMock()
mock_mcp_instance = MagicMock()
# Mock tool decorator to be a pass-through
mock_mcp_instance.tool.return_value = lambda f: f


# Mock http_app to return a dummy ASGI app
async def mock_asgi_app(scope, receive, send):
    pass


mock_mcp_instance.http_app.return_value = mock_asgi_app

mock_fastmcp_module.FastMCP.return_value = mock_mcp_instance
sys.modules["fastmcp"] = mock_fastmcp_module

import pytest
import pytest_asyncio
from typing import AsyncGenerator
from httpx import AsyncClient, ASGITransport

from src.main import app
from src.service.memory_client import AscendMemoryClient, get_memory_client


@pytest.fixture
def mock_memory_service():
    """
    Returns the internal mocked Memory instance.
    This allows checking if .add(), .search(), etc. were called on the underlying library.
    """
    return mock_memory_instance


@pytest.fixture
def override_dependencies(mock_memory_service):
    """
    Overrides the get_memory_client dependency in FastAPI.
    Returns a mock AscendMemoryClient that wraps the global mock_memory_instance.
    """
    mock_client = MagicMock(spec=AscendMemoryClient)
    # Link the mock client's internal memory to our global mock
    mock_client.memory = mock_memory_service

    app.dependency_overrides[get_memory_client] = lambda: mock_client
    yield mock_client
    app.dependency_overrides = {}


@pytest_asyncio.fixture(scope="function")
async def client(override_dependencies) -> AsyncGenerator[AsyncClient, None]:
    """
    Creates an async test client for the FastAPI app.
    Uses the override_dependencies fixture to ensure no real DB calls happen.
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.fixture(autouse=True)
def reset_global_mocks():
    """Reset global mocks before each test to avoid state pollution."""
    mock_memory_instance.reset_mock()
    mock_memory_instance.side_effect = None
    mock_memory_instance.return_value = MagicMock()
    # Also reset specific methods that might have side effects set
    mock_memory_instance.add.side_effect = None
    mock_memory_instance.search.side_effect = None
    mock_memory_instance.delete.side_effect = None
    mock_memory_instance.get_all.side_effect = None
    mock_memory_instance.get_all.return_value = MagicMock()

    mock_mcp_instance.reset_mock()
    yield
