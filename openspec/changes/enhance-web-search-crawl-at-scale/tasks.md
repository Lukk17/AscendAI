# Tasks — enhance-web-search-crawl-at-scale

## 1. Crawl job API and result store

- [ ] 1.1 Create `src/crawl/` with a crawl-job model (seed URLs, include/exclude patterns, max depth, page budget, optional extraction schema, status, counts)
- [ ] 1.2 Add REST + MCP crawl endpoints/tools: submit (returns job id), status, cancel; optional terminal webhook dispatch
- [ ] 1.3 Write results to MinIO as markdown or NDJSON under a job-scoped key; per-page extraction reuses the `enhance-web-search-extraction-and-tiers` pipeline
- [ ] 1.4 Tests: a crawl over a fixture site respects include/exclude patterns, max depth, and page budget; results land in the result store; webhook fires on completion

## 2. Redis frontier and politeness

- [ ] 2.1 Implement the Redis-backed URL frontier: per-domain queue, dedup, crawl-delay, per-domain concurrency cap
- [ ] 2.2 Honour robots.txt (toggleable per job) and seed from sitemaps when present
- [ ] 2.3 Make workers horizontally scalable: multiple worker loops/containers consume the same frontier with no central coordinator beyond Redis
- [ ] 2.4 Tests: robots.txt disallow is respected; per-domain concurrency cap enforced; two workers share the frontier without double-fetching a URL

## 3. Incremental recrawl

- [ ] 3.1 Store per-URL content hash + ETag / Last-Modified; issue conditional requests on recrawl
- [ ] 3.2 Short-circuit unchanged pages (304 or unchanged hash) before extraction and result write
- [ ] 3.3 Tests: an unchanged page on recrawl is skipped via a conditional request and not re-extracted; a changed page is re-processed

## 4. Bring-your-own-proxy hook

- [ ] 4.1 Extend the existing proxy seam with a config hook for customer-supplied proxy credentials (provider-agnostic), off by default
- [ ] 4.2 Engage the proxy only for crawl jobs when configured; document that ascend-web-hunter never runs or resells proxies
- [ ] 4.3 Tests: with no proxy configured crawling works unchanged; with a stub proxy configured, crawl requests route through it

## 5. Web connector into RAG (AscendAgent)

- [ ] 5.1 Add a `web` connector type under `service/connector/` (`add-document-connectors` framework): config = seed URLs / patterns / schedule
- [ ] 5.2 On each scheduled run, trigger an ascend-web-hunter crawl, land the output in the tenant's MinIO prefix, and trigger the existing ingestion pipeline (land-bytes-then-ingest, no parallel parse path)
- [ ] 5.3 Propagate source-page deletions through the framework's deletion path (`add-document-management-api`)
- [ ] 5.4 Tests: a `web` connector run lands crawl output under the tenant prefix and the existing pipeline indexes it into tenant RAG; a removed source page propagates to MinIO + Qdrant on the next run

## 6. Documentation and scale honesty

- [ ] 6.1 Update `ascend-web-hunter/AGENTS.md`: crawl API, frontier politeness, incremental recrawl, BYO-proxy hook, and an honest scale statement (hundreds-of-thousands-of-pages class, not proxy-network scale)
- [ ] 6.2 Extend `docs/CONNECTORS.md` (from `add-document-connectors`) with the web connector setup
- [ ] 6.3 Run `pytest` for ascend-web-hunter and `./gradlew test` for AscendAgent's connector additions; all green
