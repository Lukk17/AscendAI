## Why

ascend-web-hunter reads one URL at a time. There is no way to crawl a whole site — a customer's documentation portal, an intranet, a knowledge base — into the RAG store, which is the single most valuable thing a scraper can do for this platform: point it at a site and get a continuously fresh, private knowledge base. No competitor offers scrape-to-RAG inside a sovereign, on-premises stack, and the machinery is a short step from the per-page reader plus the connector framework the platform already has.

Crawling at volume also surfaces the one problem single-page reads never hit: IP bans. A site sees hundreds of requests from one address and blocks it. The answer is not to build or resell proxies (a legal and cost liability), but to add an optional hook where a customer plugs in their own proxy provider — used only when large crawls need it.

## What Changes

- **Job-based crawl API** (REST + MCP), mirroring the async ingestion-run pattern: a crawl request with seed URLs, include/exclude URL patterns, max depth, page budget, and an optional extraction schema returns a job id. Status is queryable, terminal state fires an optional webhook, and results are written to MinIO as markdown or NDJSON. Per-page extraction reuses the `enhance-web-search-extraction-and-tiers` pipeline.
- **URL frontier with per-domain politeness**: a Redis-backed frontier honouring robots.txt (toggleable per job), crawl-delay, per-domain concurrency caps, and sitemap seeding. Scale is horizontal — additional worker containers consume the same frontier. The honest target is the hundreds-of-thousands-of-pages class per job, not proxy-network scale, and the docs say so.
- **Incremental recrawl**: content hashes plus ETag / Last-Modified conditional requests, so an unchanged page costs a single conditional round-trip and is neither re-extracted nor re-embedded.
- **Optional bring-your-own-proxy hook**: a config slot for customer-supplied proxy credentials (e.g. Oxylabs, Webshare), building on the proxy seam `enhance-web-search-scraping` already ships. ascend-web-hunter never runs or resells proxies; the hook is off by default and only engaged when a job's scale requires it.
- **Web connector into RAG**: a `web` connector type in the `add-document-connectors` framework whose job is a scheduled crawl that lands its output in MinIO under the tenant prefix and triggers the existing ingestion pipeline — the same land-bytes-then-ingest contract every other connector follows, no parallel parse path. This is what turns a crawl into a continuously fresh tenant knowledge base.

## Capabilities

### New Capabilities

- `web-search-crawl-jobs`: async crawl job API (seed/patterns/depth/budget/schema, job id, status, webhook, MinIO results), the Redis URL frontier with robots/crawl-delay/per-domain concurrency/sitemap politeness, horizontal worker scaling, incremental recrawl via content hash + conditional requests, and the optional off-by-default bring-your-own-proxy hook.
- `web-search-rag-connector`: a `web` connector in the `add-document-connectors` framework that runs a scheduled crawl, lands output in MinIO under the tenant prefix, and triggers the existing ingestion pipeline (land-bytes-then-ingest, deletion propagation reused), turning a site into a continuously fresh tenant knowledge base.

### Modified Capabilities

(none as spec deltas — the connector framework (`add-document-connectors`) and the extraction pipeline (`enhance-web-search-extraction-and-tiers`) are defined in sibling changes, not archived to `openspec/specs/`. The `web` connector is expressed as an ADDED capability here that plugs into the framework's landing contract; the framework hook points are named in the tasks.)

## Impact

- **Depends on**: `enhance-web-search-extraction-and-tiers` (per-page extraction/tiers used by the crawler), `enhance-web-search-scraping` (proxy seam, session/fingerprint machinery), and `add-document-connectors` (the connector framework the `web` connector plugs into, plus its deletion-propagation path). The `web` connector also inherits `add-tenant-isolation` (tenant-prefix landing) transitively through the connector framework.
- **ascend-web-hunter (code)**: `src/crawl/` package (job model, frontier over Redis, worker loop, robots/sitemap handling, incremental-recrawl hash+conditional logic), `src/api/rest` + `src/api/mcp` crawl endpoints/tools, results writer to MinIO (markdown/NDJSON), webhook dispatch; `pyproject.toml` any frontier/robots deps; config for concurrency caps, politeness, proxy hook, result store.
- **ascend-ai-agent (code)**: a `web` connector type under the `service/connector/` framework from `add-document-connectors` — connector config (seed/patterns/schedule), a client that triggers an ascend-web-hunter crawl and awaits/streams results into the tenant MinIO prefix, then the standard ingestion trigger; deletion propagation reuses the framework path.
- **Compose**: optional additional ascend-web-hunter worker replicas consuming the frontier; documented, not default.
- **Docs**: `apps/ascend-web-hunter/AGENTS.md` crawl API + politeness + BYO-proxy; `docs/CONNECTORS.md` (from `add-document-connectors`) gains the web connector; honest scale statement.
- **Tests**: crawl job over a fixture site respects include/exclude, depth, and budget; frontier honours robots.txt and per-domain concurrency; incremental recrawl skips unchanged pages via conditional requests; BYO-proxy engaged only when configured; web connector lands crawl output under the tenant prefix and the existing pipeline indexes it; source-page deletion propagates.

## Relevant Skills

- `/python-patterns`
- `/python-testing`
- `/api-design`
- `/docker-patterns`
- `/security-review`
- `/springboot-patterns`
