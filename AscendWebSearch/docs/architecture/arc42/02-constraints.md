# 2. Constraints

---

### Technical constraints

| Constraint | Source | Impact |
| :--- | :--- | :--- |
| Python 3.12 | `pyproject.toml` `requires-python = ">=3.12"` | Cannot use syntax or stdlib additions from 3.13+. |
| Playwright base image | Dockerfile base `mcr.microsoft.com/playwright/python:v1.58.0-noble` | Includes Chromium, Xvfb, and all browser dependencies. Running `PlaywrightStrategy` or `NoVNCStrategy` outside this image requires manual browser installation. |
| Single-process, no worker pool | Uvicorn started with default workers (1) | Long extraction jobs (Playwright, Crawlee) queue behind each other. Adding `--workers N` requires session-state isolation analysis for module-level singletons. |
| FastMCP 2.14.5 | `pyproject.toml` pinned | MCP protocol is Streamable HTTP. The `mcp` instance in `mcp_server.py` is mounted as an ASGI sub-app; the FastMCP API may differ from sibling services using a different version. |
| In-monorepo service | `AscendWebSearch/` directory inside `AscendAI` | Shares AGENTS.md conventions, docker-compose network, and the `ascend-scrapper.docker-compose.yaml` external services group. Cannot be extracted without carrying those dependencies. |

---

### Organisational constraints

| Constraint | Impact |
| :--- | :--- |
| No separate release cadence | Ships with the monorepo. No independent image versioning beyond `0.1.0` in `pyproject.toml`. |
| External services required at runtime | SearXNG (port 9020), FlareSolverr (port 8191), and Redis (port 6379) must be running before the first search or read request. The service starts without them but fails on first use. |
| Ngrok is optional | `PUBLIC_VNC_URL` defaults to `http://localhost:7900`. Ngrok is only needed when the container is behind NAT and the operator needs remote VNC access. |
| Secrets handled by the host | No secrets manager integration. Configuration is injected as environment variables. |
