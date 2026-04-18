# AGENTS.md — AscendWebSearch

## Project Overview

AscendWebSearch is an MCP server and REST API for web search and content extraction. It integrates SearXNG for meta-search, implements multi-tiered content extraction with Cloudflare WAF bypass, and supports human intervention for CAPTCHAs via NoVNC/Ngrok.

## Tech Stack

- **Language**: Python 3.12
- **Framework**: FastAPI + Uvicorn, FastMCP
- **Version**: 0.1.0
- **Docker Base**: `mcr.microsoft.com/playwright/python:v1.58.0-noble`

## Build & Run Commands

```bash
# Install dependencies
pip install -e .[dev]

# Run the server (port 7021)
uvicorn src.main:app --host 0.0.0.0 --port 7021 --reload

# Run tests
pytest

# Docker
docker build -t ascend-web-search:latest .
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
- Redis (port 6379) for session persistence
- Ngrok for NoVNC tunnel (optional, for CAPTCHA intervention)
- Playwright for browser automation

## Environment Variables

- `SEARXNG_BASE_URL` — SearXNG endpoint (default: `http://searxng:8080`)
- `API_PORT` — Service port (default: 7021)
- `FLARESOLVERR_URL` — FlareSolverr endpoint
- `REDIS_URL` — Redis connection string
- `BLOCKLIST_URL` — Ad blocklist URL
- `VALIDATION_MIN_WORDS` — Minimum words for valid content

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
