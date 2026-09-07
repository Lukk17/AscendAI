# Design — enhance-web-search-crawl-at-scale

## Context

ascend-web-hunter is a per-URL reader. The platform has a document-ingestion pipeline (MinIO → DocumentRouter → Qdrant) and, via `add-document-connectors`, a connector framework whose contract is "land bytes in MinIO under the tenant prefix, then trigger the existing ingestion." `enhance-web-search-extraction-and-tiers` provides best-in-class per-page extraction and a proxy seam already exists from `enhance-web-search-scraping`. What is missing is the layer that turns "read one URL" into "crawl a site and keep it fresh in RAG."

## Goals / Non-Goals

**Goals:**

- An async crawl job API that mirrors the platform's async-run pattern and writes results to MinIO.
- A polite, horizontally-scalable frontier honouring robots.txt, crawl-delay, and per-domain concurrency.
- Incremental recrawl that makes re-crawling cheap.
- An optional bring-your-own-proxy hook for scale, never a proxy we run.
- A `web` connector that lands crawl output into tenant RAG through the existing framework.

**Non-Goals:**

- Building, running, or reselling proxies.
- Per-URL result caching and change-monitoring (dropped by product decision).
- Competing on proxy-network scale; the honest ceiling is hundreds of thousands of pages per job.
- Any parallel parse path — the connector lands bytes and reuses the ingestion pipeline like every other connector.

## Decisions

### D1 — Async crawl jobs, results to MinIO, mirroring the ingestion-run pattern

A crawl request (seed URLs, include/exclude patterns, max depth, page budget, optional extraction schema) returns a job id immediately; status is polled; a terminal webhook is optional. Results are written to MinIO as markdown or NDJSON. This matches the async-run shape `add-document-management-api` uses, so operators and the eventual Flutter client see one consistent job idiom.

### D2 — Redis frontier, horizontal workers, politeness first

The URL frontier lives in Redis: a per-domain queue with crawl-delay and a per-domain concurrency cap, seeded from sitemaps when present, honouring robots.txt (toggleable per job for internal sites the customer owns). Scale is adding ascend-web-hunter worker containers that consume the same frontier — no central coordinator beyond Redis. Politeness is a first-class default, not an afterthought, because an impolite crawler gets the deployment's IP banned.

### D3 — Incremental recrawl via content hash + conditional requests

Each fetched URL stores a content hash and the server's ETag / Last-Modified. A recrawl issues conditional requests; a 304 or an unchanged hash short-circuits before extraction and embedding. This makes "keep the knowledge base fresh" cheap enough to run often.

### D4 — Bring-your-own-proxy hook, off by default

The proxy seam from `enhance-web-search-scraping` is extended with a config hook for customer-supplied proxy credentials, engaged only when a job's scale requires it. ascend-web-hunter never runs or resells proxies — this keeps the on-prem story clean and the abuse liability with the proxy vendor the customer chose. With no proxy configured, crawling works exactly as today, capped at lower volume.

### D5 — The `web` connector plugs into the existing connector framework

The scrape-to-RAG capability is a `web` connector type in `add-document-connectors`, not a new pipeline. Its config is seed URLs / patterns / schedule; on each scheduled run it triggers an ascend-web-hunter crawl, lands the output in the tenant's MinIO prefix, and triggers the existing ingestion — the framework's land-bytes-then-ingest contract. Source-page deletion propagates through the framework's deletion path (owned by `add-document-management-api`). No parallel parse path, tenant isolation inherited from the framework.

## Risks / Trade-offs

- [Crawl scale claims overpromise] → the frontier targets the hundreds-of-thousands class; docs state this honestly rather than implying proxy-network scale.
- [A crawl hammers a site and gets banned] → politeness (robots, crawl-delay, per-domain concurrency) is default-on; BYO-proxy spreads load only when the customer opts in.
- [Connector crawl overlaps a manual crawl of the same site] → jobs are keyed by connector + scope; a run in progress blocks a duplicate, same as other connectors.
- [Freshness vs cost] → incremental recrawl with conditional requests keeps repeat crawls cheap; schedule is per connector.

## Open Questions

- None blocking. Exact frontier/robots library choices are validated in implementation; the job and connector contracts do not depend on them.
