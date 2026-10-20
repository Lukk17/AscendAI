# AGENTS.md - ascend-web-hunter

## Project Overview

ascend-web-hunter is an MCP server and REST API for web search and content extraction. It integrates SearXNG for meta-search, implements multi-tiered content extraction with Cloudflare WAF bypass, and supports human intervention for CAPTCHAs via NoVNC/Ngrok.

## Tech Stack

- **Language**: Python 3.12
- **Framework**: FastAPI + Uvicorn, FastMCP
- **Version**: 0.0.13
- **Docker Base**: `mcr.microsoft.com/playwright/python:v1.60.0-noble`

## Build & Run Commands

Every command below runs through this module's own virtual environment at `.venv/` (created via
`python -m venv .venv`, see docs/running.md) - never the system Python or pip. Windows interpreter:
`.venv/Scripts/python.exe`; Linux/macOS: `.venv/bin/python`.

Install dependencies, Windows:

```powershell
# Install the shared library first, then the service
.venv/Scripts/python.exe -m pip install -e ../../libs/ascend-python-common
.venv/Scripts/python.exe -m pip install -e ".[dev]"
```

Linux/macOS:

```bash
# Install the shared library first, then the service
.venv/bin/python -m pip install -e ../../libs/ascend-python-common
.venv/bin/python -m pip install -e ".[dev]"
```

Install the Playwright Chromium build, Windows:

```powershell
.venv/Scripts/python.exe -m playwright install chromium
```

Linux/macOS (`--with-deps` also installs the system libraries Chromium needs, and may ask for sudo):

```bash
.venv/bin/python -m playwright install --with-deps chromium
```

Run the server (port 7021), Windows:

```powershell
.venv/Scripts/python.exe -m uvicorn src.main:app --host 0.0.0.0 --port 7021 --reload
```

Linux/macOS:

```bash
.venv/bin/python -m uvicorn src.main:app --host 0.0.0.0 --port 7021 --reload
```

Run tests with the configured 100% branch-coverage gate, Windows:

```powershell
.venv/Scripts/python.exe -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100
```

Linux/macOS:

```bash
.venv/bin/python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100
```

Docker, identical on every platform:

```bash
docker build -t ascend-web-hunter:latest .
```

## Architecture

**Dual API surface**:
- REST API: Endpoints for web search, page reading, and content extraction
- MCP Server: FastMCP tools exposed via Streamable HTTP at `/mcp`.

**Platform behavior** (via `ascend-python-common`, wired in `src/main.py` with `create_service_app`):
- REST errors are RFC 7807 problem bodies (`application/problem+json`) with `code` and `traceId`. Request
  validation failures answer `400` with code `validation` and an `errors` list sorted by `field`. A URL the
  fetch guard refuses answers `400` with code `unsafe_uri`. The NoVNC answers are problem bodies too: `428`
  with code `human_intervention_required` and extension members `intervention_type` and `vnc_url`, and `409`
  with code `novnc_busy`, extension members `holder_url` and `holder_profile`, and a `Retry-After` header.
  Unexpected failures answer `500` with code `internal` and a fixed detail. MCP refusals are tool errors whose
  text starts with `<code>: ` (`validation: `, `unsafe_uri: `, `internal: `). The MCP status objects
  (`human_intervention_required`, `novnc_busy`, `session_expired`) are successful tool results, not errors, and
  keep their `status`-keyed shape.
- `/health` answers `200 {"status": "ok", "service": "ascend-web-hunter", "version": ...}` without touching a
  dependency. `/ready` aggregates the `redis`, `searxng`, and `searxng_breaker` probes and answers
  `200 {"status": "ready", ...}` or `503 {"status": "not-ready", ...}`.
- Logging comes from the library (`LOG_LEVEL` honoured, `LOG_FORMAT` selects `json` or `color`, lines start with
  `[ascend-web-hunter]`). There is no service `logging_config.py` and no `log_config` argument on `uvicorn.run`.

**Multi-tiered extraction strategy** (escalation order):
1. `1-beautifulsoup` - fast, lightweight HTTP client
2. `2-trafilatura` - fast, lightweight HTTP client
3. `4-playwright_stealth` - headless browser automation
4. `4a-patchright` - patched Chromium build
5. `4b-camoufox` - Firefox-family fingerprint (only while `CAMOUFOX_ENABLED=true`, default `true`)
6. `5-crawlee_adaptive` - adaptive crawler
7. `6-novnc` - human intervention for complex CAPTCHAs (via Ngrok tunnel)

A domain that succeeded at a tier before restarts at the remembered tier for `TIER_MEMORY_TTL_SECONDS`
(default `86400`). Browser waits `NETWORKIDLE_POLL_MS` (default `1000`) and `SCROLL_PAUSE_MS` (default
`200`) come from the same settings every browser tier reads.

**Key Features**:
- SearXNG integration for privacy-respecting meta-search
- HTTP 428 asks for human intervention (NoVNC), HTTP 429 rate-limits flooded callers
- Session persistence in Redis
- Ad/annoyance blocklist filtering
- Content validation (minimum word count)
- Polling crawl jobs (`POST /api/v1/crawl/jobs`, status, list, cancel, plus the `crawl_submit`,
  `crawl_job_status`, `crawl_list_jobs` and `crawl_cancel_job` MCP tools) over a shared Redis frontier:
  several instances share one crawl through Lua-claimed URLs with per-domain politeness, results land in
  Floci under `tenant/<tenantId>/`, recrawls copy unchanged pages forward. Every seed, discovered link,
  redirect hop, robots.txt and sitemap fetch passes the same SSRF guard and connect-time pinning as a
  single read. Honest ceiling: the hundreds-of-thousands-of-pages class per job across several workers.
  See [ADR-019](docs/architecture/decisions/ADR-019-crawl-jobs.md).

## Key Dependencies

- SearXNG (port 9020 via docker-compose)
- Redis (port 6379) for session persistence. External prerequisite in the development stack; bundled and runs unconditionally in `deploy-standalone/` (no published ports either way)
- Ngrok for NoVNC tunnel (optional, for CAPTCHA intervention)
- Playwright for browser automation

## Environment Variables

- `SEARXNG_BASE_URL` - SearXNG endpoint (default: `http://searxng:8080`)
- `API_PORT` - Service port (default: 7021)
- `WEB_HUNTER_HOST_PORT` - Host port of the service (default: 7021)
- `LOG_LEVEL` - Logging level (default: `INFO`)
- `LOG_FORMAT` - Log format, `json` or `color` (default: `json`)
- `OTEL_EXPORTER_OTLP_ENDPOINT` - OTLP trace export endpoint, export whenever it is set, unset by default
- `OTEL_SDK_DISABLED` - OpenTelemetry's standard switch, `true` turns the SDK off
- `RATE_LIMIT_DEFAULT` - Flood-protection rate limit for REST routes and MCP tools (default: `1200/minute`)
- `READINESS_PROBE_TIMEOUT_SECONDS` - Seconds each readiness probe may take (default: `3`)
- `STARTUP_PROBE_TIMEOUT_SECONDS` - Seconds each startup banner check may take (default: `2`)
- `SECURITY_HSTS_MAX_AGE_SECONDS` - Max age of the strict-transport-security header (default: `63072000`)
- `FETCH_MAX_REDIRECT_HOPS` - Redirect hops the URI fetch guard follows (default: `10`)
- `ALLOWED_PRIVATE_HOSTS` - Hosts the URI fetch guard may reach even at a private address (default: empty)
- `MCP_ALLOWED_HOST_HEADERS` - Host names the `/mcp` endpoint accepts in the `Host` header, inbound check on the MCP endpoint only (default: `ascend-web-hunter,localhost,127.0.0.1`). `ALLOWED_PRIVATE_HOSTS` is the outbound direction and one does not replace the other.

`API_PORT`, `LOG_LEVEL`, `LOG_FORMAT`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SDK_DISABLED`, and `RATE_LIMIT_DEFAULT` are defined in the
`ascend-python-common` `ServiceSettings` base class and subclassed in `src/config/config.py`.
- `CAMOUFOX_ENABLED` - Route reads through the 4b-camoufox tier (default: `true`)
- `TIER_MEMORY_TTL_SECONDS` - TTL in seconds for the per-domain tier memory (default: `86400`)
- `EXTRACTION_SCHEMA_MAX_BYTES` - Maximum size in bytes of the caller-supplied extraction schema (default: `16384`)
- `EXTRACTION_LLM_BASE_URL` - Base URL of the OpenAI-compatible endpoint schema extraction calls; empty turns the schema format off (default: empty)
- `EXTRACTION_LLM_MODEL` - Model name sent to the extraction endpoint (default: empty)
- `EXTRACTION_LLM_API_KEY` - API key for the extraction endpoint, read from the repository `.env` file only (default: empty)
- `EXTRACTION_LLM_MAX_INPUT_CHARS` - Page text characters sent to the extraction endpoint before the cap cuts them (default: `60000`)
- `EXTRACTION_LLM_TIMEOUT_SECONDS` - Timeout in seconds for one extraction model call (default: `60`)
- `RECIPE_TTL_SECONDS` - TTL in seconds for a stored extraction recipe (default: `604800`)
- `RECIPE_SELECTOR_MAX_CHARS` - Maximum characters of one stored CSS selector (default: `512`)
- `DOCUMENT_MAX_BYTES` - Maximum bytes fetched for one routed PDF, image or audio file (default: `52428800`)
- `DOCLING_SERVE_URL` - Base URL of the docling-serve document conversion service; empty turns the PDF route off (default: `http://docling-serve:5001`)
- `ASCEND_OCR_URL` - Base URL of the ascend-ocr service; empty turns the image route off (default: `http://ascend-ocr:7022`)
- `OCR_ROUTE_TIMEOUT_SECONDS` - Timeout in seconds polling one ascend-ocr job (default: `300`)
- `AUDIO_SCRIBE_URL` - Base URL of the ascend-audio-scribe service; empty turns the audio route off (default: `http://ascend-audio-scribe:7017`)
- `READ_CACHE_PURGE_RECONNECT_SECONDS` - Wait in seconds between two connection attempts of the read cache purge subscriber (default: `5`)
- `NETWORKIDLE_POLL_MS` - Page-quiet poll interval in milliseconds for browser tiers (default: `1000`)
- `SCROLL_PAUSE_MS` - Pause in milliseconds between two scroll steps (default: `200`)
- `REDIS_URL` - Shared storage for the rate limit windows, one budget per caller under the key prefix `ascend-web-hunter`, and for clearance-cookie persistence (default: `redis://127.0.0.1:6379/0`)
- `BLOCKLIST_URL` - Ad blocklist source. Only reached by `POST /api/v1/blocklist/refresh`; never fetched at startup
- `BLOCKLIST_PATH` - Path to the vendored blocklist file (default `src/assets/fanboy-annoyance.txt`), loaded at
  startup and overwritten in place by a refresh
- `VALIDATION_MIN_WORDS` - Minimum words for valid content
- `CHALLENGE_DETECTION_MAX_BYTES` - Prefix length scanned by the vendor, structure and phrase families (default: `50000`)
- `CHALLENGE_WALL_MAX_BYTES` - Page size under which a 403, 429 or 503 body counts as small, and under which the word floor is computed (default: `50000`)
- `CHALLENGE_SCORE_THRESHOLD` - Score at or above which a page is a wall (default: `100`)
- `CHALLENGE_RICH_CONTENT_WORDS` - Extracted words at or above which the rich-content guard fires (default: `150`)
- `CHALLENGE_FORM_DOMINANCE_RATIO` - Share of visible text inside forms at or above which form dominance fires (default: `0.6`)
- `CHALLENGE_MIN_WORDS_PER_KB` - Extracted words per kilobyte of HTML under which thin text fires (default: `2.0`)
- `CHALLENGE_THIN_LINK_COUNT` - Fewer anchors with href than this fires few links (default: `5`)
- `CHALLENGE_RICH_LINK_COUNT` - At least this many anchors with href fires the many-links guard (default: `20`)
- `CHALLENGE_SHAPE_MAX_BYTES` - Bounds the extraction the shape family uses (default: `500000`)
- `CHALLENGE_WEIGHT_DEFINITIVE_HEADER` - Weight of the definitive_header signal (default: `200`)
- `CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE` - Weight of the interstitial_structure signal (default: `80`)
- `CHALLENGE_WEIGHT_VENDOR_SCRIPT` - Weight of the vendor_script signal (default: `60`)
- `CHALLENGE_WEIGHT_VENDOR_PRESENCE` - Weight of the vendor_presence signal (default: `30`)
- `CHALLENGE_WEIGHT_STATUS_EMPTY_BODY` - Weight of the status_empty_body signal (default: `200`)
- `CHALLENGE_WEIGHT_STATUS_SMALL_BODY` - Weight of the status_small_body signal (default: `50`)
- `CHALLENGE_WEIGHT_STATUS_LARGE_BODY` - Weight of the status_large_body signal (default: `20`)
- `CHALLENGE_WEIGHT_CAPTCHA_INPUT` - Weight of the captcha_input signal (default: `50`)
- `CHALLENGE_WEIGHT_CAPTCHA_ELEMENT` - Weight of the captcha_element signal (default: `40`)
- `CHALLENGE_WEIGHT_FORM_DOMINANCE` - Weight of the form_dominance signal (default: `40`)
- `CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY` - Weight of the script_only_body signal (default: `40`)
- `CHALLENGE_WEIGHT_THIN_TEXT` - Weight of the thin_text signal (default: `20`)
- `CHALLENGE_WEIGHT_FEW_LINKS` - Weight of the few_links signal (default: `20`)
- `CHALLENGE_WEIGHT_NO_ARTICLE` - Weight of the no_article signal (default: `20`)
- `CHALLENGE_WEIGHT_RICH_CONTENT` - Weight of the rich_content guard signal (default: `-60`)
- `CHALLENGE_WEIGHT_MANY_LINKS` - Weight of the many_links guard signal (default: `-20`)
- `CHALLENGE_WEIGHT_PHRASE_TITLE` - Weight of the phrase_title signal (default: `60`)
- `CHALLENGE_WEIGHT_PHRASE_BODY` - Weight of the phrase_body signal (default: `30`)
- `NOVNC_MAX_CONCURRENT_FLOWS` - Maximum concurrent intervention windows per container, a memory constraint as much as a display one (default: `4`)
- `NOVNC_DISPLAY_SIZE` - Size of the shared Xvfb display as `<width>x<height>`, read by Xvfb and the service; the Dockerfile also sets it for a container started without compose (default: `1920x1080`)
- `NOVNC_WINDOW_WIDTH_PX` - Width in pixels of each intervention window (default: `1280`)
- `NOVNC_WINDOW_HEIGHT_PX` - Height in pixels of each intervention window (default: `800`)
- `NOVNC_WINDOW_CASCADE_OFFSET_PX` - Cascade step in pixels between intervention windows (default: `48`)
- `NOVNC_FLOW_LEASE_GRACE_SECONDS` - Teardown grace added on top of the flow timeout before a held flow is reclaimed (default: `30.0`)
- `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS` - Interval in seconds between lease-sweeper runs (default: `30.0`)
- `NOVNC_FLOW_CANCEL_GRACE_SECONDS` - Bounds reclamation and shutdown (default: `10.0`)
- `NOVNC_BUSY_RETRY_AFTER_SECONDS` - Short poll interval answered in the 409 Retry-After header (default: `30`)
- `NOVNC_PUBLIC_URL` - One base address shared by every container, the address of the web-hunter edge proxy, with no path; unset keeps `PUBLIC_VNC_URL` and the one Ngrok tunnel (default: unset)
- `VNC_PASSWORD` - Password for the NoVNC desktop. Consumed by `docker-entrypoint.sh`, not by `config.py`. Unset means
  x11vnc runs with `-nopw` and the container logs a warning at boot. Required in the standalone deployment. The VNC
  protocol truncates it to 8 characters.
- `CRAWL_MAX_SEEDS` - Most seeds in one crawl request (default: `20`)
- `CRAWL_MAX_PATTERNS` - Most include patterns and most exclude patterns in one crawl request (default: `50`)
- `CRAWL_MAX_DEPTH` - Largest `max_depth` a crawl request may ask for (default: `5`)
- `CRAWL_DEFAULT_DEPTH` - `max_depth` when the request has none, refused at startup above `CRAWL_MAX_DEPTH` (default: `2`)
- `CRAWL_MAX_PAGES` - Largest `page_budget` a crawl request may ask for (default: `10000`)
- `CRAWL_DEFAULT_PAGE_BUDGET` - `page_budget` when the request has none, refused at startup above `CRAWL_MAX_PAGES` (default: `100`)
- `CRAWL_ROBOTS_OPT_OUT_DOMAINS` - Seed domains for which `respect_robots` false is accepted, a site the operator owns (default: empty)
- `CRAWL_RESULT_S3_BUCKET` - Bucket of the crawl results (default: `web-hunter-crawls`)
- `CRAWL_RESULT_S3_PREFIX` - Key prefix of the crawl results after the tenant prefix (default: `crawl-results/`)
- `CRAWL_JOB_RETENTION_SECONDS` - Lifetime of job records, results, frontier keys and recrawl state (default: `604800`)
- `CRAWL_DOMAIN_CONCURRENCY` - Pages of one domain read at once, all instances together (default: `2`)
- `CRAWL_DEFAULT_DELAY_SECONDS` - Least time between two fetches of one domain (default: `1`)
- `CRAWL_PROXY_URL` - Customer proxy for crawl fetches only, empty turns it off (default: empty)
- `CRAWL_CLAIM_LEASE_SECONDS` - Lifetime of a page claim (default: `120`)
- `CRAWL_CLAIM_MAX_EXPIRIES` - Claim expiries after which a URL counts as failed (default: `2`)
- `CRAWL_WORKER_CONCURRENCY` - Crawl worker tasks each instance starts (default: `4`)
- `CRAWL_WORKER_IDLE_SECONDS` - Wait of a worker that found nothing to claim (default: `1`)
- `CRAWL_POLL_AFTER_SECONDS` - The `poll_after_seconds` hint of a crawl submission (default: `5`)
- `OBJECT_STORE_S3_ENDPOINT` - Address of the S3-compatible store (default: `http://localhost:9070`)
- `OBJECT_STORE_S3_ACCESS_KEY` - Access key of the store (default: empty)
- `OBJECT_STORE_S3_SECRET_KEY` - Secret key of the store (default: empty)

Two more are consumed by sibling containers rather than by this service, and both are mandatory for the scrapper stack:
`SEARXNG_SECRET` (SearXNG's session key, which is why `infra/searxng/settings.yml` carries no `secret_key`) and
`NGROK_AUTHTOKEN`.

The full reference, including every timeout and threshold, is [docs/configuration.md](docs/configuration.md).

## Deployment

Two compose files run this service and they are deliberately different:

- `../../compose.ascend-web-hunter.yaml` at the repo root. Development. Builds from source, publishes SearXNG
  on loopback so the service can run natively against it, exports OTLP telemetry to the platform
  collector.
- [`deploy-standalone/compose.yaml`](deploy-standalone/README.md). Standalone single-host deployment. Pulls published images pinned to
  a version tag, publishes nothing but port 7021, no telemetry, requires `VNC_PASSWORD`.

The full list of intended differences is in [deploy-standalone/README.md](deploy-standalone/README.md). Anything not on that list should be
identical in both files.

The development file and the main stack (`../../compose.yaml`, project `ascend-ai`, which pulls the development file in through
`include:`) use the same three fixed container names, `searxng`, `ascend-web-hunter` and `ngrok-ascend-web-hunter`,
so only one of the two projects runs at a time. Switching means `docker compose down` on the project you leave, which removes its
containers. `stop` is not enough, because a stopped container still holds its name and the other project then refuses to create
its containers with a name conflict. Running the development file alone (project `ascend-scrapper`) on a host without its own
Redis also needs `COMPOSE_PROFILES=redis` and `REDIS_URL=redis://redis:6379/0` in the root `.env`, which the root `.env.example`
documents as commented-out lines. To leave the main stack and start this stack alone, from the repo root:

```bash
docker compose down
```

```bash
docker compose -f compose.ascend-web-hunter.yaml up -d
```

To go back to the main stack:

```bash
docker compose -f compose.ascend-web-hunter.yaml down
```

```bash
docker compose up -d
```

**Sync rule.** [`deploy-standalone/searxng/settings.yml`](deploy-standalone/searxng/settings.yml) is a byte-identical copy of
`../../infra/searxng/settings.yml`, so `diff` between them is the whole check. When you change one, change the other in the same
commit. The same applies to environment variables: a new variable in the scrapper stack goes into the root
`.env.example`, into [`deploy-standalone/.env.example`](deploy-standalone/.env.example), and into the configuration table in
[deploy-standalone/README.md](deploy-standalone/README.md).

## Code Conventions

- Absolute imports from `src`
- Type hints (PEP 484) on all function signatures
- Pydantic models for data validation
- Async/await for I/O-bound operations
- FastMCP for MCP tool definitions
- When instrumenting new code (metrics, logs, or spans), follow [../../docs/OBSERVABILITY.md](../../docs/OBSERVABILITY.md)

## Relevant Skills

- `/python-patterns`
- `/api-design`, `/docker-patterns`
- `/security-review` (web scraping, input validation)
