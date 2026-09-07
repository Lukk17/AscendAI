# 7. Deployment View

---

### docker-compose placement

ascend-web-hunter runs as the `ascend-web-hunter` service in `ascend-scrapper.docker-compose.yaml` (project
`ascend-scrapper`). This file is included by the top-level `docker-compose.yaml` via `include:`, so
`docker compose up` from the monorepo root brings up the scraper stack alongside the main application stack.
It can also be started independently as its own Docker Desktop group.

```mermaid
graph TB
    subgraph "ascend-scrapper compose network"
        WebHunter["ascend-web-hunter<br/>:7021"]
        SearXNG["searxng<br/>:9020"]
        FlareSolverr["flaresolverr<br/>:8191"]
        Ngrok["ngrok-ascend-web-hunter<br/>(tunnel)"]
    end

    subgraph "ascend-ai compose network"
        Agent["ascend-ai-agent<br/>:9917"]
        Redis["Redis<br/>:6379"]
    end

    Agent -->|"MCP POST /mcp"| WebHunter
    Agent -->|"REST GET/POST"| WebHunter
    WebHunter -->|"search HTML"| SearXNG
    WebHunter -->|"Cloudflare bypass"| FlareSolverr
    WebHunter -->|"session cookies"| Redis
    Ngrok -->|"public tunnel"| WebHunter
```

Redis is an external prerequisite shared across both compose projects; the scraper stack reaches it via the
host bridge network or a shared Docker network depending on deployment configuration.

---

### Healthcheck wiring

The `GET /health` endpoint (`src/main.py:56-58`) returns `{"status": "ok"}` as long as the process is alive.
There is no separate readiness probe. The blocklist loads from the vendored `src/assets/fanboy-annoyance.txt`
eagerly at module import time, before the process can even reach the point of serving `/health`; a missing or
corrupt vendored file is a packaging defect that prevents the process from starting at all, not something the
health check needs to model. See [ADR-008](../decisions/ADR-008-blocklist-vendored-not-fetched.md).

---

### Environment variables

| Variable | Default | Description |
| :--- | :--- | :--- |
| `API_HOST` | `0.0.0.0` | Bind address for Uvicorn. |
| `API_PORT` | `7021` | Listen port. |
| `LOG_LEVEL` | `INFO` | Logging level. |
| `SEARXNG_BASE_URL` | `http://localhost:9020` | SearXNG endpoint. Docker Compose overrides to `http://searxng:8080`. |
| `SEARXNG_USER_AGENT` | `ascend-web-hunter/1.0` | User-Agent sent to SearXNG. |
| `FLARESOLVERR_URL` | `http://localhost:8191/v1` | FlareSolverr endpoint. |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection for session cookie store. |
| `BLOCKLIST_URL` | `https://secure.fanboy.co.nz/fanboy-annoyance.txt` | Source `POST /api/v1/blocklist/refresh` downloads from. Never fetched automatically. |
| `BLOCKLIST_PATH` | `src/assets/fanboy-annoyance.txt` | Path to the vendored blocklist file; also where a refresh writes. |
| `BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS` | `60.0` | Minimum seconds between accepted refresh attempts. |
| `VALIDATION_MIN_WORDS` | `10` | Minimum word count for extracted content to pass validation. |
| `DEFAULT_TIMEOUT` | `30.0` | Default HTTP timeout in seconds. |
| `SEARCH_TIMEOUT` | `10.0` | Timeout for SearXNG search requests. |
| `EXTRACT_TIMEOUT` | `30.0` | Timeout per HTTP extraction strategy. |
| `NOVNC_TIMEOUT_SECONDS` | `600` | Background monitor runtime cap for NoVNC sessions (10 minutes). |
| `PUBLIC_VNC_URL` | `http://localhost:7900` | Public VNC URL returned in 428 responses. Set to Ngrok API URL to enable dynamic resolution. |
| `SELENIUM_BROWSER_VNC_URL` | `http://localhost:7900` | Fallback VNC URL when Ngrok API call fails. |
| `MIN_FLESCH_SCORE` | `20.0` | Minimum Flesch reading ease score for content validation. |
| `MIN_TTR` | `0.1` | Minimum type-token ratio for repetition check. |

---

### Docker image

The service uses `mcr.microsoft.com/playwright/python:v1.58.0-noble` as its base image. This provides Chromium,
Xvfb, and the full Playwright browser dependencies required by `PlaywrightStrategy`, `CrawleeStrategy`, and
`NoVNCStrategy`. The image is significantly larger than a minimal Python image; browser dependencies are the
dominant size contributor.

`src/assets/fanboy-annoyance.txt` ships inside the image via the same `COPY src/ src/` that already carries
`src/assets/user_agents.json`; no separate `COPY` step exists for it. A blocklist refreshed via
`POST /api/v1/blocklist/refresh` writes back to that same in-container path, so it only persists across a
container restart if that path is bind-mounted or volume-mounted to somewhere durable — this deployment does not
mount one, so a restart reverts to whatever was last baked into the image.
