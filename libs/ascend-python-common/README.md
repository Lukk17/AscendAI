# ascend-python-common

One shared platform library for the four AscendAI Python services, so they answer errors, logs, traces, health checks and rate limits the same way.

---

### What it is and why it exists

The four Python services (ascend-audio-scribe, ascend-web-hunter, ascend-memory, ascend-ocr) each carried their own copy of the same cross-cutting code: error handlers, the settings class, logging setup, request id middleware, OpenTelemetry setup, readiness checks and the app wiring in `main.py`. A read-only measurement found about 1,000 duplicated lines, and the copies had drifted apart: three services ignored their `LOG_LEVEL` setting, only ascend-ocr had rate limiting, ascend-ocr did not answer RFC 7807 problem bodies while the other three did, ascend-web-hunter pinned older OpenTelemetry versions, ascend-memory named its MCP server `AscendMemory`, and ascend-audio-scribe named its port setting `MCP_PORT`. This library holds that code once. Each service keeps only its business code, its own error codes, its own settings fields and its own readiness probes.

---

### Quick start

Run every command from this folder:

```
libs/ascend-python-common
```

Create the virtual environment (Windows PowerShell):

```powershell
python -m venv .venv
```

Create the virtual environment (Linux or macOS):

```bash
python3 -m venv .venv
```

Install the library editable with both extras (Windows PowerShell):

```powershell
.venv/Scripts/python.exe -m pip install -e .[dev,fetch]
```

Install the library editable with both extras (Linux or macOS):

```bash
.venv/bin/python -m pip install -e .[dev,fetch]
```

Check the install resolves (Windows PowerShell):

```powershell
.venv/Scripts/python.exe -m pip check
```

Check the install resolves (Linux or macOS):

```bash
.venv/bin/python -m pip check
```

Check the package imports (Windows PowerShell):

```powershell
.venv/Scripts/python.exe -c "import ascend_python_common"
```

Check the package imports (Linux or macOS):

```bash
.venv/bin/python -c "import ascend_python_common"
```

A minimal service built on the library:

```python
from fastmcp import FastMCP

from ascend_python_common.app import ServiceDefinition, create_service_app
from ascend_python_common.settings import ServiceSettings


class Settings(ServiceSettings):
    API_PORT: int = 7020
    RATE_LIMIT_DEFAULT: str = "6000/minute"


settings = Settings()
mcp = FastMCP("ascend-memory")
app = create_service_app(
    ServiceDefinition(
        name="ascend-memory",
        distribution="ascend-memory",
        settings=settings,
        mcp=mcp,
    )
)
```

Run the full gate from this folder (Windows PowerShell):

```powershell
.venv/Scripts/python.exe -m ruff check .
```

```powershell
.venv/Scripts/python.exe -m ruff format --check .
```

```powershell
.venv/Scripts/python.exe -m mypy src tests
```

```powershell
.venv/Scripts/python.exe -m pytest
```

Run the full gate from this folder (Linux or macOS):

```bash
.venv/bin/python -m ruff check .
```

```bash
.venv/bin/python -m ruff format --check .
```

```bash
.venv/bin/python -m mypy src tests
```

```bash
.venv/bin/python -m pytest
```

The gate demands 100 percent branch coverage. A service that builds on this library installs it first from this folder, then itself, so pip finds the pinned version already installed and never asks an index for it.

---

### Architecture

Request path through an app built by `create_service_app`:

```text
client
  -> CorrelationIdMiddleware (pure ASGI, outermost, request id and MCP session digest)
  -> OpenTelemetry ASGI middleware (server span, always-on provider)
  -> Starlette stack
       -> SecurityHeadersMiddleware
       -> slowapi rate limiting (REST, default limit, /health /ready /metrics exempt, /mcp skipped, shared storage with the service name as key prefix, in-memory fallback)
       -> error handlers (registry entries, HTTPException, RequestValidationError, RateLimitExceeded, catch-all)
       -> service routers, /health, /ready, /metrics
       -> McpPathRoute (/mcp and /mcp/ only, everything else falls to the router)
            -> FastMCP middlewares: request log context, per-tool rate limit, refusal mapping
```

The MCP endpoint runs in FastMCP stateless HTTP mode, so any container answers any MCP request and no tool may rely on a server-to-client message between requests.

Path of one refused request. `GET /does-not-exist` matches no route, so the router answers the problem 404 from [src/ascend_python_common/errors/problem.py](src/ascend_python_common/errors/problem.py): status 404, media type `application/problem+json`, body members `type`, `title`, `status`, `detail`, `instance`, `code` (`not_found`) and `traceId` (the current span id from [src/ascend_python_common/tracing.py](src/ascend_python_common/tracing.py)). The refusal is logged once at WARNING without a traceback and counted in `ascend_service_errors_total{code="not_found", surface="rest", operation="unmatched"}`.

---

### Modules

| File | What it holds |
|---|---|
| [src/ascend_python_common/app.py](src/ascend_python_common/app.py) | `ServiceDefinition` and `create_service_app`, the `/mcp`-only route, lifespan order |
| [src/ascend_python_common/settings.py](src/ascend_python_common/settings.py) | `ServiceSettings`, `McpFetchSettings`, `CsvTuple`, upper-casing `LogLevel` |
| [src/ascend_python_common/log_config.py](src/ascend_python_common/log_config.py) | `configure_logging`, JSON or color format, `trace_id` and `span_id` fields, MCP session token masking |
| [src/ascend_python_common/request_context.py](src/ascend_python_common/request_context.py) | Request id and MCP session digest as pure ASGI middleware plus the FastMCP log context middleware |
| [src/ascend_python_common/tracing.py](src/ascend_python_common/tracing.py) | Tracer provider with the OTLP exporter only when `OTEL_EXPORTER_OTLP_ENDPOINT` is set, span processor dropping `mcp.session.id`, `current_trace_id` |
| [src/ascend_python_common/errors/codes.py](src/ascend_python_common/errors/codes.py) | `ProblemCode` and the platform codes |
| [src/ascend_python_common/errors/problem.py](src/ascend_python_common/errors/problem.py) | The one problem body builder |
| [src/ascend_python_common/errors/registry.py](src/ascend_python_common/errors/registry.py) | `ErrorRegistry`, exception type to code and detail |
| [src/ascend_python_common/errors/handlers.py](src/ascend_python_common/errors/handlers.py) | REST handler registration |
| [src/ascend_python_common/errors/mcp.py](src/ascend_python_common/errors/mcp.py) | FastMCP middleware mapping registered exceptions to tool errors |
| [src/ascend_python_common/errors/refusals.py](src/ascend_python_common/errors/refusals.py) | Refusal logging and the `ascend_service_errors_total` counter |
| [src/ascend_python_common/readiness.py](src/ascend_python_common/readiness.py) | Probe types, the aggregator, `/health` and `/ready` bodies |
| [src/ascend_python_common/rate_limit.py](src/ascend_python_common/rate_limit.py) | The limiter on `ServiceDefinition.rate_limit_storage_uri` (`memory://` by default, Redis for shared budgets), REST wiring, FastMCP per-tool limiting under the same service-name key prefix with in-memory fallback |
| [src/ascend_python_common/security_headers.py](src/ascend_python_common/security_headers.py) | Pure ASGI response headers |
| [src/ascend_python_common/startup_banner.py](src/ascend_python_common/startup_banner.py) | The banner frame and printing rules, one INFO record per start |
| [src/ascend_python_common/uri_guard.py](src/ascend_python_common/uri_guard.py) | The URI fetch guard: SSRF check, address pinning, redirect checks, `file://` jail |
| [src/ascend_python_common/uri_guard_aiohttp.py](src/ascend_python_common/uri_guard_aiohttp.py) | The pinned resolver and the guarded GET for aiohttp (needs the `fetch` extra) |
| [src/ascend_python_common/tooling.py](src/ascend_python_common/tooling.py) | The conformance check every service test suite calls |
| [tooling/ruff.toml](tooling/ruff.toml) | The shared ruff rule set every service extends |

---

### Comparison

Copying the code into each service is what this library replaces. It cost about 1,000 duplicated lines and the copies drifted, which is how three services ended up ignoring `LOG_LEVEL` while the fourth honoured it.

A cookiecutter template would stamp out four copies that drift again on the first fix that touches only one of them. The shared behaviour here changes in one place on purpose, so a template does not hold.

A private package index would add hosting, credentials and a publish step to every change, and this repository has none of those today. The library installs from its folder instead: editable in local virtual environments, and in Docker through a Compose additional build context. Where this loses: the name is not registered on any index, so a service install that runs before the library install would ask the index for it. Every documented install, the CI job and every Dockerfile install the library first, which closes that path.

---

### Configuration

Every service reads these base settings from its environment and its `.env` file. A value outside its bounds stops start-up with an error naming the field.

| Setting | Type and bounds | Default |
|---|---|---|
| `API_HOST` | string | `0.0.0.0` |
| `API_PORT` | integer, 1 to 65535 | none in the base, each service subclass sets its own port |
| `LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR` or `CRITICAL`, upper-cased before validation so `info` is accepted | `INFO` |
| `LOG_FORMAT` | `json` or `color` | `json` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | absolute http or https URL, or unset | unset, so nothing is exported |
| `RATE_LIMIT_DEFAULT` | string, parsed with the `limits` parser at start-up, so a typo stops start-up | per service, set by the subclass |
| `READINESS_PROBE_TIMEOUT_SECONDS` | float, greater than 0 | `3`, the budget of each readiness probe |
| `STARTUP_PROBE_TIMEOUT_SECONDS` | float, greater than 0 | `2`, the time each startup banner check may take |
| `SECURITY_HSTS_MAX_AGE_SECONDS` | integer, 0 or more | `63072000`, the `max-age` of the `strict-transport-security` response header |

Tracing exports whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is set. OpenTelemetry's standard `OTEL_SDK_DISABLED=true` switches the SDK off.

Services that fetch caller URIs add the `McpFetchSettings` mixin:

| Setting | Type and bounds | Default |
|---|---|---|
| `ALLOWED_PRIVATE_HOSTS` | comma separated tuple | empty |
| `MCP_FILE_URI_ROOT` | absolute path or unset | unset, so `file://` is refused |
| `MCP_DOWNLOAD_TIMEOUT_SECONDS` | positive float | set by the service subclass |
| `FETCH_MAX_REDIRECT_HOPS` | integer, 0 or more | no default in the mixin, each service subclass sets its own |

When `MCP_ALLOWED_HOSTS` is set in the environment, every service built on this library refuses to start with an error that names `ALLOWED_PRIVATE_HOSTS`. The old name grants nothing. Set `LOG_FORMAT=color` in a local `.env` for terminal output.

---

### Documentation map

| Document | What it covers |
|---|---|
| [pyproject.toml](pyproject.toml) | Version, the one pinned dependency set, the `dev` and `fetch` extras, the gate configuration |
| [CHANGELOG.md](CHANGELOG.md) | Version history, newest entry on top |
| [tooling/ruff.toml](tooling/ruff.toml) | The shared ruff rule set |
| [src/ascend_python_common/tooling.py](src/ascend_python_common/tooling.py) | The required mypy, pytest and ruff values services conform to |
| [ADR-M012](../../docs/architecture/decisions/ADR-M012-shared-python-library.md) | Why the library exists, where it installs from, how it versions |
| [design.md](../../openspec/changes/add-ascend-python-common/design.md) | The full design behind this library |
| [proposal.md](../../openspec/changes/add-ascend-python-common/proposal.md) | Why the change was made and what it changes |
