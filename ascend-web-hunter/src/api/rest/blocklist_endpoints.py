from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status

from src.config.blocklist_loader import BlocklistState, blocklist_loader
from src.validator.url_validator import url_validator

blocklist_router = APIRouter(prefix="/api/v1/blocklist", tags=["blocklist"])


def _state_dict(state: BlocklistState) -> dict[str, Any]:
    age_seconds = (datetime.now(UTC) - state.loaded_at).total_seconds()

    return {
        "rule_count": state.rule_count,
        "loaded_at": state.loaded_at.isoformat(),
        "age_seconds": age_seconds,
    }


@blocklist_router.get("/status")
async def blocklist_status() -> dict[str, Any]:
    """
    Report the currently active blocklist without changing anything: how many
    rules are loaded and how long ago they were loaded or last refreshed.
    """
    state = blocklist_loader.state
    if state is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Blocklist not loaded")

    return _state_dict(state)


@blocklist_router.post("/refresh")
async def refresh_blocklist() -> dict[str, Any]:
    """
    Download the blocklist from BLOCKLIST_URL, validate it, and atomically
    replace both the on-disk file and the rules every request is checked
    against. A download or validation failure leaves the previously loaded
    blocklist serving requests unchanged.

    Not exposed on the MCP surface: refreshing the blocklist is a deliberate
    operator action, not something a calling agent should trigger.
    """
    rules, new_state = await blocklist_loader.refresh()
    url_validator.rules = rules

    return {"status": "refreshed", **_state_dict(new_state)}
