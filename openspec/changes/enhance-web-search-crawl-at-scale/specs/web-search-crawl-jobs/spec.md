## ADDED Requirements

### Requirement: Async crawl job API

ascend-web-hunter SHALL expose a crawl API (REST and MCP) that accepts seed URLs, include/exclude URL patterns, a maximum depth, a page budget, and an optional extraction schema, and returns a job id without blocking for the crawl. Job status SHALL be queryable, a terminal state MAY fire a configured webhook, and results SHALL be written to MinIO as markdown or NDJSON. Per-page extraction SHALL reuse the extraction pipeline from `enhance-web-search-extraction-and-tiers`.

#### Scenario: Crawl respects scope and returns a job id

- **WHEN** a crawl is submitted with a seed URL, an include pattern, max depth 2, and a page budget of 50
- **THEN** the response returns a job id immediately
- **AND** the crawl visits only URLs matching the include pattern, no deeper than depth 2, and no more than 50 pages
- **AND** results are written to the MinIO result store

#### Scenario: Terminal webhook fires

- **WHEN** a crawl job with a configured webhook reaches a terminal state
- **THEN** the webhook is called with the job outcome

### Requirement: Redis frontier with per-domain politeness

The crawl frontier SHALL be Redis-backed and SHALL enforce, per registrable domain, a crawl-delay and a concurrency cap, seed from sitemaps when present, and honour robots.txt (toggleable per job for sites the customer owns). Multiple worker processes SHALL be able to consume the same frontier concurrently without fetching the same URL twice, so a crawl scales by adding workers.

#### Scenario: robots.txt disallow respected

- **WHEN** a crawl with robots.txt honouring enabled encounters a path disallowed by the site's robots.txt
- **THEN** that path is not fetched

#### Scenario: Per-domain concurrency capped

- **WHEN** a crawl has many queued URLs for one domain and a per-domain concurrency cap of 2
- **THEN** no more than 2 requests to that domain are in flight at once

#### Scenario: Two workers share the frontier

- **WHEN** two worker processes consume the same crawl frontier
- **THEN** each queued URL is fetched by exactly one worker

### Requirement: Incremental recrawl via content hash and conditional requests

ascend-web-hunter SHALL store, per crawled URL, a content hash and the server's ETag / Last-Modified, and SHALL issue conditional requests on recrawl. A page reported unchanged (304 or an unchanged content hash) SHALL be short-circuited before extraction and result writing, so it is neither re-extracted nor re-embedded.

#### Scenario: Unchanged page skipped on recrawl

- **WHEN** a page is recrawled and the server returns 304 (or the content hash is unchanged)
- **THEN** the page is not re-extracted and no new result is written for it

#### Scenario: Changed page reprocessed

- **WHEN** a page's content hash differs on recrawl
- **THEN** the page is re-extracted and its result updated

### Requirement: Optional bring-your-own-proxy hook, never a hosted proxy

ascend-web-hunter SHALL provide an off-by-default configuration hook for customer-supplied proxy credentials, engaged only for crawl jobs when configured, building on the existing proxy seam. ascend-web-hunter SHALL NOT run, host, or resell a proxy network. With no proxy configured, crawling SHALL work unchanged at lower volume.

#### Scenario: Crawl works without a proxy

- **WHEN** a crawl runs with no proxy configured
- **THEN** it completes using the deployment's own network egress

#### Scenario: Configured proxy is used for the crawl

- **WHEN** customer proxy credentials are configured and a crawl runs
- **THEN** crawl fetches route through the supplied proxy
