"""Redis key names of the crawl frontier (design D13).

Every key starts with ``crawl_`` and holds the tenant in the second place,
so ``crawl_*:{tenant}:*`` finds every Redis key of one tenant's crawl data.
The one exception is the shared pickup set ``crawl_runnable``, which holds
only ``{tenant}:{job_id}`` references. All builders live here so task 8.1
can check every written key against the D13 patterns in one place.
"""

RUNNABLE_KEY = "crawl_runnable"


def job_key(tenant_id: str, job_id: str) -> str:
    return f"crawl_job:{tenant_id}:{job_id}"


def job_key_pattern(tenant_id: str) -> str:
    return f"crawl_job:{tenant_id}:*"


def queue_key(tenant_id: str, job_id: str, domain: str) -> str:
    return f"crawl_queue:{tenant_id}:{job_id}:{domain}"


def seen_key(tenant_id: str, job_id: str) -> str:
    return f"crawl_seen:{tenant_id}:{job_id}"


def inflight_key(tenant_id: str, job_id: str, domain: str) -> str:
    return f"crawl_inflight:{tenant_id}:{job_id}:{domain}"


def claims_key(tenant_id: str, job_id: str) -> str:
    return f"crawl_claims:{tenant_id}:{job_id}"


def next_fetch_key(tenant_id: str, job_id: str, domain: str) -> str:
    return f"crawl_next_fetch:{tenant_id}:{job_id}:{domain}"


def pages_key(tenant_id: str, job_id: str) -> str:
    return f"crawl_pages:{tenant_id}:{job_id}"


def recrawl_key(tenant_id: str, scope: str) -> str:
    return f"crawl_recrawl:{tenant_id}:{scope}"


def runnable_member(tenant_id: str, job_id: str) -> str:
    return f"{tenant_id}:{job_id}"
