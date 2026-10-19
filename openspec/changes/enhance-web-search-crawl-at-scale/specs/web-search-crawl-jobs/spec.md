## ADDED Requirements

### Requirement: Polling crawl job API

ascend-web-hunter SHALL expose `POST /api/v1/crawl/jobs`, `GET /api/v1/crawl/jobs/{job_id}`, `GET /api/v1/crawl/jobs` and `DELETE /api/v1/crawl/jobs/{job_id}`, and the MCP tools `crawl_submit`, `crawl_job_status`, `crawl_list_jobs` and `crawl_cancel_job`. A submission SHALL answer HTTP 202 with a `job_id` without waiting for the crawl. Status SHALL be read by polling. No webhook SHALL be called.

#### Scenario: Submission returns a job id

- **WHEN** a valid crawl request is submitted
- **THEN** the answer is HTTP 202 with a `job_id` and state `waiting`

#### Scenario: Unknown job

- **WHEN** a caller reads a `job_id` that does not exist
- **THEN** the answer is HTTP 404 with `Content-Type: application/problem+json`, `code` `job_not_found` and `type` `https://ascend.ai/errors/job-not-found`

### Requirement: Crawl errors are problem bodies

Crawl REST errors SHALL be RFC 7807 problem bodies with `application/problem+json`, `type` `https://ascend.ai/errors/` plus code with `-` for `_`, `title`, `status`, `detail`, `instance`, `code`, `traceId`, built by the shared `ascend-python-common` builder. `traceId` SHALL be the 32 lower hex trace id when valid, else omitted, never empty or invented. A 5xx `detail` SHALL NOT name internal hosts, paths, or exception text.

#### Scenario: Error body carries the trace id

- **WHEN** tracing is on and a caller reads an unknown `job_id`
- **THEN** the problem body carries `code` `job_not_found` and a `traceId` equal to the trace id of that request

#### Scenario: Tracing off still names the trace

- **WHEN** no trace export is configured (`OTEL_EXPORTER_OTLP_ENDPOINT` unset) and a caller reads an unknown `job_id`
- **THEN** the problem body carries `code` `job_not_found` and a `traceId` of 32 lower case hex characters, the id of the unsampled span the library starts for every request

### Requirement: Crawl jobs are tenant scoped

Every crawl job SHALL belong to one tenant from MCP `ascend.ai/tenant_id` or REST `X-Ascend-Tenant`, defaulting to `default` with no setting changing it. No tool argument SHALL name a tenant. Outside `[a-z0-9-]{1,64}` SHALL be refused 400 `invalid_tenant`. Records, frontier keys, recrawl state and results SHALL carry the tenant, and status, list and cancel SHALL see only the caller tenant.

#### Scenario: A job of another tenant is not found

- **WHEN** a job submitted for tenant `acme` is read by a caller of tenant `globex`
- **THEN** the answer is HTTP 404 with `code` `job_not_found`
- **AND** the job is absent from the list of tenant `globex`

#### Scenario: A malformed tenant is refused

- **WHEN** a REST call sends `X-Ascend-Tenant: ../acme`
- **THEN** the answer is HTTP 400 with `code` `invalid_tenant` and no job is created

### Requirement: Crawl request bounds

Crawl requests SHALL carry 1 to CRAWL_MAX_SEEDS seeds, patterns at most CRAWL_MAX_PATTERNS each, max_depth to CRAWL_MAX_DEPTH, page_budget to CRAWL_MAX_PAGES, plus same_domain_only, respect_robots, output_format, extraction_schema, profile. Missing max_depth SHALL use CRAWL_DEFAULT_DEPTH (2), missing page_budget CRAWL_DEFAULT_PAGE_BUDGET (100). Bounds and defaults SHALL be env settings defaulting 20, 50, 5, 10000. Only inside-bound URLs SHALL be visited.

#### Scenario: Crawl respects scope

- **WHEN** a crawl runs with an include pattern, `max_depth` 2 and `page_budget` 50
- **THEN** it visits only matching URLs, no deeper than depth 2, and no more than 50 pages

#### Scenario: Request defaults come from the settings

- **WHEN** a crawl request names no `max_depth` and no `page_budget` and the settings keep their defaults
- **THEN** the job runs with `max_depth` 2 and `page_budget` 100

### Requirement: Crawl URLs pass the SSRF guard

Every seed SHALL be checked at submission, and a seed that is not `http` or `https`, carries userinfo, or resolves to a private, loopback, link-local or reserved address SHALL be refused with HTTP 400 and `code` `unsafe_uri` and no job created. Every discovered link, redirect hop, robots.txt fetch and sitemap fetch SHALL pass the same guard with connect-time pinning, and a link that fails SHALL be dropped and counted.

#### Scenario: Private seed refused

- **WHEN** a crawl is submitted with the seed `http://10.0.0.1/`
- **THEN** the answer is HTTP 400 with `code` `unsafe_uri` and no job exists

#### Scenario: Every unsafe seed form is refused as a problem body

- **WHEN** a crawl is submitted with a seed whose host resolves to a private address, a `file://` seed or a seed with userinfo
- **THEN** each answer is HTTP 400 with `Content-Type: application/problem+json`, `code` `unsafe_uri` and a `traceId` of 32 lower case hex characters
- **AND** no job exists and no request reaches the private address

#### Scenario: Discovered private link dropped

- **WHEN** a crawled page links to `http://127.0.0.1/admin`
- **THEN** that link is not fetched and the job counts it as `skipped_unsafe`

### Requirement: Results stored in Floci under a configured prefix

Crawl results SHALL be written through the one S3 client in `src/storage/object_store.py` to `OBJECT_STORE_S3_ENDPOINT` (Floci locally, host port 9070) in `CRAWL_RESULT_S3_BUCKET` under `tenant/<tenantId>/` plus `CRAWL_RESULT_S3_PREFIX`, as one `pages.ndjson` index and one file per page under the job prefix. The connection SHALL use only `OBJECT_STORE_S3_ENDPOINT`, `OBJECT_STORE_S3_ACCESS_KEY`, `OBJECT_STORE_S3_SECRET_KEY`.

#### Scenario: Results land under the tenant and the prefix

- **WHEN** a crawl job of tenant `acme` succeeds
- **THEN** `tenant/acme/<prefix><job_id>/pages.ndjson` exists and lists every fetched page

### Requirement: Redis frontier with per-domain politeness

Frontier SHALL be Redis, per-domain delay and cap, sitemaps, robots.txt. respect_robots=false SHALL need CRAWL_ROBOTS_OPT_OUT_DOMAINS. Workers SHALL share one frontier, no double fetch. Any instance SHALL work any jobs. Caps,delay,budget SHALL hold together. Any cancel SHALL stop all. Dead claims SHALL return after CRAWL_CLAIM_LEASE_SECONDS (120), fail after CRAWL_CLAIM_MAX_EXPIRIES (2). Each SHALL read at most CRAWL_WORKER_CONCURRENCY (4) at once. All shared changes SHALL be atomic.

#### Scenario: The domain cap holds across instances

- **WHEN** two instances work on one job whose seeds are all on one domain and `CRAWL_DOMAIN_CONCURRENCY` is 2
- **THEN** at no moment are more than 2 pages of that domain being read by both instances together

#### Scenario: A cancel on one instance stops the other

- **WHEN** a running job is cancelled through one instance while a worker of a second instance reads one of its pages
- **THEN** the job reads `cancelled`, the second instance claims no further page of it, and the page it was reading is not added to the results

#### Scenario: One instance reads at most its worker count of pages at once

- **WHEN** one instance works on jobs with more than 4 URLs ready to claim on different domains and `CRAWL_WORKER_CONCURRENCY` is 4
- **THEN** at no moment does that instance read more than 4 pages at once

#### Scenario: The claim of a stopped instance is taken back

- **WHEN** an instance stops while it holds a claim on a URL of a running job
- **THEN** after the claim lease ends another instance claims that URL and the job still reaches `succeeded`

#### Scenario: robots.txt disallow respected

- **WHEN** a crawl meets a path its robots.txt disallows
- **THEN** that path is not fetched

#### Scenario: A crawl result honours every bound

- **WHEN** a crawl with an include pattern, `max_depth` 2 and `page_budget` 5 reaches `succeeded` on a site whose robots.txt disallows one path
- **THEN** its `pages.ndjson` lists at most 5 pages, none deeper than depth 2, none outside the include pattern and not the disallowed path

#### Scenario: Two workers share the frontier

- **WHEN** two workers consume the same frontier
- **THEN** each queued URL is fetched by exactly one worker

### Requirement: Incremental recrawl

Each crawled URL SHALL store content hash, `ETag`, `Last-Modified` and page file key, and recrawls SHALL send conditional requests. On 304 or unchanged hash the earlier file SHALL be copied forward by server-side object copy with no re-upload and marked `unchanged`, so each job keeps every reached page until expiry. Missing earlier files SHALL be fetched without conditional headers as new files.

#### Scenario: Unchanged page copied forward

- **WHEN** a recrawled page answers 304
- **THEN** the new job's results hold that page's file, made by a server-side copy of the earlier file, and the index marks it `unchanged`

#### Scenario: The new job stays complete after the earlier job expires

- **WHEN** a recrawl marked a page `unchanged` and the earlier job's results then expire
- **THEN** the new job's page file for that page can still be read

#### Scenario: The earlier page file is gone

- **WHEN** a recrawl reaches a page whose earlier page file was already deleted
- **THEN** the page is requested without conditional headers and written as a new file

### Requirement: Crawl progress and recrawl state expire

Every crawl store part SHALL expire after `CRAWL_JOB_RETENTION_SECONDS`. Job records and results SHALL expire after it. Frontier keys (domain queues, seen set, in-flight counters, claim set, next fetch times, page lines) SHALL be deleted at `succeeded`, `failed` or `cancelled`, each carrying a Redis expiry of that bound set on create and on write. Each recrawl hash SHALL carry the same expiry, reset on each write of that tenant scope.

#### Scenario: Frontier keys go when the job ends

- **WHEN** a crawl job reaches `succeeded`
- **THEN** none of its frontier keys remains in Redis

#### Scenario: Frontier keys of a dead worker expire

- **WHEN** a worker stops during a job and nothing writes its frontier keys again
- **THEN** each of those keys carries a Redis expiry no longer than `CRAWL_JOB_RETENTION_SECONDS` from its last write

#### Scenario: Recrawl state expires

- **WHEN** a tenant crawls a scope once and never again
- **THEN** the recrawl state hash of that scope carries a Redis expiry no longer than `CRAWL_JOB_RETENTION_SECONDS` from that job's last write
