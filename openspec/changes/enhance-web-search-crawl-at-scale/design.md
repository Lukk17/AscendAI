## Context

ascend-web-hunter reads one URL per request through its tier ladder, with an SSRF guard re-validated on every redirect
hop and connect-time address pinning (ADR-012). ascend-ocr already ships a job API with polling and results in Floci
(its ADR-008 and ADR-009). The crawl job API follows the same shape so callers learn one idiom.

## Decisions

### D1: Polling job API, no webhook

Endpoints under `/api/v1/crawl`:

| Method | Path | Answer |
| :-- | :-- | :-- |
| POST | `/api/v1/crawl/jobs` | 202 with `job_id`, `state` `waiting`, `poll_after_seconds` |
| GET | `/api/v1/crawl/jobs/{job_id}` | 200 with state, counts and result keys, 404 `JOB_NOT_FOUND` |
| GET | `/api/v1/crawl/jobs` | 200 with the jobs still retained |
| DELETE | `/api/v1/crawl/jobs/{job_id}` | 200 with state `cancelled`, 404 when unknown |

MCP tools: `crawl_submit`, `crawl_job_status`, `crawl_list_jobs`, `crawl_cancel_job`, same arguments and results.
States: `waiting`, `running`, `succeeded`, `failed`, `cancelled`. A webhook was rejected for v1: it needs its own SSRF
guard on an address the caller chooses, signing and retries, and polling covers every current caller.

### D2: Request schema

```json
{
  "seeds": ["https://docs.example.com/"],
  "include_patterns": ["/guide/*"],
  "exclude_patterns": ["*/archive/*"],
  "max_depth": 2,
  "page_budget": 100,
  "same_domain_only": true,
  "respect_robots": true,
  "output_format": "text",
  "extraction_schema": null,
  "profile": null
}
```

- `seeds`: 1 to `CRAWL_MAX_SEEDS` (default 20) absolute `http` or `https` URLs.
- `include_patterns` and `exclude_patterns`: up to 50 each, glob patterns matched with `fnmatch` against the URL path.
  Globs, not regular expressions, so a caller cannot submit a pattern with catastrophic backtracking.
- `max_depth`: 0 to `CRAWL_MAX_DEPTH` (default 5), default 2.
- `page_budget`: 1 to `CRAWL_MAX_PAGES` (default 10000), default 100.
- `same_domain_only`: default true, links outside the seeds' registrable domains are dropped.
- `respect_robots`: default true. False is allowed only for a seed domain listed in `CRAWL_ROBOTS_OPT_OUT_DOMAINS`
  (default empty), meaning a site the operator owns.
- `output_format`, `extraction_schema`, `profile`: the same meaning and rules as on a single read.

### D3: Results in Floci

S3 client settings: `CRAWL_RESULT_S3_ENDPOINT` (default `http://localhost:9070`, Floci), `CRAWL_RESULT_S3_BUCKET`
(default `web-hunter-crawls`), `CRAWL_RESULT_S3_PREFIX` (default `crawl-results/`), `CRAWL_RESULT_S3_ACCESS_KEY` and
`CRAWL_RESULT_S3_SECRET_KEY`. Keys are `<prefix><job_id>/pages.ndjson` (one line per page: URL, status, content hash,
fetched time, result key) and `<prefix><job_id>/pages/<sha256 of URL>.md` (or `.json` for `schema`). Job records and
results expire after `CRAWL_JOB_RETENTION_SECONDS` (default 604800).

### D4: SSRF rules for crawl URLs

- Every seed is checked at submission with the same guard single reads use. A seed with a scheme other than `http` or
  `https`, with userinfo, or resolving to a private, loopback, link-local or reserved address is refused with HTTP 400
  `UNSAFE_URI` and the job is not created.
- Every discovered link, every redirect hop, every robots.txt fetch and every sitemap fetch goes through the same
  guard and connect-time pinning (ADR-012). A link that fails is dropped and counted as `skipped_unsafe`.
- Links are taken only from `href` attributes and sitemap `loc` entries, never from scripts.

### D5: Frontier and politeness

Redis keys per job: a per-domain queue, a seen set of normalised URLs, and a per-domain in-flight counter. Defaults:
`CRAWL_DOMAIN_CONCURRENCY` 2, `CRAWL_DEFAULT_DELAY_SECONDS` 1, robots.txt `Crawl-delay` used when larger. robots.txt
is parsed with `protego`. Sitemaps from robots.txt seed the frontier. Each worker claims a URL atomically, so two
workers never fetch the same URL. Politeness applies only inside crawl jobs. Single reads stay unthrottled.

### D6: Incremental recrawl

Per normalised URL the store keeps the content hash, `ETag` and `Last-Modified` from the last job with the same seeds
and patterns. A recrawl sends `If-None-Match` and `If-Modified-Since`. A 304 or an equal hash writes no new page file
and marks the page `unchanged` in `pages.ndjson`.

### D7: Customer proxy, crawl only

`CRAWL_PROXY_URL` (default empty) routes crawl fetches through a proxy the customer supplies. Single reads keep using
the existing `PROXY_*` seam. The project never runs or resells a proxy.

## Risks

- Scale claims: the honest ceiling is the hundreds-of-thousands-of-pages class per job across several workers, and
  the docs say so.
- A crawl getting the deployment's address blocked: politeness is on by default and the per-domain cap is low.
