import re
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis
from ascend_python_common.uri_guard import FetchPolicy, check_fetch_uri

from src.config.config import settings
from src.crawl.models import (
    DEFAULT_TENANT,
    TENANT_PATTERN,
    CrawlRequest,
    InvalidTenantError,
    JobRecord,
)

TENANT_HEADER = "X-Ascend-Tenant"


def resolve_tenant(header_value: str | None) -> str:
    if header_value is None or header_value in ("", DEFAULT_TENANT):
        return DEFAULT_TENANT
    if re.fullmatch(TENANT_PATTERN, header_value) is None:
        raise InvalidTenantError(header_value)
    return header_value


def job_key(tenant_id: str, job_id: str) -> str:
    return f"crawl_job:{tenant_id}:{job_id}"


def job_key_pattern(tenant_id: str) -> str:
    return f"crawl_job:{tenant_id}:*"


class CrawlJobService:
    def __init__(self) -> None:
        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._client

    def _fetch_policy(self) -> FetchPolicy:
        return FetchPolicy(
            allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
            file_root=None,
            max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
        )

    async def submit_job(self, tenant_id: str, request: CrawlRequest) -> JobRecord:
        for seed in request.seeds:
            await check_fetch_uri(str(seed), self._fetch_policy())
        record = JobRecord(job_id=uuid.uuid4().hex, tenant_id=tenant_id, request=request)
        await self.client.setex(
            job_key(tenant_id, record.job_id),
            settings.CRAWL_JOB_RETENTION_SECONDS,
            record.model_dump_json(),
        )
        return record

    async def get_job(self, tenant_id: str, job_id: str) -> JobRecord | None:
        raw = await self.client.get(job_key(tenant_id, job_id))
        if raw is None:
            return None
        try:
            return JobRecord.model_validate_json(raw)
        except ValueError:
            return None

    async def list_jobs(self, tenant_id: str) -> list[JobRecord]:
        records: list[JobRecord] = []
        async for key in self.client.scan_iter(match=job_key_pattern(tenant_id)):
            raw = await self.client.get(key)
            if raw is None:
                continue
            try:
                records.append(JobRecord.model_validate_json(raw))
            except ValueError:
                continue
        return records

    async def cancel_job(self, tenant_id: str, job_id: str) -> JobRecord | None:
        record = await self.get_job(tenant_id, job_id)
        if record is None:
            return None
        if record.state in ("waiting", "running"):
            record.state = "cancelled"
            record.updated_at = datetime.now(UTC)
            await self.client.setex(
                job_key(tenant_id, record.job_id),
                settings.CRAWL_JOB_RETENTION_SECONDS,
                record.model_dump_json(),
            )
        return record


job_service = CrawlJobService()
