# AGENTS.md — ascend-web-hunter

## Project Overview

ascend-web-hunter is an MCP server and REST API for web search and content extraction. It integrates SearXNG for meta-search, implements multi-tiered content extraction with Cloudflare WAF bypass, and supports human intervention for CAPTCHAs via NoVNC/Ngrok.

## Tech Stack

- **Language**: Python 3.12
- **Framework**: FastAPI + Uvicorn, FastMCP
- **Version**: 0.0.5
- **Docker Base**: `mcr.microsoft.com/playwright/python:v1.60.0-noble`

## Build & Run Commands

Every command below runs through this module's own virtual environment at `.venv/` (created via
`python -m venv .venv`, see docs/running.md) — never the system Python or pip. Windows interpreter:
`.venv/Scripts/python.exe`; Linux/macOS: `.venv/bin/python`.

```bash
# Install dependencies
.venv/Scripts/pip.exe install -e .[dev]

# Run the server (port 7021)
.venv/Scripts/uvicorn.exe src.main:app --host 0.0.0.0 --port 7021 --reload

# Run tests with the configured 100% branch-coverage gate
.venv/Scripts/pytest.exe --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100

# Docker
docker build -t ascend-web-hunter:latest .
```

## Architecture

**Dual API surface**:
- REST API: Endpoints for web search, page reading, and content extraction
- MCP Server: FastMCP tools exposed via Streamable HTTP

**Multi-tiered extraction strategy** (escalation order):
1. `curl_cffi` — fast, lightweight HTTP client
2. FlareSolverr — Cloudflare bypass proxy
3. Playwright — headless browser automation
4. NoVNC — human intervention for complex CAPTCHAs (via Ngrok tunnel)

**Key Features**:
- SearXNG integration for privacy-respecting meta-search
- Global HTTP 428 handling for rate limiting
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

- `SEARXNG_BASE_URL` — SearXNG endpoint (default: `http://searxng:8080`)
- `API_PORT` — Service port (default: 7021)
- `FLARESOLVERR_URL` — FlareSolverr endpoint
- `REDIS_URL` — Redis connection string
- `BLOCKLIST_URL` — Ad blocklist source. Only reached by `POST /api/v1/blocklist/refresh`; never fetched at startup
- `BLOCKLIST_PATH` — Path to the vendored blocklist file (default `src/assets/fanboy-annoyance.txt`), loaded at
  startup and overwritten in place by a refresh
- `VALIDATION_MIN_WORDS` — Minimum words for valid content
- `VNC_PASSWORD` — Password for the NoVNC desktop. Consumed by `docker-entrypoint.sh`, not by `config.py`. Unset means
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

## Relevant Skills

- `/python-patterns`, `/python-testing`
- `/api-design`, `/docker-patterns`
- `/security-review` (web scraping, input validation)
