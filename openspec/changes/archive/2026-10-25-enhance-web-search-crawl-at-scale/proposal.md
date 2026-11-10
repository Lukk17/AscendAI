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
- Results go to Floci, the S3-compatible store on host port 9070, in `CRAWL_RESULT_S3_BUCKET` under the
  configurable prefix `CRAWL_RESULT_S3_PREFIX`, below the tenant prefix `tenant/<tenantId>/`. The S3 client lives in
  `src/storage/object_store.py` with the shared connection settings `OBJECT_STORE_S3_ENDPOINT`,
  `OBJECT_STORE_S3_ACCESS_KEY` and `OBJECT_STORE_S3_SECRET_KEY`, so `add-file-download` reuses it.
- Every job belongs to one tenant, taken from the MCP `_meta` key `ascend.ai/tenant_id` or the REST header
  `X-Ascend-Tenant`, and a job of another tenant is not found.
- The internal tenant erase and export calls for one tenant's crawl data (owner answer 57 of 2026-10-03) are not in
  this change. Owner answer 70.3 of 2026-10-04 moved them into `add-audit-and-gdpr-compliance` (company, build group
  5), which adds them to this service later on the key layout this change defines. This change does not wait for it.
- Crawl progress (the frontier keys) and recrawl state expire, like results and job records.
- Errors are RFC 7807 problem bodies with the `https://ascend.ai/errors/` type base, a `code` and a `traceId`,
  built by the shared problem builder of the `ascend-python-common` library. The codes of this change are entries in
  the service's error registry, and the library logs, counts and maps them to MCP tool errors.
- The crawl API is part of ascend-web-hunter and adds no switch of its own. `add-deployment-modules` (build group 3,
  position 6) lands later and lists ascend-web-hunter as its module `web-search`, and `add-mcp-tool-servers` (build
  group 4, position 6) later makes the agent see the tools as `web_crawl_*`. This change waits for neither.
- A Redis frontier with per-domain politeness: robots.txt, crawl-delay, a per-domain concurrency cap and sitemap
  seeding. More worker containers share the same frontier.
- Safe with several ascend-web-hunter instances at once (owner decision 87 of 2026-10-08): every instance works on
  every job, and job pickup, URL claims, the per-domain cap, the crawl delay, the page budget, cancel and the job
  record live in Redis and change only through atomic Redis scripts. A claim of an instance that stops is taken back
  after its lease (design D15).
- Incremental recrawl: content hash plus `ETag` and `Last-Modified` conditional requests. A page found unchanged has
  its earlier page file copied forward into the new job's results with a server-side copy, so each job stays
  complete until it expires (owner answer 59 of 2026-10-03).
- SSRF rules for seeds and every discovered link.
- The existing proxy seam gains a customer-supplied proxy hook for crawl jobs, off by default.
- The RAG connector that lands crawl output into tenant knowledge bases is not in this change. It moved to
  `add-web-crawl-rag-connector`, which depends on `add-connector-framework` (the connector framework, split out of
  `add-document-connectors` on 2026-10-04).

## Capabilities

### New Capabilities

- `web-search-crawl-jobs`: the job API, the request schema, result storage, the frontier, politeness, incremental
  recrawl, the SSRF rules for crawl URLs, the tenant scoping, and the expiry of crawl progress and recrawl state.

### Modified Capabilities

- `web-search-antibot-evasion`: "Optional proxy egress, disabled by default" gains a separate crawl proxy that is
  used only by crawl jobs, and no longer names FlareSolverr, which `remove-flaresolverr-tier` (position 7) removed
  before this change. "No outbound self-throttling, and inbound limits only per caller", the name
  `add-ascend-python-common` gave the old "No service-side request rate limiting", is narrowed so crawl politeness is
  allowed while single reads stay unthrottled.

## Dependencies and Build Order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders, among them the owner order of
2026-10-01): build group 2 (web-hunter), position 9. It needs `enhance-web-search-tier-ladder` (position 5, every page
is read through the normal ladder), `enhance-web-search-extraction-and-tiers` (position 6, the `output_format` and
`extraction_schema` a job may ask for), `add-ascend-python-common` (position 1, the problem builder, error registry and
refusal handling of design D9, and the URI guard) and `add-python-runtime-upgrades` (position 2, so the MCP tools and
tests of this change are written against FastMCP 4 and every test that uses `fastmcp.Client` names its protocol era,
its D9). `remove-flaresolverr-tier` (position 7) lands before it, so no crawl fetch uses FlareSolverr. Its e2e specs
use the shared fake site of `add-web-search-scraping-e2e` (build group 1). `add-file-download` (position 10) builds its
download storage on the `src/storage/object_store.py` client of this change (its D12), and
`add-web-crawl-rag-connector` (build group 4) builds on this change later. A crawl call that names no tenant runs as
the tenant `default`, the tenant a personal deployment runs as, the same rule `add-file-download` follows (owner answer
54.5 of 2026-10-03). Every caller sends no tenant or `default` until `add-mcp-tool-servers` (build group 4) makes the
agent fill the MCP `_meta` key, and this change does not wait for it. There is no `CRAWL_DEFAULT_TENANT` setting.
`add-audit-and-gdpr-compliance` (company, build group 5) adds the internal tenant erase and export calls later (owner
answer 70.3 of 2026-10-04). This change does not wait for it.

## Impact

- `apps/ascend-web-hunter/src/crawl/`: new package (`models.py`, `frontier.py`, `worker.py`, `robots.py`,
  `result_store.py`, `job_service.py`).
- `apps/ascend-web-hunter/src/storage/object_store.py`: new, the one S3 client of the service.
- `apps/ascend-web-hunter/src/api/rest/crawl_endpoints.py`: new router under `/api/v1/crawl` with the job calls,
  mounted in `src/main.py`.
- `apps/ascend-web-hunter/src/api/mcp/mcp_server.py`: four tools.
- `apps/ascend-web-hunter/src/proxy/proxy_provider.py`: the crawl proxy.
- `apps/ascend-web-hunter/src/config/config.py`: the settings in `design.md`.
- `apps/ascend-web-hunter/pyproject.toml`: an S3 client (`boto3` or `aioboto3`, exact pin) and `protego` for
  robots.txt.
- `compose.ascend-web-hunter.yaml` and `apps/ascend-web-hunter/deploy-standalone/compose.yaml`: the shared
  `OBJECT_STORE_S3_*` connection variables and every `CRAWL_*` setting of design D16 as `${VAR:-default}` (owner rule
  98 of 2026-10-08), with matching lines in both `.env.example` files and the standalone README table.
- `apps/ascend-web-hunter/docs/configuration.md`: one row per setting of design D16, ending "Added by
  `enhance-web-search-crawl-at-scale`.", in the same commit as the setting.
- e2e: one new spec (next free number at implementation time), `<N>-crawl-jobs` (a crawl of the shared e2e fake site
  with recrawl), its Bruno folder `docs/api/request/AscendAI/web-hunter/testing/crawl/`, and its place in
  `docs/E2E_RUN_SCENARIOS.md`. The refusal spec `<N>-crawl-refusals` was dropped by owner decision 91.3 of 2026-10-08,
  because the unit tests prove every refusal it repeated.
- Docs: `AGENTS.md`, `README.md`, `docs/configuration.md`, ADR-019 for the crawl model, and a CHANGELOG entry with
  the version bump from 0.0.14 to 0.0.15.

## Relevant Skills

- `/python-patterns`
- `/tdd-workflow`
- `/api-design`
- `/backend-patterns`
- `/docker-patterns`
- `/security-review`
- `/architecture-decision-records`
