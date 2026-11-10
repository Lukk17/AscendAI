# ADR-019: Polling crawl jobs over a shared Redis frontier

## Status

Accepted, 2026-10-20

## Amendment, 2026-11-08 (owner decision): crawl jobs ignore the rules of robots.txt by default

Crawl jobs ignore the rules of robots.txt unless the caller sends
`respect_robots` true, by owner decision. `respect_robots` defaults to false
on `CrawlRequest` and on the `crawl_submit` tool, and false is accepted for every site: the refusal in
D2 and the setting `CRAWL_ROBOTS_OPT_OUT_DOMAINS` are removed. A caller who
sends true gets the rest of D2 as written: the RFC 9309 reading of the answer,
a disallowed page skipped with `reason` `robots_disallowed` and `Crawl-delay`
above the `CRAWL_DEFAULT_DELAY_SECONDS` floor. Sitemap URLs seed the frontier
of every job: a job that ignores the rules still fetches robots.txt once per
origin and uses it for its sitemap addresses only, so no page is skipped and
no `Crawl-delay` applies. A robots.txt that cannot be loaded disallows nothing
for such a job, it only leaves the job without sitemap addresses, and any
failure while seeding from sitemaps is logged and ends the seeding. The
per-domain delay `CRAWL_DEFAULT_DELAY_SECONDS` (1 second by default) and the per-domain cap
stay in force for every job.

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
The final answer to the robots.txt fetch is read as RFC 9309 says: a 4xx
answer other than 429 allows every page of the origin, and a 5xx answer, a
429 (read as a server error, as Google reads it) or a connection error
disallows every page of the origin for the job. A disallowed page counts as
`failed` and its line in `pages.ndjson` reads `status` `skipped` with
`reason` `robots_disallowed`.
`respect_robots: false` is refused unless every seed domain is listed in
`CRAWL_ROBOTS_OPT_OUT_DOMAINS`. Politeness applies only inside crawl jobs;
single reads stay unthrottled.

### D3, several instances share one crawl through Lua scripts

Every shared-state change is one Redis Lua script: submission writes the job
record, the seed queues, the seen set and the `crawl_runnable` member
together; the claim script takes back expired claims, enforces the domain
cap, the crawl delay and the page budget for all instances together, with
the pages claimed and still being read counted against the budget beside
the finished ones, then pops one URL; the finish script removes the claim,
appends the page line, counts the page, queues only unseen links and ends
the job when every queue and claim is empty: `succeeded` when at least one
page was fetched or unchanged, `failed` when none was. The first claim moves the job from
`waiting` to `running`. Cancel runs the cancel script on whichever instance
receives the call, so it reaches every instance through the shared record
with no messaging between instances. A claim whose lease
(`CRAWL_CLAIM_LEASE_SECONDS`, 120) passes is requeued by the next claim of
any instance; a URL that expires `CRAWL_CLAIM_MAX_EXPIRIES` times (2) counts
as failed. Each instance runs `CRAWL_WORKER_CONCURRENCY` (4) worker tasks.
robots.txt stays a per-instance memory cache, which is correct because every
instance reads the same file. It keeps one verdict per job, profile and
origin, the disallow-all of an unreachable file included, and never one from
a fetch that raised or was cancelled. Every instance drops that memory once
it sees the job ended or gone, and a fetch still running at that moment keeps
nothing. robots.txt and sitemap fetches carry the job's profile and go through
the crawl proxy like every other crawl fetch. Crawl page reads neither read from nor write
to the in-process read cache of single reads, so a page a job reports as
`fetched` was fetched by that job. The rejected alternative is one asyncio
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
keeps every reached page until it expires. The job record and the recrawl
state expire in Redis at `CRAWL_JOB_RETENTION_SECONDS` (604800). Frontier
keys are deleted when the job ends and carry that expiry on every write.
The result objects in the bucket (`pages.ndjson` and every page file)
expire through one bucket lifecycle rule on `tenant/`. A lifecycle rule
counts whole days, so it carries the retention rounded up to whole days,
counted from when each object was written: a result object expires within
one day after the retention time, and the store deletes it asynchronously.
Each instance sets the rule once at crawl worker startup, merged by its rule
ID into the bucket's other lifecycle rules, which needs the
`s3:GetLifecycleConfiguration` and `s3:PutLifecycleConfiguration`
permissions. A store that refuses the rule or does not support it leaves
the results without expiry, and the service reports that with a WARNING, a
startup banner line and the `crawl_result_expiry_rule_applied` gauge rather
than failing page writes.

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
