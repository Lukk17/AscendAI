import json
import re
import time
import uuid
from datetime import UTC, datetime

import redis.asyncio as redis
from ascend_python_common.uri_guard import FetchPolicy, check_fetch_uri

from src.config.config import settings
from src.crawl.frontier import Frontier
from src.crawl.keys import (
    RUNNABLE_KEY,
    claims_key,
    job_key,
    job_key_pattern,
    pages_key,
    runnable_member,
    seen_key,
)
from src.crawl.models import (
    DEFAULT_TENANT,
    TENANT_PATTERN,
    CrawlRequest,
    InvalidTenantError,
    JobCounts,
    JobRecord,
)
from src.crawl.robots import ensure_opt_out
from src.reader.cloudflare.cookie_manager import cookie_manager

TENANT_HEADER = "X-Ascend-Tenant"


def resolve_tenant(header_value: str | None) -> str:
    if header_value is None or header_value in ("", DEFAULT_TENANT):
        return DEFAULT_TENANT
    if re.fullmatch(TENANT_PATTERN, header_value) is None:
        raise InvalidTenantError(header_value)
    return header_value


class CrawlJobService:
    def __init__(self) -> None:
        self._client: redis.Redis | None = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._client

    @property
    def frontier(self) -> Frontier:
        return Frontier(self.client)

    def _fetch_policy(self) -> FetchPolicy:
        return FetchPolicy(
            allowed_hosts=tuple(settings.ALLOWED_PRIVATE_HOSTS),
            file_root=None,
            max_redirect_hops=settings.FETCH_MAX_REDIRECT_HOPS,
        )

    async def submit_job(self, tenant_id: str, request: CrawlRequest) -> JobRecord:
        for seed in request.seeds:
            await check_fetch_uri(str(seed), self._fetch_policy())
        seeds = [str(seed) for seed in request.seeds]
        ensure_opt_out(seeds, request.respect_robots)
        record = JobRecord(
            job_id=uuid.uuid4().hex,
            tenant_id=tenant_id,
            request=request,
            domains=sorted({cookie_manager.registrable_domain(seed) for seed in seeds}),
            pending=len(seeds),
            counts=JobCounts(
                queued=len(seeds),
                fetched=0,
                unchanged=0,
                failed=0,
                skipped_unsafe=0,
            ),
        )
        groups: dict[str, list[dict[str, object]]] = {}
        for seed_str in seeds:
            domain = cookie_manager.registrable_domain(seed_str)
            groups.setdefault(domain, []).append({"u": seed_str, "d": 0})
        groups_json = json.dumps(
            [{"domain": domain, "urls": urls} for domain, urls in sorted(groups.items())]
        )
        await self.frontier.submit(
            job_key=job_key(tenant_id, record.job_id),
            seen_key=seen_key(tenant_id, record.job_id),
            runnable_key=RUNNABLE_KEY,
            job_json=record.model_dump_json(),
            retention=settings.CRAWL_JOB_RETENTION_SECONDS,
            submitted_ms=int(time.time() * 1000),
            member=runnable_member(tenant_id, record.job_id),
            tenant_id=tenant_id,
            job_id=record.job_id,
            groups_json=groups_json,
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
        await self.frontier.cancel(
            job_key=job_key(tenant_id, job_id),
            seen_key=seen_key(tenant_id, job_id),
            claims_key=claims_key(tenant_id, job_id),
            pages_key=pages_key(tenant_id, job_id),
            runnable_key=RUNNABLE_KEY,
            updated_at=datetime.now(UTC).isoformat(),
            retention=settings.CRAWL_JOB_RETENTION_SECONDS,
            tenant_id=tenant_id,
            job_id=job_id,
            member=runnable_member(tenant_id, job_id),
        )
        updated = await self.get_job(tenant_id, job_id)
        return updated if updated is not None else record


job_service = CrawlJobService()
