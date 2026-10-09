# Changelog: ascend-python-common

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top.

## [1.0.0] - <release date>

### Changed
- `1.0.0` cut once all four Python services are migrated (design D3). No code change since `0.1.0`.

## [0.1.0] - 2026-10-07

### Added
- First release of the shared platform library for the four Python services.
- `settings.py`: `ServiceSettings` base (`API_HOST`, `API_PORT`, `LOG_LEVEL`, `LOG_FORMAT`,
  `OTEL_EXPORTER_OTLP_ENDPOINT`, `RATE_LIMIT_DEFAULT`), `McpFetchSettings` mixin,
  `CsvTuple`, upper-casing `LogLevel`, start-up refusal of the old `MCP_ALLOWED_HOSTS` name.
  Tracing exports whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is set, which is unset by default,
  and the custom export switch is gone. Every operational value is a setting whose code
  default is the value used today: `READINESS_PROBE_TIMEOUT_SECONDS` (`3`),
  `STARTUP_PROBE_TIMEOUT_SECONDS` (`2`) and `SECURITY_HSTS_MAX_AGE_SECONDS` (`63072000`)
  on `ServiceSettings`, `FETCH_MAX_REDIRECT_HOPS` on `McpFetchSettings` with no default
  in the mixin so each service subclass sets its own, and `fetch_policy()` reads that
  field instead of taking the hop count as an argument.
- `errors/`: RFC 7807 problem body builder with `type`, `title`, `status`, `detail`, `instance`,
  `code` and `traceId`, `ProblemCode` and the platform codes, `ErrorRegistry`,
  `install_error_handlers`, refusal logging and `ascend_service_errors_total`, `McpRefusalMiddleware`.
- `log_config.py`: JSON or color logging that honours `LOG_LEVEL`, routes uvicorn and fastmcp
  through the root handler, adds `trace_id` and `span_id` fields, masks MCP session tokens.
- `request_context.py`: request id and MCP session digest as pure ASGI middleware plus the FastMCP
  log context middleware.
- `tracing.py`: tracer provider with the OTLP exporter and `ParentBased(ALWAYS_ON)` only when
  `OTEL_EXPORTER_OTLP_ENDPOINT` is set, a span processor dropping `mcp.session.id` at span start
  with no capture of the `mcp-session-id` header, `current_trace_id`. Worker tracing and the
  trace-context carry helpers stay in ascend-ocr, which builds its provider with the library
  builder, and `ServiceDefinition` carries no service-specific middleware or instrumentor
  fields: a service adds its own middleware to the returned app and installs its own
  instrumentor in its own lifespan.
- `readiness.py`: probe aggregator with a 3 second budget, `/health` and `/ready` bodies.
  The aggregator takes each probe's budget from `READINESS_PROBE_TIMEOUT_SECONDS`.
- `rate_limit.py`: REST limiter with `Retry-After` problem 429 bodies and per-tool MCP limiting on
  shared storage. The storage is `ServiceDefinition.rate_limit_storage_uri` (default `memory://`,
  Redis through each service's `REDIS_URL` so containers share one caller budget), every key carries
  the service name as its prefix, and an unreachable Redis falls back to in-memory limiting with a
  WARNING log instead of refusing traffic. New pin `redis==8.0.0`.
- `security_headers.py`: shared response headers as pure ASGI middleware.
  `strict-transport-security` is built once at start-up as
  `max-age=<SECURITY_HSTS_MAX_AGE_SECONDS>; includeSubDomains; preload`.
- `app.py`: `ServiceDefinition` and `create_service_app`, MCP served at `/mcp` only,
  in FastMCP stateless HTTP mode, so any container answers any MCP request.
- `startup_banner.py`: banner frame and printing rules with secret masking.
- `tooling.py` and `tooling/ruff.toml`: shared ruff rule set and the conformance check services call.
- `uri_guard.py` and `uri_guard_aiohttp.py` (fetch extra): SSRF check, address pinning, guarded
  redirects, `file://` jail. `MAX_REDIRECT_HOPS = 10` stays only as the default value the
  service subclasses give `FETCH_MAX_REDIRECT_HOPS`.
