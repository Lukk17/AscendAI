import logging

import httpx
from fastapi import Request, status
from fastapi.responses import JSONResponse

from src.api.exceptions import HumanInterventionRequiredException, NoVNCFlowBusyException
from src.config.blocklist_loader import BlocklistRefreshThrottledError, BlocklistValidationError
from src.observability.metrics import HUMAN_INTERVENTION_TOTAL, NOVNC_FLOW_BUSY_TOTAL

logger = logging.getLogger(__name__)


PROBLEM_JSON = "application/problem+json"
_PROBLEM_TYPE_BASE = "https://ascend.ai/errors"

# Suggested wait before a caller retries a busy NoVNC flow. Not the flow's own
# timeout (up to 10 minutes): a short, fixed poll interval so a rejected caller
# gets a fast, actionable answer instead of an opaque long wait.
_NOVNC_BUSY_RETRY_AFTER_SECONDS = 30


async def httpx_exception_handler(request: Request, exc: httpx.HTTPError) -> JSONResponse:
    """
    Global handler for HTTPX errors (external API failures).
    Returns 503 with an RFC 7807 problem document. The upstream exception
    detail is logged server-side, never echoed to the caller (the original
    `str(exc)` payload leaked upstream URLs and DNS / TLS error strings).
    """
    logger.error(f"External Service Error during {request.method} {request.url}: {exc}")

    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        media_type=PROBLEM_JSON,
        content={
            "type": f"{_PROBLEM_TYPE_BASE}/external-service-unavailable",
            "title": "External Service Unavailable",
            "status": status.HTTP_503_SERVICE_UNAVAILABLE,
            "detail": "An upstream dependency failed to respond.",
            "instance": str(request.url.path),
        },
    )


async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """
    Catch-all handler for unhandled exceptions.
    Returns 500 with an RFC 7807 problem document. The exception is logged
    with full traceback server-side; the response body never carries internal
    detail.
    """
    logger.exception(f"Unhandled Exception during {request.method} {request.url}: {exc}")

    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        media_type=PROBLEM_JSON,
        content={
            "type": f"{_PROBLEM_TYPE_BASE}/internal",
            "title": "Internal Server Error",
            "status": status.HTTP_500_INTERNAL_SERVER_ERROR,
            "instance": str(request.url.path),
        },
    )


async def human_intervention_exception_handler(
    request: Request, exc: HumanInterventionRequiredException
) -> JSONResponse:
    """
    Returns 428 Precondition Required when a manual Captcha or Login is triggered.
    """
    HUMAN_INTERVENTION_TOTAL.labels(intervention_type=exc.intervention_type).inc()
    logger.warning(
        f"428 Precondition Required triggered on {request.method} {request.url}: type={exc.intervention_type}"
    )

    # Intentionally NOT RFC 7807 here: the human-intervention response is an
    # established contract documented in ADR-003. The MCP tool docstring tells
    # agents to surface `vnc_url` and `intervention_type` by name; changing the
    # field shape would break every downstream agent.
    return JSONResponse(
        status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        content={
            "status": "human_intervention_required",
            "intervention_type": exc.intervention_type,
            "vnc_url": exc.vnc_url,
            "message": exc.message,
        },
    )


async def novnc_flow_busy_exception_handler(request: Request, exc: NoVNCFlowBusyException) -> JSONResponse:
    """
    Returns 409 Conflict when a NoVNC intervention is requested while another
    one already holds the single shared browser/display/CDP port.
    """
    NOVNC_FLOW_BUSY_TOTAL.inc()
    logger.info(
        f"409 Conflict on {request.method} {request.url}: NoVNC busy with "
        f"{exc.holder_url} (profile={exc.holder_profile})"
    )

    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        headers={"Retry-After": str(_NOVNC_BUSY_RETRY_AFTER_SECONDS)},
        content={
            "status": "novnc_busy",
            "message": exc.message,
            "holder_url": exc.holder_url,
            "holder_profile": exc.holder_profile,
        },
    )


async def blocklist_validation_error_handler(request: Request, exc: BlocklistValidationError) -> JSONResponse:
    """
    Returns 502 when a blocklist refresh downloaded content that parsed to zero
    usable rules. The previously loaded blocklist stays active; this only
    reports that the refresh itself did not take effect.
    """
    logger.error(f"Blocklist refresh validation failed during {request.method} {request.url}: {exc}")

    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        media_type=PROBLEM_JSON,
        content={
            "type": f"{_PROBLEM_TYPE_BASE}/blocklist-refresh-invalid",
            "title": "Blocklist Refresh Invalid",
            "status": status.HTTP_502_BAD_GATEWAY,
            "detail": str(exc),
            "instance": str(request.url.path),
        },
    )


async def blocklist_refresh_throttled_handler(
    request: Request, exc: BlocklistRefreshThrottledError
) -> JSONResponse:
    """
    Returns 429 when a blocklist refresh is requested again before the
    configured cooldown has elapsed since the last attempt.
    """
    retry_after = max(1, int(exc.retry_after_seconds) + 1)
    logger.info(f"Blocklist refresh throttled on {request.method} {request.url}: retry after {retry_after}s")

    return JSONResponse(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        media_type=PROBLEM_JSON,
        headers={"Retry-After": str(retry_after)},
        content={
            "type": f"{_PROBLEM_TYPE_BASE}/blocklist-refresh-throttled",
            "title": "Blocklist Refresh Throttled",
            "status": status.HTTP_429_TOO_MANY_REQUESTS,
            "detail": str(exc),
            "instance": str(request.url.path),
        },
    )
