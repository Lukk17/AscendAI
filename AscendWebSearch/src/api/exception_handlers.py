import logging

import httpx
from fastapi import Request, status
from fastapi.responses import JSONResponse

from src.api.exceptions import HumanInterventionRequiredException

logger = logging.getLogger(__name__)


async def httpx_exception_handler(request: Request, exc: httpx.HTTPError):
    """
    Global handler for HTTPX errors (external API failures).
    Returns 503 Service Unavailable instead of crashing.
    """
    logger.error(f"External Service Error during {request.method} {request.url}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": "External search service unavailable", "error": str(exc)},
    )


async def global_exception_handler(request: Request, exc: Exception):
    """
    Catch-all handler for unhandled exceptions.
    """
    logger.error(f"Unhandled Exception during {request.method} {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={"detail": "Internal Server Error"},
    )


async def human_intervention_exception_handler(request: Request, exc: HumanInterventionRequiredException):
    """
    Returns 428 Precondition Required when a manual Captcha or Login is triggered.
    """
    logger.warning(f"428 Precondition Required triggered on {request.method} {request.url}: type={exc.intervention_type}")
    return JSONResponse(
        status_code=status.HTTP_428_PRECONDITION_REQUIRED,
        content={
            "status": "human_intervention_required",
            "intervention_type": exc.intervention_type,
            "vnc_url": exc.vnc_url,
            "message": exc.message
        }
    )
