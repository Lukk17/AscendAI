# web-search-crawl-jobs Specification

## Purpose
Defines the crawl jobs of ascend-web-hunter: the polling job API on REST and MCP, the tenant scope, the request bounds and the page budget, the SSRF guard on every crawled URL, the shared Redis frontier that lets several instances work one crawl politely, the results in object storage with incremental recrawl, when a job ends failed, and how long every part of a crawl is kept.

## Requirements

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

Crawl requests SHALL carry 1 to CRAWL_MAX_SEEDS seeds, patterns at most CRAWL_MAX_PATTERNS each, max_depth to CRAWL_MAX_DEPTH, page_budget to CRAWL_MAX_PAGES, plus same_domain_only, respect_robots, output_format, extraction_schema, profile. Missing max_depth SHALL use CRAWL_DEFAULT_DEPTH (2), missing page_budget CRAWL_DEFAULT_PAGE_BUDGET (100), missing respect_robots false. Bounds and defaults SHALL be env settings defaulting 20, 50, 5, 10000. Only inside-bound URLs SHALL be visited. The page budget SHALL count the pages already finished (`fetched`, `unchanged` or `failed`) plus the pages claimed and still being read, by every instance together, and no URL SHALL be claimed while that sum has reached `page_budget`, so a job never reads more pages than its budget. A seed listed twice in one request SHALL be queued once. A page skipped for robots.txt SHALL be counted as `robots_skipped` in the job status counts, SHALL NOT count as `failed` and SHALL NOT spend page budget.

#### Scenario: Crawl respects scope

- **WHEN** a crawl runs with an include pattern, `max_depth` 2 and `page_budget` 50
- **THEN** it visits only matching URLs, no deeper than depth 2, and no more than 50 pages

#### Scenario: Pages in flight count against the budget

- **WHEN** a job with `page_budget` 5 has 3 finished pages and 2 pages claimed and still being read
- **THEN** no instance claims another URL of that job
- **AND** the job ends with at most 5 pages counted as `fetched`, `unchanged` or `failed`

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

### Requirement: A crawl that reaches no page ends failed

A job whose frontier and claims are empty, or whose page budget is reached with no claim left, SHALL end in state `succeeded` only when its `fetched` plus `unchanged` count is at least one. A job that ends with zero pages `fetched` or `unchanged` SHALL end in state `failed`, whatever its `failed` and `skipped_unsafe` counts are.

#### Scenario: Every page of a job fails

- **WHEN** a crawl job's only seed cannot be read by any crawl tier and the frontier is empty
- **THEN** the job reads `failed` with `fetched` 0, `unchanged` 0 and `failed` 1

#### Scenario: One page read is enough to succeed

- **WHEN** a crawl job reads one page and every other URL it claimed failed
- **THEN** the job reads `succeeded`

### Requirement: Crawl reads never reach the human-help tier

A crawl page read SHALL climb the tier ladder no further than `5-crawlee_adaptive`. It SHALL NOT run `6-novnc`, SHALL NOT open a human-intervention window, and SHALL NOT take an intervention slot. A page that every crawl tier refuses SHALL be counted as `failed` and the crawl SHALL go on with the next URL.

#### Scenario: A crawled page behind a challenge wall

- **WHEN** a crawl claims a page whose challenge wall no automated tier clears
- **THEN** the page is counted as `failed`
- **AND** no NoVNC window opens and no intervention flow is recorded for that page

### Requirement: Results stored in Floci under a configured prefix

Crawl results SHALL be written through the one S3 client in `src/storage/object_store.py` to `OBJECT_STORE_S3_ENDPOINT` (Floci locally, host port 9070) in `CRAWL_RESULT_S3_BUCKET` under `tenant/<tenantId>/` plus `CRAWL_RESULT_S3_PREFIX`, as one `pages.ndjson` index and one file per page under the job prefix. The connection SHALL use only `OBJECT_STORE_S3_ENDPOINT`, `OBJECT_STORE_S3_ACCESS_KEY`, `OBJECT_STORE_S3_SECRET_KEY`.

#### Scenario: Results land under the tenant and the prefix

- **WHEN** a crawl job of tenant `acme` succeeds
- **THEN** `tenant/acme/<prefix><job_id>/pages.ndjson` exists and lists every fetched page

### Requirement: Redis frontier with per-domain politeness

Frontier SHALL be Redis, per-domain delay and cap, sitemaps, robots.txt. respect_robots SHALL default to false and false SHALL be accepted for every site. A job with respect_robots false SHALL NOT skip a page or apply a Crawl-delay because of robots.txt, and CRAWL_DEFAULT_DELAY_SECONDS SHALL still apply to it. Every job SHALL fetch robots.txt once per origin for its sitemap addresses and SHALL seed the frontier from those sitemaps, and a job with respect_robots false SHALL use the file for nothing else. A failure to load robots.txt or a sitemap, or any other failure while seeding from sitemaps, SHALL be logged and SHALL NOT stop a job with respect_robots false from reading its pages. Workers SHALL share one frontier, no double fetch. Any instance SHALL work any jobs. Caps,delay,budget SHALL hold together. Any cancel SHALL stop all. Dead claims SHALL return after CRAWL_CLAIM_LEASE_SECONDS (120), fail after CRAWL_CLAIM_MAX_EXPIRIES (2). Each SHALL read at most CRAWL_WORKER_CONCURRENCY (4) at once. All shared changes SHALL be atomic. A job with respect_robots true SHALL read robots.txt as RFC 9309 says: a 4xx answer other than 429 SHALL allow every page of the origin, and a 5xx answer, a 429, or a network or connection error SHALL disallow every page of the origin for the rest of the job. A disallowed page SHALL NOT be fetched and SHALL be listed in `pages.ndjson` with `status` `skipped` and `reason` `robots_disallowed`. The rules and `Crawl-delay` SHALL be read for the agent `ascend-web-hunter-crawl`, so a group naming it SHALL win over the star group, and a `Crawl-delay` SHALL be cut to CRAWL_MAX_DELAY_SECONDS (60). A host name that does not resolve and a file slower than CRAWL_ROBOTS_TIMEOUT_SECONDS (30) SHALL count as unreachable. A robots.txt whose rule objects, counted as the rule sets of its user-agent lines times the rules of its other lines, exceed CRAWL_ROBOTS_MAX_RULES (1000000) SHALL NOT be parsed and SHALL disallow every page of its origin. The rule objects of the parsed robots.txt files one instance keeps SHALL stay under CRAWL_ROBOTS_CACHE_MAX_RULES (2000000) together, by evicting the least recently used files, and a value below CRAWL_ROBOTS_MAX_RULES SHALL be refused at startup. A job SHALL end once its `robots_skipped` count reaches `page_budget` times CRAWL_ROBOTS_SKIP_FACTOR (10). A sitemap SHALL be parsed as a stream, a sitemap that declares a DOCTYPE or holds a start tag that one parse step leaves unfinished with no `<` delivered SHALL yield no addresses and spend no budget, and an address longer than the longest allowed URL SHALL be dropped. Sitemap documents up to CRAWL_SITEMAP_MAX_DOCUMENTS and queued addresses up to `page_budget` SHALL be counted per job in each instance, not per origin. With `same_domain_only` true a sitemap on another registrable domain SHALL be dropped, and a sitemap on another registrable domain than the robots.txt that named it SHALL be fetched with no stored session. The sitemap work of one page SHALL stop at CRAWL_SITEMAP_TIMEOUT_SECONDS (60), which SHALL stay below CRAWL_CLAIM_LEASE_SECONDS, and the page SHALL still be read.

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

#### Scenario: A default crawl ignores robots.txt

- **WHEN** a crawl request that names no `respect_robots` meets a path its robots.txt disallows
- **THEN** that path is fetched
- **AND** its line in `pages.ndjson` reads `status` `fetched`

#### Scenario: A crawl that ignores robots.txt rules still uses its sitemaps

- **WHEN** a crawl with `respect_robots` false reads the first page of an origin whose robots.txt names a sitemap and disallows every page
- **THEN** robots.txt is fetched once for that origin
- **AND** the addresses of the sitemap seed the frontier and those pages are fetched

#### Scenario: A robots.txt that cannot be loaded leaves a default crawl working

- **WHEN** the robots.txt of an origin answers 500, 503 or 429, or its fetch fails, to a crawl with `respect_robots` false
- **THEN** the failure is logged and no sitemap address seeds the frontier
- **AND** the pages of that origin are fetched

#### Scenario: Ignoring robots.txt is accepted for every site

- **WHEN** a crawl is submitted with `respect_robots` false for any seed that passes the SSRF guard
- **THEN** the answer is HTTP 202 and a job exists

#### Scenario: The per-domain delay holds when robots.txt is ignored

- **WHEN** a crawl with `respect_robots` false reads a page of a domain whose robots.txt asks for a longer `Crawl-delay`
- **THEN** the next page of that domain may be claimed `CRAWL_DEFAULT_DELAY_SECONDS` after that claim and no earlier

#### Scenario: robots.txt disallow respected

- **WHEN** a crawl with `respect_robots` true meets a path its robots.txt disallows
- **THEN** that path is not fetched
- **AND** its line in `pages.ndjson` reads `status` `skipped` with `reason` `robots_disallowed`

#### Scenario: A missing robots.txt allows every page

- **WHEN** the robots.txt of an origin answers 404 or another 4xx status other than 429 to a crawl with `respect_robots` true
- **THEN** the crawl fetches the pages of that origin

#### Scenario: An unreachable robots.txt disallows every page

- **WHEN** the robots.txt of an origin answers 500, 503 or 429, or its connection fails, to a crawl with `respect_robots` true
- **THEN** no page of that origin is fetched for the rest of the job, a seed on that origin included
- **AND** each such page is listed in `pages.ndjson` with `status` `skipped` and `reason` `robots_disallowed`

#### Scenario: A page skipped for robots.txt spends no budget

- **WHEN** a crawl with `respect_robots` true and `page_budget` 1 has a disallowed seed and an allowed seed
- **THEN** the allowed page is fetched and the job status counts hold `robots_skipped` 1 and `failed` 0

#### Scenario: A hostile robots.txt is refused before it is parsed

- **WHEN** a robots.txt of 16000 user-agent lines and 23272 rule lines is read
- **THEN** it is not parsed and every page of its origin is disallowed

#### Scenario: A group naming the crawler wins over the star group

- **WHEN** a robots.txt disallows every page for the star group and allows every page for `ascend-web-hunter-crawl`
- **THEN** a crawl with `respect_robots` true fetches the pages of that origin

#### Scenario: A robots.txt built to multiply its rules is refused

- **WHEN** a robots.txt of 1000 lines `User-agent: a1*` and 1000 lines `Allow: /$/index.html` is read
- **THEN** it is not parsed and every page of its origin is disallowed

#### Scenario: Large robots.txt files stay under the cache limit

- **WHEN** one instance parses many large robots.txt files
- **THEN** the rule objects it keeps stay under CRAWL_ROBOTS_CACHE_MAX_RULES and the least recently used files are the ones evicted

#### Scenario: A page full of disallowed links ends the job

- **WHEN** a crawl with `respect_robots` true and `page_budget` 2 finds 100 links its robots.txt disallows
- **THEN** the job ends once `robots_skipped` reaches 2 times CRAWL_ROBOTS_SKIP_FACTOR

#### Scenario: A seed listed twice is queued once

- **WHEN** a crawl request lists the same seed twice
- **THEN** that seed is queued once

#### Scenario: A sitemap with an endless start tag yields nothing

- **WHEN** a sitemap document holds a start tag so long that a parse step delivers no `<` while still inside it
- **THEN** none of its addresses reaches the frontier and no sitemap budget is spent on them

#### Scenario: A sitemap with a DOCTYPE yields nothing

- **WHEN** a sitemap document declares a DOCTYPE
- **THEN** none of its addresses reaches the frontier

#### Scenario: A crawl result honours every bound

- **WHEN** a crawl with `respect_robots` true, an include pattern, `max_depth` 2 and `page_budget` 5 reaches `succeeded` on a site whose robots.txt disallows one path
- **THEN** its `pages.ndjson` lists at most 5 pages, none deeper than depth 2, none outside the include pattern and no `fetched` or `unchanged` line for the disallowed path

#### Scenario: Two workers share the frontier

- **WHEN** two workers consume the same frontier
- **THEN** each queued URL is fetched by exactly one worker

### Requirement: Gzip sitemaps are recognised by their bytes

A sitemap whose body starts with the gzip signature bytes `1f 8b` SHALL be inflated whatever its address and its declared Content-Type. CRAWL_SITEMAP_MAX_BYTES SHALL bound both the bytes read and the inflated size, so a file larger than the cap either way is skipped and logged.

#### Scenario: A gzip sitemap with a wrong Content-Type is read

- **WHEN** a sitemap at an address without `.gz` answers Content-Type `application/xml` with a gzip body
- **THEN** every URL it lists reaches the frontier

#### Scenario: A small gzip sitemap that inflates past the cap is skipped

- **WHEN** a sitemap whose compressed body fits CRAWL_SITEMAP_MAX_BYTES inflates to more than CRAWL_SITEMAP_MAX_BYTES
- **THEN** inflation stops at the cap, the file is skipped and logged, and none of its URLs reaches the frontier

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

Job records SHALL expire in Redis at `CRAWL_JOB_RETENTION_SECONDS` after their last write. The result objects in the bucket, `pages.ndjson` and every page file, a page file copied forward by a recrawl included, SHALL expire through one bucket lifecycle rule on the `tenant/` prefix. An S3 lifecycle rule counts whole days, so the rule SHALL carry `CRAWL_JOB_RETENTION_SECONDS` rounded up to whole days, at least one, counted by the store from when each object was written. A result object therefore expires within one day after the retention time, and the store deletes expired objects asynchronously. The service SHALL set the rule once per process at crawl worker startup, outside the page write path, and SHALL merge it by its rule ID into the bucket's existing lifecycle configuration, keeping every other rule. Setting it needs the `s3:GetLifecycleConfiguration` and `s3:PutLifecycleConfiguration` permissions on the bucket. When the store does not support lifecycle rules or refuses them, result objects do not expire: the service SHALL log a WARNING naming the bucket and the error, SHALL report it on the startup banner and in the `crawl_result_expiry_rule_applied` gauge, and SHALL still write every page. Frontier keys (domain queues, seen set, in-flight counters, claim set, next fetch times, page lines) SHALL be deleted at `succeeded`, `failed` or `cancelled`, each carrying a Redis expiry of that bound set on create and on write. Each recrawl hash SHALL carry the same expiry, reset on each write of that tenant scope.

#### Scenario: Result objects expire through the bucket lifecycle rule

- **WHEN** the crawl workers of an instance start against a store that supports lifecycle rules
- **THEN** `CRAWL_RESULT_S3_BUCKET` carries one lifecycle rule on the `tenant/` prefix whose expiry is `CRAWL_JOB_RETENTION_SECONDS` rounded up to whole days, at least one
- **AND** every other lifecycle rule the bucket held before is still there

#### Scenario: A store that refuses lifecycle rules still stores every page

- **WHEN** the store refuses the lifecycle rule or does not support it
- **THEN** a WARNING names the bucket and the error, the startup banner line `Crawl result expiry` reads a warning, and `crawl_result_expiry_rule_applied` reads 0
- **AND** every page of a crawl is still written and the job still ends `succeeded`

#### Scenario: Frontier keys go when the job ends

- **WHEN** a crawl job reaches `succeeded`
- **THEN** none of its frontier keys remains in Redis

#### Scenario: Frontier keys of a dead worker expire

- **WHEN** a worker stops during a job and nothing writes its frontier keys again
- **THEN** each of those keys carries a Redis expiry no longer than `CRAWL_JOB_RETENTION_SECONDS` from its last write

#### Scenario: Recrawl state expires

- **WHEN** a tenant crawls a scope once and never again
- **THEN** the recrawl state hash of that scope carries a Redis expiry no longer than `CRAWL_JOB_RETENTION_SECONDS` from that job's last write
