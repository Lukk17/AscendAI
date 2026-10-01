from typing import Annotated

from fastapi import APIRouter, Form, Request, Response, UploadFile

from src.api.middleware.rate_limit import limiter
from src.config.config import DEFAULT_QUALITY, QualityMode, settings
from src.config.logging_config import get_logger
from src.model.ocr_models import JobListResponse, JobStatusResponse, JobSubmitResponse
from src.observability.metrics import OCR_REQUESTS_TOTAL, request_language_label
from src.service.job_service import job_service

logger = get_logger(__name__)

rest_router = APIRouter(prefix="/v1")

_SURFACE: str = "rest"


@rest_router.post("/ocr/jobs", status_code=202, summary="Submit a document to be read")
@limiter.limit(settings.RATE_LIMIT_OCR)
async def submit_job(
    request: Request,
    response: Response,
    file: UploadFile,
    lang: Annotated[str | None, Form()] = None,
    quality: Annotated[QualityMode, Form()] = DEFAULT_QUALITY,
    straighten: Annotated[bool, Form()] = False,
) -> JobSubmitResponse:
    _ = request
    language: str = lang or settings.DEFAULT_LANGUAGE
    OCR_REQUESTS_TOTAL.labels(surface=_SURFACE, language=request_language_label(language)).inc()

    file_bytes: bytes = await file.read()
    submitted = await job_service.submit(
        file_bytes, file.filename or "upload", language, quality, "rest", straighten=straighten
    )
    response.headers["Location"] = submitted.status_url

    return submitted


@rest_router.get("/ocr/jobs", summary="List the work that is queued or running")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
def list_jobs(request: Request) -> JobListResponse:
    _ = request

    return job_service.list_jobs()


@rest_router.get("/ocr/jobs/{job_id}", summary="Read the state of submitted work")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
def read_job(request: Request, job_id: str) -> JobStatusResponse:
    _ = request

    return job_service.status(job_id)


@rest_router.delete("/ocr/jobs/{job_id}", status_code=204, summary="Stop work, or forget a finished result")
@limiter.limit(settings.RATE_LIMIT_DEFAULT)
async def delete_job(request: Request, job_id: str) -> None:
    _ = request
    await job_service.delete(job_id)
