from typing import Any

import httpx
from ascend_python_common.errors import INTERNAL, VALIDATION, ErrorRegistry, ProblemCode
from ascend_python_common.uri_guard import UnsafeUriError

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.config.blocklist_loader import BlocklistRefreshThrottledError, BlocklistValidationError
from src.observability.metrics import HUMAN_INTERVENTION_TOTAL, NOVNC_FLOW_BUSY_TOTAL

EXTERNAL_SERVICE_UNAVAILABLE = ProblemCode("external_service_unavailable", 503)
BLOCKLIST_REFRESH_INVALID = ProblemCode("blocklist_refresh_invalid", 502)
BLOCKLIST_REFRESH_THROTTLED = ProblemCode("blocklist_refresh_throttled", 429)
HUMAN_INTERVENTION_REQUIRED = ProblemCode("human_intervention_required", 428)
NOVNC_BUSY = ProblemCode("novnc_busy", 409)
UNSAFE_URI = ProblemCode("unsafe_uri", 400)

# Suggested wait before a caller retries a busy NoVNC flow. Not the flow's own
# timeout (up to 10 minutes): a short, fixed poll interval so a rejected caller
# gets a fast, actionable answer instead of an opaque long wait.
_NOVNC_BUSY_RETRY_AFTER_SECONDS = 30


def _human_detail(exc: BaseException) -> str:
    assert isinstance(exc, HumanInterventionRequiredException)
    HUMAN_INTERVENTION_TOTAL.labels(intervention_type=exc.intervention_type).inc()
    return exc.message


def _human_extensions(exc: BaseException) -> dict[str, Any] | None:
    assert isinstance(exc, HumanInterventionRequiredException)
    return {"intervention_type": exc.intervention_type, "vnc_url": exc.vnc_url}


def _novnc_detail(exc: BaseException) -> str:
    assert isinstance(exc, NoVNCFlowBusyException)
    NOVNC_FLOW_BUSY_TOTAL.inc()
    return exc.message


def _novnc_extensions(exc: BaseException) -> dict[str, Any] | None:
    assert isinstance(exc, NoVNCFlowBusyException)
    return {"holder_url": exc.holder_url, "holder_profile": exc.holder_profile}


def _throttle_retry_after(exc: BaseException) -> dict[str, str] | None:
    assert isinstance(exc, BlocklistRefreshThrottledError)
    return {"Retry-After": str(max(1, int(exc.retry_after_seconds) + 1))}


def build_error_registry() -> ErrorRegistry:
    registry = ErrorRegistry(internal_code=INTERNAL)
    registry.register(UnsafeUriError, UNSAFE_URI, str)
    registry.register(ValueError, VALIDATION, str)
    registry.register(
        httpx.HTTPError,
        EXTERNAL_SERVICE_UNAVAILABLE,
        "An upstream dependency failed to respond.",
    )
    registry.register(BlocklistValidationError, BLOCKLIST_REFRESH_INVALID, str)
    registry.register(
        BlocklistRefreshThrottledError,
        BLOCKLIST_REFRESH_THROTTLED,
        str,
        headers=_throttle_retry_after,
    )
    registry.register(
        HumanInterventionRequiredException,
        HUMAN_INTERVENTION_REQUIRED,
        _human_detail,
        extensions=_human_extensions,
    )
    registry.register(
        NoVNCFlowBusyException,
        NOVNC_BUSY,
        _novnc_detail,
        headers={"Retry-After": str(_NOVNC_BUSY_RETRY_AFTER_SECONDS)},
        extensions=_novnc_extensions,
    )
    return registry


error_registry = build_error_registry()
