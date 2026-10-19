from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True, scope="session")
def _no_camelcase_compat() -> Iterator[None]:
    import fastmcp.settings

    previous = fastmcp.settings.mcp_camelcase_compat
    fastmcp.settings.mcp_camelcase_compat = False
    try:
        yield
    finally:
        fastmcp.settings.mcp_camelcase_compat = previous
