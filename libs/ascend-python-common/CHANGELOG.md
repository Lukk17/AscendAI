# Changelog: ascend-python-common

All notable changes to this project are documented in this file. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to
[Semantic Versioning](https://semver.org/). Newest entry on top.

## [2.0.0] - <release date>

### Changed
- Breaking: the pinned version set moves to FastAPI 0.147.0, Starlette 1.9.0,
  uvicorn 0.54.0, FastMCP 4.1.1, MCP SDK 2.3.0 and httpx2 2.14.0 (owner pin
  2026-10-19, design D1). `mcp-types` 2.3.0 arrives with the SDK pin. Every
  service drops its own `httpx2` dev pin and follows the library set.
- The `/mcp` endpoint checks the `Host` and `Origin` headers of every request
  (new setting `MCP_ALLOWED_HOST_HEADERS`, empty refused at start-up, default
  per service: its compose service name, `localhost`, `127.0.0.1`). A refused
  `Host` answers 421, a refused `Origin` answers 403, REST routes are not
  checked (D10).
- `create_service_app` builds the app with FastAPI telemetry switched off
  (`tracing`, `metrics`, `logs`, `operation_spans` and `auto_configure` all
  false, the five keys checked against the installed 0.147.0 source), so the
  library keeps its single HTTP server span and its single exporter (D4).
- `http_app` is called with explicit transport settings: `stateless_http=True`,
  `json_response=False`, `session_idle_timeout=None` (D10).
- The FastMCP server reports the service version read from
  `importlib.metadata` in `initialize`, no longer the FastMCP version (D7).
  Each service passes its version when it builds its server.
- The MCP log context middleware takes the session digest from the
  `mcp-session-id` header of the carrying HTTP request through
  `get_http_request()`, checked against the SDK pattern, with no digest when
  the header is absent. The `mcp.types` import of that module moved to
  `mcp_types` (D6).
- Route lookup for REST rate limiting is the library's own
  `route_lookup.resolve_route`, which follows Starlette matching into included
  routers and mounts. slowapi keeps handling directly added routes, and the
  Prometheus instrumentator 8.1.0 already resolves included routers itself,
  so it needed no change (D3).
- The `mcp.session.id` drop now also runs at export time
  (`_SessionIdScrubbingExporter`), because FastMCP 4.1.1 re-adds the attribute
  after span start. The start-time processor is unchanged, no new processor
  and no condition was added (D5, owner decision 93).
- `build_tracer_provider` and `configure_tracing` take an optional `service_version`, put on the
  resource as `service.version`, where it wins over `OTEL_RESOURCE_ATTRIBUTES`. `create_service_app`
  passes the version of the service distribution read from `importlib.metadata`, the same value
  `/health` answers, so no compose file writes the version by hand. Existing callers keep working.
- No warning was silenced and no `noqa`, `type: ignore` or `pragma: no cover`
  was added.

### Fixed
- `strip_user_info` runs in linear time. The scheme part is limited to 32 characters, so a long run of letters no longer
  costs quadratic time.
- `format_check` removes user info from the status as well as from the target.
- `configure_logging` keeps the `fastmcp.server.mixins.mcp_operations` logger at WARNING whatever `LOG_LEVEL` is, so
  tool arguments never reach the log, even at DEBUG.
- `strip_user_info` now removes everything up to the last `@` before the
  first `/`, `?` or `#`. A password that holds an `@` is no longer partly
  printed, and an `@` in the query or fragment of an address with no path is
  no longer taken for user info.
- `configure_logging` keeps the `httpx`, `httpx2` and `httpcore` loggers at WARNING whatever `LOG_LEVEL` is, so a
  request address with a password or a signature never reaches the log.
- The URI guard refuses every address that is not globally routable, including the shared range 100.64.0.0/10 and the
  old IPv6 site-local range fec0::/10, also in IPv4-mapped form. A host name the name codec cannot encode, such as one
  with a 70 character label, is an `UnsafeUriError` and no longer a raw `UnicodeError`.
- A redirect `Location` that does not parse, such as `http://[`, is an `UnsafeUriError` and no longer a raw `ValueError`.

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
