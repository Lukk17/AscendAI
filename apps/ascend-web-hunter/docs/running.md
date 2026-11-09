# Running ascend-web-hunter

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
pip install -e ".[dev]"
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

Run the unit tests with the 100% branch-coverage gate (identical in both shells, the default run leaves out
`tests/integration`):

```bash
python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100
```

Run the integration tests. They drive the real Playwright, Patchright and Camoufox browsers, and the read cache
purge tests in `tests/integration/test_cache_purge_redis.py` need the local Redis at `REDIS_URL` (default
`redis://127.0.0.1:6379`), where they use database 15 only and close every connection they open. They are outside
the coverage gate, hence `--no-cov`.

Bash:

```bash
.venv/bin/python -m pytest tests/integration -q --no-cov
```

PowerShell:

```powershell
.venv/Scripts/python.exe -m pytest tests/integration -q --no-cov
```

---

### Docker

Every command in this section is identical in bash and PowerShell.

Build the image:

```bash
docker build -t ascend-web-hunter:latest .
```

Run the container standalone. SearXNG publishes its port on `127.0.0.1` only, so a
standalone container never reaches it through the host gateway. Join the network of the running stack
(`ascend-ai_default` for the main stack, `ascend-scrapper_default` for the scraping file alone) and call SearXNG
by name. The host's Redis is reached through `host.docker.internal` with the host gateway mapping
(`redis://redis:6379/0` instead when the bundled Redis of the scraping file runs). Remove the compose container
of the same name and port first, also before the IDE run configuration starts:

```bash
docker compose rm -sf ascend-web-hunter
```

```bash
docker run -d --name ascend-web-hunter --network ascend-ai_default --add-host=host.docker.internal:host-gateway -p 7021:7021 -e SEARXNG_BASE_URL="http://searxng:8080" -e REDIS_URL="redis://host.docker.internal:6379/0" ascend-web-hunter:latest
```

Publishing is done by the [Release workflow](../../../.github/workflows/README.md) rather than by hand. It builds
multi-arch and pushes `v<version>` and `latest` to both `lukk17/ascend-ai-ascend-web-hunter` and
`ghcr.io/lukk17/ascend-ai-ascend-web-hunter`. The version comes from `[project].version` in `pyproject.toml`.

The Compose-orchestrated path (recommended) brings up SearXNG and the Ngrok bridge in one shot. Run it
from the repository root so it goes into the `ascend-ai` project rather than creating a second project that fights over
the same container names:

```bash
docker compose up -d --build searxng ascend-web-hunter ngrok-ascend-web-hunter
```

Redis is not part of that stack. It has to be running separately on port 6379, which is what `REDIS_URL` points at.
`SEARXNG_SECRET` must be set in the root `.env` or compose refuses to start.

To deploy this stack to a host of its own, use the ready-made bundle in [../deploy-standalone/](../deploy-standalone/README.md) instead. It
pulls published images rather than building and needs no checkout of this repository.

---

### MCP server mode

The service exposes an MCP server on `/mcp` (SSE transport).

Add to your agent's MCP config:

```json
{
  "mcpServers": {
    "ascend-web-hunter": {
      "type": "sse",
      "url": "http://localhost:7021/mcp"
    }
  }
}
```

Tools advertised:

- `web_search(query, limit)`: search the web through SearXNG
- `web_read(url, include_links?, link_filter?, heavy_mode?, profile?, output_format?, tier?)`: extract content from a URL

When the response carries `status: "human_intervention_required"` (MCP tool result), the agent should display the `vnc_url` to
the user and re-call `web_read` once they confirm the challenge is solved. On REST the same outcome is HTTP 428
with a problem body carrying `code: "human_intervention_required"` plus `intervention_type` and `vnc_url`. The cached Redis session will let
the second call succeed without escalating again.

In the NoVNC window, Ctrl+V (Cmd+V on a Mac) types the text on your own clipboard as key presses into the field that has focus in the remote browser, and a paste on a phone does the same. Polish letters arrive unchanged. A newline in the text is a real Return key, so multi-line text pasted into a one-line field can submit the form, and a tab character is a real Tab key. Only text you choose to paste is sent. A paste above 10000 characters is refused with a message on the NoVNC page and no key is sent, because several windows share one display. A browser tab that was open on the NoVNC page before an update keeps the old script until you reload it. The Clipboard button in the noVNC side panel stays as the fallback if your browser does not pass the shortcut through, and it still uses the clipboard path, where Polish letters can arrive wrong.

When it carries `status: "session_expired"`, the stored login for that domain and profile has lapsed and no tier
ran. The agent should call `session_establish` for the same url and profile, have the user complete the login,
then re-call `web_read`.

`output_format` is `text` (the flat `content` field, the default) or `structured` (adds `title`, `author`, `date`
and `sitename`), and `structured` is refused together with `include_links`. `tier` names where the chain starts,
one of `1-beautifulsoup`, `2-trafilatura`, `4-playwright_stealth`, `4a-patchright`, `4b-camoufox`,
`5-crawlee_adaptive` or `6-novnc`, and escalation continues through the tiers after it.

---

### Startup readiness banner

On startup the service logs one multi-line INFO record. It contains an ASCII banner, the bound access URLs,
the External services rows, and the full list of REST and observability endpoints. Implementation in
[src/config/startup_banner.py](../src/config/startup_banner.py).

The External services rows probe SearXNG and Redis, and the `/health` of each document routing target:
docling-serve (`DOCLING_SERVE_URL`, PDF route), ascend-ocr (`ASCEND_OCR_URL`, image route) and
ascend-audio-scribe (`AUDIO_SCRIBE_URL`, audio route). Each probe waits at most
`STARTUP_PROBE_TIMEOUT_SECONDS` (default `2`). A routing target row reads `<url>/health [Connected]` when
its `/health` answers 2xx, `[Warning (status=<code>)]` on another status, and `[FAILED]` when it cannot be
reached. An empty URL reads `route off [Not configured]` and is not probed. A row is a warning only and never
stops the service from starting.

The three routing targets are not `/ready` probes. Each route is optional and answers on its own when its
target is down or turned off, so a missing target must not make the whole service not ready. Watch these rows
to see a routing target that is down.

---

### Observability endpoints

| Endpoint | Purpose |
| :--- | :--- |
| `GET /health` | Liveness (always 200 when the process is alive) |
| `GET /ready` | Readiness: probes Redis and SearXNG; 200 only when all upstreams respond |
| `GET /metrics` | Prometheus counters and histograms (strategy outcomes, durations, intervention rate) |
| `GET /docs` | Swagger UI |
| `GET /redoc` | Redoc |
| `GET /openapi.json` | OpenAPI 3 schema |

Every response includes the request's `X-Request-ID` header (echoed if the caller sent one, generated as
UUIDv4 otherwise). Inbound IDs are validated against `^[A-Za-z0-9._-]{1,128}$`; anything else gets replaced
with a fresh UUID to block log injection and response-splitting attempts.
