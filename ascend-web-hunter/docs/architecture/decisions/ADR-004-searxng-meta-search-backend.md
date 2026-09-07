# ADR-004: SearXNG as the sole meta-search backend

## Status

Accepted — 2026-05-31

## Context

The service needs a search backend that returns URLs for a query. Options include: direct integration with
commercial search APIs (Google Custom Search, Bing Web Search), open-source crawlers, or a self-hosted meta-search
engine. Commercial APIs require per-query billing and API keys, which add cost and deployment friction. The
AscendAI stack is self-hosted by design; search should follow the same principle.

SearXNG is a self-hosted meta-search engine that aggregates results from multiple sources (Google, Bing, DuckDuckGo,
and others) without exposing individual user queries to those providers. It exposes an HTTP search interface that
returns either JSON or HTML depending on configuration.

A secondary issue is SearXNG's rate-limit behaviour. Many SearXNG instances disable the JSON API (`format=json`)
by default to discourage bot traffic. The HTML interface is always enabled.

## Decision

`SearxngClient` (`src/search/search_client.py:12`) sends `GET /search?q={query}&format=html` to the configured
`SEARXNG_BASE_URL`. It parses the HTML response with BeautifulSoup, selecting `article.result` elements from
SearXNG's default Catppuccin/Simple theme structure and extracting title, URL, and content snippet.

The client uses `httpx.AsyncClient` with `SEARCH_TIMEOUT` (default 10 s). The previous implementation used a
synchronous `httpx.Client`, which blocked the async event loop for the duration of the SearXNG request. A comment
in the source (`src/search/search_client.py:16`) records this as the reason for the change.

Request headers send `SEARXNG_USER_AGENT`, `SEARXNG_X_REAL_IP`, and `SEARXNG_X_FORWARDED_FOR` to pass SearXNG's
request checks (some instances enforce these headers to distinguish direct browser access from bot access).

Both `GET /api/v1/web/search` (REST) and the `web_search` MCP tool delegate to `SearxngClient.search`. The `limit`
parameter caps the number of articles parsed; all parsing stops once `limit` results are collected.

## Alternatives Considered

### Alternative 1: Google Custom Search API
- **Pros**: High-quality results; JSON response; no HTML parsing.
- **Cons**: Requires an API key and a Google Cloud project per deployment. Free tier is 100 queries per day;
  production load requires billing. Sends every query to Google.
- **Why not**: Violates the privacy-first, self-hosted principle. Per-query billing makes cost unpredictable.

### Alternative 2: Bing Web Search API
- **Pros**: JSON response; straightforward pagination.
- **Cons**: Same API-key and billing concerns as Google. Microsoft data residency terms may conflict with some
  deployment contexts.
- **Why not**: Same reasons as Google Custom Search.

### Alternative 3: Scrapy / direct search-engine scraping
- **Pros**: No intermediate service.
- **Cons**: Search engines actively block scrapers. Maintaining scraping code against Google/Bing HTML changes
  is significant ongoing work. High ban rate.
- **Why not**: SearXNG already solves this problem as a maintained project.

### Alternative 4: SearXNG JSON API
- **Pros**: Cleaner parsing; no HTML dependency.
- **Cons**: Many SearXNG instances disable `format=json` by default. The monorepo's own SearXNG instance in the
  compose stack may be configured with or without JSON enabled. Using HTML ensures the client always works.
- **Why not**: HTML parsing is less clean but more universally available. The `article.result` selector is
  stable across SearXNG versions.

## Consequences

### Positive
- No API keys required; no per-query billing.
- Results aggregate multiple upstream search engines; failure of one upstream does not eliminate results.
- The SearXNG instance is under operator control; search data stays within the deployment.

### Negative
- HTML parsing is brittle against SearXNG theme changes. If SearXNG changes the `article.result` DOM structure,
  `_parse_html_results` silently returns zero results. There is no unit test that catches a theme-driven DOM
  change without a live SearXNG fixture.
- The `format=html` approach means the raw SearXNG response is not machine-structured. Title and content snippet
  quality depends on how well SearXNG's template renders the upstream results.
- `SearxngClient` is instantiated at module load time in `rest_endpoints.py:15` and `mcp_server.py:10`. A bad
  `SEARXNG_BASE_URL` does not fail at startup; it fails silently on the first query.

### Risks
- **SearXNG upstream outage**: If the SearXNG instance is down, `search` raises `httpx.HTTPStatusError`. The
  global `httpx_exception_handler` returns 503. No retry or fallback search backend exists.
- **Rate limiting by SearXNG**: SearXNG can rate-limit clients if query frequency exceeds its internal caps.
  No retry-with-backoff is implemented in `SearxngClient`.

## Related

- `src/search/search_client.py` — `SearxngClient.search`, `_parse_html_results`.
- `src/api/rest/rest_endpoints.py:26-38` — `GET /api/v1/web/search` calls `search_client.search`.
- `src/api/mcp/mcp_server.py:16-28` — `web_search` MCP tool calls `search_client.search`.
- `src/config/config.py` — `SEARXNG_BASE_URL`, `SEARCH_TIMEOUT`, `SEARXNG_USER_AGENT`.
- `ascend-scrapper.docker-compose.yaml` — SearXNG service definition at port 9020.
