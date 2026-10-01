## Why

ascend-web-hunter reads one URL at a time. There is no way to crawl a whole site, such as a documentation portal or
an intranet, in one request. Crawling at volume also brings the one problem single reads never hit: one address
sending hundreds of requests gets blocked. The answer is politeness by default and an optional hook for a proxy the
customer supplies, never a proxy this project runs.

## What Changes

- A crawl job API, polling only. `POST /api/v1/crawl/jobs` answers HTTP 202 with a `job_id`. `GET
  /api/v1/crawl/jobs/{job_id}` returns the state, counts and result keys. `GET /api/v1/crawl/jobs` lists jobs.
  `DELETE /api/v1/crawl/jobs/{job_id}` cancels. MCP tools `crawl_submit`, `crawl_job_status`, `crawl_list_jobs` and
  `crawl_cancel_job` mirror them. There is no webhook in v1.
- Results go to Floci, the S3-compatible store on host port 9070, under the configurable prefix
  `CRAWL_RESULT_S3_PREFIX`.
- A Redis frontier with per-domain politeness: robots.txt, crawl-delay, a per-domain concurrency cap and sitemap
  seeding. More worker containers share the same frontier.
- Incremental recrawl: content hash plus `ETag` and `Last-Modified` conditional requests.
- SSRF rules for seeds and every discovered link.
- The existing proxy seam gains a customer-supplied proxy hook for crawl jobs, off by default.
- The RAG connector that lands crawl output into tenant knowledge bases is not in this change. It moved to
  `add-web-crawl-rag-connector`, which depends on `add-document-connectors`.

## Capabilities

### New Capabilities

- `web-search-crawl-jobs`: the job API, the request schema, result storage, the frontier, politeness, incremental
  recrawl and the SSRF rules for crawl URLs.

### Modified Capabilities

- `web-search-antibot-evasion`: "Optional proxy egress, disabled by default" gains a separate crawl proxy that is
  used only by crawl jobs, and "No service-side request rate limiting" is narrowed so crawl politeness is allowed
  while single reads stay unthrottled.

## Dependencies and Build Order

Last in the owner's order of 2026-10-01: `open-several-novnc-windows-at-once`, `detect-challenge-walls-in-any-language`,
`enhance-web-search-tier-ladder`, `enhance-web-search-extraction-and-tiers` (structured extraction), then this change.
It depends on the tier ladder (every page is read through the normal ladder) and on structured extraction (the
`output_format` and `extraction_schema` a job may ask for). `add-web-crawl-rag-connector` depends on this change.

## Impact

- `apps/ascend-web-hunter/src/crawl/`: new package (`models.py`, `frontier.py`, `worker.py`, `robots.py`,
  `result_store.py`, `job_service.py`).
- `apps/ascend-web-hunter/src/api/rest/crawl_endpoints.py`: new router under `/api/v1/crawl`, mounted in `src/main.py`.
- `apps/ascend-web-hunter/src/api/mcp/mcp_server.py`: four tools.
- `apps/ascend-web-hunter/src/proxy/proxy_provider.py`: the crawl proxy.
- `apps/ascend-web-hunter/src/config/config.py`: the settings in `design.md`.
- `apps/ascend-web-hunter/pyproject.toml`: an S3 client (`boto3` or `aioboto3`, exact pin) and `protego` for
  robots.txt.
- `compose.ascend-web-hunter.yaml` and `apps/ascend-web-hunter/deploy-standalone/compose.yaml`: the crawl S3 variables,
  with matching lines in both `.env.example` files and the standalone README table.
- Docs: `AGENTS.md`, `README.md`, `docs/configuration.md`, ADR-018 for the crawl model, and a CHANGELOG bump.

## Relevant Skills

- `/python-patterns`
- `/tdd-workflow`
- `/api-design`
- `/backend-patterns`
- `/docker-patterns`
- `/security-review`
- `/architecture-decision-records`
