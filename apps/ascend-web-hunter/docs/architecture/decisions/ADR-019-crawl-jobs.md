# ADR-019: Polling crawl jobs over a shared Redis frontier

## Status

Accepted, 2026-10-20

## Context

The service reads one URL per request through its tier ladder, with the SSRF
guard re-validated on every redirect hop and connect-time address pinning
(ADR-012). Callers that need whole sites (documentation trees, product
catalogues) re-request page after page and follow links themselves, paying
one round trip per page and re-learning politeness per call. ascend-ocr
already ships a job API with polling and results in Floci. Several
ascend-web-hunter containers run at once, and each one must be able to work
any crawl: no part of a crawl may live only inside one process.

## Decision

### D1, polling job API, no webhook

`POST /api/v1/crawl/jobs` answers HTTP 202 with a `job_id`, state `waiting`
and a `poll_after_seconds` hint. `GET /api/v1/crawl/jobs/{job_id}` and
`GET /api/v1/crawl/jobs` read status and list, `DELETE` cancels. States are
`waiting`, `running`, `succeeded`, `failed` and `cancelled`. The MCP tools
`crawl_submit`, `crawl_job_status`, `crawl_list_jobs` and `crawl_cancel_job`
carry the same fields. A webhook was rejected for v1: it needs its own SSRF
guard on a caller-chosen address, signing and retries, and polling covers
every current caller.

### D2, Redis frontier with per-domain politeness

Each job owns a per-domain queue, a seen set of normalised URLs and a
per-domain in-flight counter in Redis. robots.txt is parsed with `protego`:
a disallowed path is not fetched, `Crawl-delay` is honoured above the
`CRAWL_DEFAULT_DELAY_SECONDS` floor, and sitemap URLs seed the frontier.
`respect_robots: false` is refused unless every seed domain is listed in
`CRAWL_ROBOTS_OPT_OUT_DOMAINS`. Politeness applies only inside crawl jobs;
single reads stay unthrottled.

### D3, several instances share one crawl through Lua scripts

Every shared-state change is one Redis Lua script: submission writes the job
record, the seed queues, the seen set and the `crawl_runnable` member
together; the claim script takes back expired claims, enforces the domain
cap, the crawl delay and the page budget for all instances together, then
pops one URL; the finish script removes the claim, appends the page line,
counts the page, queues only unseen links and moves the job to `succeeded`
when every queue and claim is empty. The first claim moves the job from
`waiting` to `running`. Cancel runs the cancel script on whichever instance
receives the call, so it reaches every instance through the shared record
with no messaging between instances. A claim whose lease
(`CRAWL_CLAIM_LEASE_SECONDS`, 120) passes is requeued by the next claim of
any instance; a URL that expires `CRAWL_CLAIM_MAX_EXPIRIES` times (2) counts
as failed. Each instance runs `CRAWL_WORKER_CONCURRENCY` (4) worker tasks.
robots.txt stays a per-instance memory cache, which is correct because every
instance reads the same file. The rejected alternative is one asyncio
crawler per job inside one process with the frontier in memory: it loses
several instances working on one crawl and a crawl surviving the instance
that started it.

### D4, results in Floci with incremental recrawl

One shared S3 client (`src/storage/object_store.py`) writes
`tenant/<tenantId>/<prefix><job_id>/pages.ndjson` and one file per page.
Per tenant and crawl scope, Redis keeps the content hash, `ETag`,
`Last-Modified` and page key of each URL. A recrawl sends conditional
requests; on a 304 or an equal hash the earlier page file is copied forward
with a server-side copy, so the bytes never pass the service and every job
keeps every reached page until it expires. Everything the crawl keeps
expires after `CRAWL_JOB_RETENTION_SECONDS` (604800); frontier keys are
deleted when the job ends and carry that expiry on every write.

### D5, honest scale

The ceiling is the hundreds-of-thousands-of-pages class per job across
several workers, not millions and not the whole web. The docs say so.

## Alternatives Considered

### Webhook delivery of finished jobs

- Pros: no polling traffic, faster caller reaction.
- Cons: the callback address needs its own SSRF guard, signing and
  retries, for callers polling already covers.
- Rejected: polling covers every current caller; revisit when one needs it.

### One in-process crawler per job

- Pros: no Lua scripts, plain Python data structures.
- Cons: a crawl dies with its instance, and two instances cannot share one
  crawl.
- Rejected: the owner keeps several instances sharing one crawl.

## Consequences

- Crawl throughput scales with worker tasks and instances, bounded by the
  per-domain cap and delay, which stay conservative by default.
- Operators tune behaviour through `CRAWL_*` settings only; no code
  constant carries an operational value.
- A blocked deployment address is the main operational risk; politeness is
  on by default and the per-domain cap is low.
