from fastapi import APIRouter, Header

from src.config.config import settings
from src.crawl.job_service import TENANT_HEADER, job_service, resolve_tenant
from src.crawl.models import (
    CrawlJobList,
    CrawlJobView,
    CrawlRequest,
    CrawlSubmission,
    JobNotFoundError,
)

crawl_router = APIRouter(prefix="/api/v1/crawl", tags=["crawl"])


@crawl_router.post("/jobs", status_code=202, response_model=CrawlSubmission)
async def submit_crawl_job(
    request: CrawlRequest,
    x_ascend_tenant: str | None = Header(default=None, alias=TENANT_HEADER),
) -> CrawlSubmission:
    tenant_id = resolve_tenant(x_ascend_tenant)
    record = await job_service.submit_job(tenant_id, request)
    return CrawlSubmission(
        job_id=record.job_id,
        state=record.state,
        poll_after_seconds=settings.CRAWL_POLL_AFTER_SECONDS,
    )


@crawl_router.get("/jobs/{job_id}", response_model=CrawlJobView)
async def crawl_job_status(
    job_id: str,
    x_ascend_tenant: str | None = Header(default=None, alias=TENANT_HEADER),
) -> CrawlJobView:
    tenant_id = resolve_tenant(x_ascend_tenant)
    record = await job_service.get_job(tenant_id, job_id)
    if record is None:
        raise JobNotFoundError(job_id)
    return CrawlJobView.from_record(record)


@crawl_router.get("/jobs", response_model=CrawlJobList)
async def crawl_list_jobs(
    x_ascend_tenant: str | None = Header(default=None, alias=TENANT_HEADER),
) -> CrawlJobList:
    tenant_id = resolve_tenant(x_ascend_tenant)
    records = await job_service.list_jobs(tenant_id)
    return CrawlJobList(jobs=[CrawlJobView.from_record(record) for record in records])


@crawl_router.delete("/jobs/{job_id}", response_model=CrawlJobView)
async def crawl_cancel_job(
    job_id: str,
    x_ascend_tenant: str | None = Header(default=None, alias=TENANT_HEADER),
) -> CrawlJobView:
    tenant_id = resolve_tenant(x_ascend_tenant)
    record = await job_service.cancel_job(tenant_id, job_id)
    if record is None:
        raise JobNotFoundError(job_id)
    return CrawlJobView.from_record(record)
