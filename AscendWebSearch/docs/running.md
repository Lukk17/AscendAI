# Running AscendWebSearch

This doc covers local Python execution, the Docker path, and MCP client configuration. For curl examples
against a running instance see [api-examples.md](api-examples.md).

---

### Prerequisites

- Python 3.12 (or use Docker)
- A reachable SearXNG instance (`9020` host-exposed or `8080` container-internal)
- Playwright browsers (only for local Python; the Docker image ships them)
- Ngrok auth token for remote CAPTCHA solving. Get a free token from
  [dashboard.ngrok.com](https://dashboard.ngrok.com) and set `NGROK_AUTHTOKEN`

---

### Local Python

Create a venv.

Bash:

```bash
python3 -m venv .venv
```

PowerShell:

```powershell
python -m venv .venv
```

Activate it.

Bash:

```bash
source .venv/bin/activate
```

PowerShell:

```powershell
.\.venv\Scripts\activate
```

Install dependencies (identical in both shells):

```bash
pip install -e .[dev]
```

Install Playwright browsers (identical in both shells):

```bash
playwright install --with-deps chromium
```

Export the SearXNG base URL.

Bash:

```bash
export SEARXNG_BASE_URL="http://localhost:9020"
```

PowerShell:

```powershell
$env:SEARXNG_BASE_URL="http://localhost:9020"
```

Run the service (identical in both shells):

```bash
python src/main.py
```

---

### Docker

Every command in this section is identical in bash and PowerShell.

Build the image:

```bash
docker build -t ascend-web-search:latest .
```

Run the container standalone. Inside the Compose network use `http://searxng:8080`; for a single container
against a host-network SearXNG use `host.docker.internal`:

```bash
docker run -d --name ascend-web-search -p 7021:7021 -e SEARXNG_BASE_URL="http://host.docker.internal:9020" ascend-web-search:latest
```

Tag for the registry (optional):

```bash
docker tag ascend-web-search:latest lukk17/ascend-web-search:v0.1.0
```

Push it (optional):

```bash
docker push lukk17/ascend-web-search:v0.1.0
```

The Compose-orchestrated path (recommended) brings up SearXNG, FlareSolverr, Redis, and the Ngrok bridge in
one shot:

```bash
docker compose -f ../ascend-scrapper.docker-compose.yaml up -d --build
```

---

### MCP server mode

The service exposes an MCP server on `/mcp` (SSE transport).

Add to your agent's MCP config:

```json
{
  "mcpServers": {
    "ascend-web-search": {
      "type": "sse",
      "url": "http://localhost:7021/mcp"
    }
  }
}
```

Tools advertised:

- `web_search(query, limit)`: search the web through SearXNG
- `web_read(url, include_links?, link_filter?, heavy_mode?)`: extract content from a URL

When the response carries `status: "human_intervention_required"`, the agent should display the `vnc_url` to
the user and re-call `web_read` once they confirm the challenge is solved. The cached Redis session will let
the second call succeed without escalating again.

---

### Startup readiness banner

On startup the service logs one multi-line INFO record. It contains an ASCII banner, the bound access URLs,
parallel 2-second probes for SearXNG / FlareSolverr / Redis, and the full list of REST and observability
endpoints. Implementation in [src/config/startup_banner.py](../src/config/startup_banner.py).

---

### Observability endpoints

| Endpoint | Purpose |
| :--- | :--- |
| `GET /health` | Liveness (always 200 when the process is alive) |
| `GET /ready` | Readiness: probes Redis, SearXNG, FlareSolverr; 200 only when all upstreams respond |
| `GET /metrics` | Prometheus counters and histograms (strategy outcomes, durations, intervention rate) |
| `GET /docs` | Swagger UI |
| `GET /redoc` | Redoc |
| `GET /openapi.json` | OpenAPI 3 schema |

Every response includes the request's `X-Request-ID` header (echoed if the caller sent one, generated as
UUIDv4 otherwise). Inbound IDs are validated against `^[A-Za-z0-9._-]{1,128}$`; anything else gets replaced
with a fresh UUID to block log injection and response-splitting attempts.
