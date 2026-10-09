# AGENTS.md - ascend-web-hunter

## Project Overview

ascend-web-hunter is an MCP server and REST API for web search and content extraction. It integrates SearXNG for meta-search, implements multi-tiered content extraction with Cloudflare WAF bypass, and supports human intervention for CAPTCHAs via NoVNC/Ngrok.

## Tech Stack

- **Language**: Python 3.12
- **Framework**: FastAPI + Uvicorn, FastMCP
- **Version**: 0.0.7
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
  dependency. `/ready` aggregates the `redis`, `searxng`, `flaresolverr`, `searxng_breaker`, and
  `flaresolverr_breaker` probes and answers `200 {"status": "ready", ...}` or `503 {"status": "not-ready", ...}`.
- Logging comes from the library (`LOG_LEVEL` honoured, `LOG_FORMAT` selects `json` or `color`, lines start with
  `[ascend-web-hunter]`). There is no service `logging_config.py` and no `log_config` argument on `uvicorn.run`.

**Multi-tiered extraction strategy** (escalation order):
1. `curl_cffi` - fast, lightweight HTTP client
2. FlareSolverr - Cloudflare bypass proxy
3. Playwright - headless browser automation
4. NoVNC - human intervention for complex CAPTCHAs (via Ngrok tunnel)

**Key Features**:
- SearXNG integration for privacy-respecting meta-search
- HTTP 428 asks for human intervention (NoVNC), HTTP 429 rate-limits flooded callers
- Session persistence in Redis
- Ad/annoyance blocklist filtering
- Content validation (minimum word count)

## Key Dependencies

- SearXNG (port 9020 via docker-compose)
- FlareSolverr (port 8191) for Cloudflare bypass
- Redis (port 6379) for session persistence. External prerequisite in the development stack; bundled and runs unconditionally in `deploy-standalone/` (no published ports either way)
- Ngrok for NoVNC tunnel (optional, for CAPTCHA intervention)
- Playwright for browser automation

## Environment Variables

- `SEARXNG_BASE_URL` - SearXNG endpoint (default: `http://searxng:8080`)
- `API_PORT` - Service port (default: 7021)
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

`API_PORT`, `LOG_LEVEL`, `LOG_FORMAT`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_SDK_DISABLED`, and `RATE_LIMIT_DEFAULT` are defined in the
`ascend-python-common` `ServiceSettings` base class and subclassed in `src/config/config.py`.
- `FLARESOLVERR_URL` - FlareSolverr endpoint
- `REDIS_URL` - Shared storage for the rate limit windows, one budget per caller under the key prefix `ascend-web-hunter`, and for clearance-cookie persistence (default: `redis://127.0.0.1:6379/0`)
- `BLOCKLIST_URL` - Ad blocklist source. Only reached by `POST /api/v1/blocklist/refresh`; never fetched at startup
- `BLOCKLIST_PATH` - Path to the vendored blocklist file (default `src/assets/fanboy-annoyance.txt`), loaded at
  startup and overwritten in place by a refresh
- `VALIDATION_MIN_WORDS` - Minimum words for valid content
- `VNC_PASSWORD` - Password for the NoVNC desktop. Consumed by `docker-entrypoint.sh`, not by `config.py`. Unset means
  x11vnc runs with `-nopw` and the container logs a warning at boot. Required in the standalone deployment. The VNC
  protocol truncates it to 8 characters.

Two more are consumed by sibling containers rather than by this service, and both are mandatory for the scrapper stack:
`SEARXNG_SECRET` (SearXNG's session key, which is why `infra/searxng/settings.yml` carries no `secret_key`) and
`NGROK_AUTHTOKEN`.

The full reference, including every timeout and threshold, is [docs/configuration.md](docs/configuration.md).

## Deployment

Two compose files run this service and they are deliberately different:

- `../../compose.ascend-web-hunter.yaml` at the repo root. Development. Builds from source, publishes SearXNG and
  FlareSolverr on loopback so the service can run natively against them, exports OTLP telemetry to the platform
  collector.
- [`deploy-standalone/compose.yaml`](deploy-standalone/README.md). Standalone single-host deployment. Pulls published images pinned to
  a version tag, publishes nothing but port 7021, no telemetry, requires `VNC_PASSWORD`.

The full list of intended differences is in [deploy-standalone/README.md](deploy-standalone/README.md). Anything not on that list should be
identical in both files.

The development file and the main stack (`../../compose.yaml`, project `ascend-ai`, which pulls the development file in through
`include:`) use the same four fixed container names, `searxng`, `flaresolverr`, `ascend-web-hunter` and `ngrok-ascend-web-hunter`,
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
