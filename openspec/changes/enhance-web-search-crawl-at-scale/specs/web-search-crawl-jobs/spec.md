## ADDED Requirements

### Requirement: Polling crawl job API

ascend-web-hunter SHALL expose `POST /api/v1/crawl/jobs`, `GET /api/v1/crawl/jobs/{job_id}`, `GET /api/v1/crawl/jobs` and `DELETE /api/v1/crawl/jobs/{job_id}`, and the MCP tools `crawl_submit`, `crawl_job_status`, `crawl_list_jobs` and `crawl_cancel_job`. A submission SHALL answer HTTP 202 with a `job_id` without waiting for the crawl. Status SHALL be read by polling. No webhook SHALL be called.

#### Scenario: Submission returns a job id

- **WHEN** a valid crawl request is submitted
- **THEN** the answer is HTTP 202 with a `job_id` and state `waiting`

#### Scenario: Unknown job

- **WHEN** a caller reads a `job_id` that does not exist
- **THEN** the answer is HTTP 404 with code `JOB_NOT_FOUND`

### Requirement: Crawl request bounds

A crawl request SHALL carry 1 to `CRAWL_MAX_SEEDS` seeds, glob `include_patterns` and `exclude_patterns`, a `max_depth` up to `CRAWL_MAX_DEPTH`, a `page_budget` up to `CRAWL_MAX_PAGES`, `same_domain_only`, `respect_robots`, and the single-read fields `output_format`, `extraction_schema` and `profile`. The crawl SHALL visit only URLs inside these bounds.

#### Scenario: Crawl respects scope

- **WHEN** a crawl runs with an include pattern, `max_depth` 2 and `page_budget` 50
- **THEN** it visits only matching URLs, no deeper than depth 2, and no more than 50 pages

### Requirement: Crawl URLs pass the SSRF guard

Every seed SHALL be checked at submission, and a seed that is not `http` or `https`, carries userinfo, or resolves to a private, loopback, link-local or reserved address SHALL be refused with HTTP 400 `UNSAFE_URI` and no job created. Every discovered link, redirect hop, robots.txt fetch and sitemap fetch SHALL pass the same guard with connect-time pinning, and a link that fails SHALL be dropped and counted.

#### Scenario: Private seed refused

- **WHEN** a crawl is submitted with the seed `http://10.0.0.1/`
- **THEN** the answer is HTTP 400 `UNSAFE_URI` and no job exists

#### Scenario: Discovered private link dropped

- **WHEN** a crawled page links to `http://127.0.0.1/admin`
- **THEN** that link is not fetched and the job counts it as `skipped_unsafe`

### Requirement: Results stored in Floci under a configured prefix

Crawl results SHALL be written to the S3-compatible store at `CRAWL_RESULT_S3_ENDPOINT` (Floci locally, host port 9070) in `CRAWL_RESULT_S3_BUCKET` under `CRAWL_RESULT_S3_PREFIX`, as one `pages.ndjson` index and one file per page, all under the job's own key prefix.

#### Scenario: Results land under the prefix

- **WHEN** a crawl job succeeds
- **THEN** `<prefix><job_id>/pages.ndjson` exists and lists every fetched page

### Requirement: Redis frontier with per-domain politeness

The frontier SHALL be Redis-backed and SHALL enforce, per registrable domain, a crawl delay and a concurrency cap, seed from sitemaps, and honour robots.txt. `respect_robots=false` SHALL be accepted only for domains listed in `CRAWL_ROBOTS_OPT_OUT_DOMAINS`. Several workers SHALL share one frontier without fetching a URL twice.

#### Scenario: robots.txt disallow respected

- **WHEN** a crawl meets a path its robots.txt disallows
- **THEN** that path is not fetched

#### Scenario: Two workers share the frontier

- **WHEN** two workers consume the same frontier
- **THEN** each queued URL is fetched by exactly one worker

### Requirement: Incremental recrawl

ascend-web-hunter SHALL store per crawled URL its content hash, `ETag` and `Last-Modified`, and SHALL send conditional requests on a recrawl. A 304 or an unchanged hash SHALL write no new page file and SHALL mark the page `unchanged`.

#### Scenario: Unchanged page skipped

- **WHEN** a recrawled page answers 304
- **THEN** no new page file is written and the index marks it `unchanged`
