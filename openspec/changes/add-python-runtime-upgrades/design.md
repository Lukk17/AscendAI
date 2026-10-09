## Context

See `proposal.md` for why. This section records the starting point and the facts the decisions rest on, each with where it was read.

Starting point: this change starts after `add-ascend-python-common` is applied. At that point the library `libs/ascend-python-common` owns the one version set of the four services (its D4) and all shared web and MCP code: the app factory and the MCP path route (D12), the correlation id and MCP session digest middleware and the FastMCP log context middleware (D8), rate limiting on REST and MCP (D9), the MCP refusal middleware (D5), tracing with the span processor that drops the MCP session id from every span (D10, owner decision 93 of 2026-10-08, which replaced the session digest exporter wrapper). The services keep only business code, their tools and their own tests. The library is installed from its folder and pinned with `==` in every service (its D2 and D3), so a library version and the four pins always move in one commit.

Versions installed today, read from each service's `.venv` on 2026-10-03:

| Package | Today (all four services) | Latest on PyPI, 2026-10-03 | Released |
|---|---|---|---|
| `fastapi` | 0.136.3 | 0.142.2 | 2026-09-30 |
| `starlette` | 1.7.0 (not pinned, resolved) | 1.7.0 | 2026-09-23 |
| `uvicorn` | 0.48.0 | 0.54.0 | 2026-09-25 |
| `fastmcp` | 3.3.1 | 4.0.10 (4.0.0 on 2026-08-31, last 3.x is 3.4.7) | 2026-09-25 |
| `mcp` | 1.30.0 | 2.3.0 (2.0.0 on 2026-07-28) | 2026-10-02 |
| `mcp-types` | not installed | 2.3.0, exact-pinned by `mcp` | 2026-10-02 |
| `httpx2` | 2.13.1 (dev extra only) | 2.13.1 | |
| `pydantic` | 2.13.4 | 2.13.5 | 2026-08-28 |
| `sse-starlette` | 3.5.0 (ascend-ocr), 3.4.11 (others) | 3.5.0 | 2026-09-28 |

Sources: `https://pypi.org/pypi/<name>/json` and `https://pypi.org/pypi/<name>/<version>/json` for every version, date and `requires_dist` in this document, read with `curl` on 2026-10-03.

Facts from the release notes, migration guides and the released wheels:

- FastAPI 0.137.0 (2026-06-14) is the one release marked breaking in the range. `include_router` no longer copies path operations. `router.routes` becomes a tree that can hold intermediate router objects, and "any logic that depended on iterating on the `router.routes` directly would be affected" (https://github.com/fastapi/fastapi/releases/tag/0.137.0). Two libraries in the version set walk `app.routes` and descend only into Starlette `Mount` objects: slowapi 0.1.10 (`_find_route_handler` in `slowapi/middleware.py`, which also needs a route `endpoint`) and prometheus-fastapi-instrumentator 8.1.0 (`_get_route_name` in `routing.py`). Read in ascend-ocr's `.venv` on 2026-10-03.
- FastAPI 0.142.0 (2026-09-29) adds built-in OpenTelemetry, on by default for traces, metrics and logs. With an OTLP endpoint in the environment it adds an exporter to each enabled provider (`auto_configure`, default on). It records unhandled exceptions as OpenTelemetry log records with type, message and stack trace. It is configured with `FastAPI(telemetry={"tracing", "metrics", "logs", "operation_spans", "auto_configure", "exclude"})` (https://fastapi.tiangolo.com/advanced/opentelemetry/, https://github.com/fastapi/fastapi/pull/16403). 0.142.2 lets start-up continue when the automatic set-up fails. FastAPI 0.142.2 requires `opentelemetry-api>=1.44.0`, `starlette>=0.46.0`, `pydantic>=2.9.0` (PyPI).
- uvicorn 0.49.0 to 0.54.0 (https://uvicorn.dev/release-notes/): 0.50.0 exits with code 3 on any start-up failure, makes `--ws auto` pick `websockets-sansio` when `websockets` is installed and deprecates the legacy `websockets` implementation. 0.51.0 removes `colorama` from the `standard` extra. 0.53.0 trusts the IPv6 loopback in the default `FORWARDED_ALLOW_IPS`. 0.49.0 reverts the duplicate forwarding header handling of 0.48.0. No change to `uvicorn.run(app, host, port)` or to logging configuration.
- FastMCP 4 (https://gofastmcp.com/getting-started/upgrading/from-fastmcp-3, https://github.com/PrefectHQ/fastmcp/releases/tag/v4.0.0): builds on MCP SDK 2, needs `pydantic>=2.12` and `starlette>=1.0.1`, replaces `httpx` with `httpx2`. Middleware now sees every inbound message, including `notifications/cancelled`, `notifications/initialized` and messages that fail validation. Protocol model fields are snake_case, with a bridge for camelCase reads that emits `FastMCPDeprecationWarning` (`fastmcp.settings.mcp_camelcase_compat`, default true). `fastmcp.Client` defaults to `mode="auto"` and negotiates the sessionless 2026-07-28 era. It emits one SERVER span per MCP request. Removed: `as_proxy`, `import_server`, `mount(prefix=)`, `ctx.sample`, `ctx.list_roots`, tool `serializer=` and `exclude_args=`. A missing resource answers `-32602` instead of `-32002`.
- FastMCP 4.0.10 wheel, read on 2026-10-03: `http_app(path, middleware, json_response, stateless_http, transport, event_store, retry_interval, host_origin_protection, allowed_hosts, allowed_origins, session_idle_timeout)`. Defaults: `streamable_http_path="/mcp"`, `stateless_http=False`, `json_response=False`, `http_host_origin_protection=False`, `http_session_idle_timeout=None`. The `FastMCP(...)` constructor still takes `name`, `middleware`, `lifespan`, and takes `version`. `Middleware` keeps `on_request` and `on_call_tool`, and `MiddlewareContext` keeps `fastmcp_context`. `Context.session_id` returns the connection's session id on a session-based connection and otherwise falls back to the request's `mcp-session-id` header or a new `uuid4()` string. FastMCP's server spans set `mcp.session.id` to `ctx.session_id` (`fastmcp/server/telemetry.py`). Sync tool functions run in a worker thread in both 3.3.1 and 4.0.10 (`fastmcp/utilities/async_utils.py`), so the sync tools of ascend-memory and ascend-ocr behave as today.
- MCP Python SDK 2 (https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md, read as raw text on 2026-10-03): the handshake era (`HANDSHAKE_PROTOCOL_VERSIONS` = 2024-11-05, 2025-03-26, 2025-06-18, 2025-11-25) and the sessionless era (2026-07-28) are both served. `mcp.server.streamable_http` still exports `MCP_SESSION_ID_HEADER = "mcp-session-id"` and `SESSION_ID_PATTERN = ^[\x21-\x7E]+$`, and its loggers keep the names `mcp.server.streamable_http` and `mcp.server.streamable_http_manager` (read in the 2.3.0 wheel). Streamable HTTP bodies above 4 MiB answer 413 before parsing. Server results are validated against the negotiated protocol schema. Unknown methods answer `-32601`. OpenTelemetry propagation is on by default, with a server tracing middleware on the `mcp-python-sdk` tracer, no-op without an SDK provider. `mcp.types` is an alias of the new `mcp-types` package. `pydantic-settings` is no longer an SDK dependency and `MCP_*` environment variables are not read. The 1.x line keeps receiving critical fixes only.
- Agent side, today (read on 2026-10-05): the agent runs Spring Boot 3.5.14 and Spring AI 1.1.5 (`apps/ascend-agent/gradle/libs.versions.toml`), and connects to the Python servers with `spring-ai-starter-mcp-client-webflux` over `spring.ai.mcp.client.streamable-http.connections` (`application.yaml`). Spring AI 1.1.5 depends on the MCP Java SDK 0.17.0 (`spring-ai-mcp-1.1.5.pom` in the local Gradle cache), whose `io.modelcontextprotocol.spec.ProtocolVersions` holds 2024-11-05, 2025-03-26 and 2025-06-18 (read from `mcp-core-0.17.0.jar` in the same cache). So today's agent negotiates 2025-06-18 over the session-based handshake, which MCP SDK 2 still serves (its `HANDSHAKE_PROTOCOL_VERSIONS` above). It does not speak the sessionless 2026-07-28 era.
- Agent side, later: `upgrade-spring-boot-4` (build group 3, position 2, lands after this change) moves the agent to Spring AI 2.0.1 with MCP Java SDK 2.0.0 (`mcp-core`), its D11. MCP Java SDK 2.0.0 "tracks the latest 2025-11-25 MCP specification", is Streamable HTTP first, and its transports advertise all known protocol versions (https://github.com/modelcontextprotocol/java-sdk/releases, read on 2026-10-03). It does not speak the sessionless era either, so the upgraded agent negotiates 2025-11-25 over the same handshake. `upgrade-spring-boot-4` carries the task that checks this again after its upgrade (owner answer 70.1 of 2026-10-04).
- The e2e specs and Bruno requests that call MCP directly send `initialize` with protocol 2025-06-18 (ascend-ocr specs 5, 10, 11, 14, 20) or 2025-11-25 (ascend-memory and ascend-audio-scribe specs 4 and 5), read with `git grep protocolVersion` on 2026-10-03. Both stay inside the handshake era.
- No Python service registers an MCP resource or prompt or uses `ctx` in a tool (`git grep` of `@mcp.resource`, `@mcp.prompt`, `ctx.` under `apps/*/src`, 2026-10-03), so the removed `Context` methods and the resource error code touch no service code.

## Goals / Non-Goals

Goals:

- The four services and the library on the latest FastAPI, uvicorn, FastMCP and MCP SDK, one version each, with every service gate green and no warning silenced.
- No change to any REST body, any MCP tool result or any setting a deployment sets.
- Today's agent (Spring Boot 3.5.14, Spring AI 1.1.5) keeps connecting to all four MCP servers with no code change.

Non-Goals:

- No adoption of FastAPI's built-in telemetry as the trace path (D4 keeps the library's ASGI middleware). The owner decided on 2026-10-03 (answer 61.1, open question 1 closed) that there is no switch now, and the library keeps its own tracing setup.
- No adoption of the sessionless protocol's new features (`server/discover`, `subscriptions/listen`, multi-round tools). The servers serve sessionless clients because the SDK does, nothing more.
- No change to ascend-weather-mcp. It is Java and moves later with `upgrade-spring-boot-4`.
- No upgrade of business libraries (paddleocr, mem0ai, crawlee, playwright and the rest) or of the OpenTelemetry, Prometheus, slowapi and logging packages the library already moved to their latest release on 2026-10-03.

## Decisions

### D1: The target version set

In `libs/ascend-python-common/pyproject.toml`, replacing the kept versions of `add-ascend-python-common` D4:

| Package | From | To | Why |
|---|---|---|---|
| `fastapi` | 0.136.3 | 0.142.2 | Latest. Owner asked for it |
| `uvicorn` | 0.48.0 | 0.54.0 | Latest. Owner asked for it |
| `fastmcp` | 3.3.1 | 4.0.10 | Latest. Owner asked for FastMCP 4 |
| `mcp` | 1.30.0 (via `mcp>=1.30.0` in ascend-ocr) | 2.3.0 | Latest. Required by FastMCP 4 (`mcp>=2.0.0,<3`). Pinned directly because the library imports `mcp.server.streamable_http` itself |
| `starlette` | not pinned, 1.7.0 resolved | 1.7.0 | Same version, now pinned, because the library and the services import Starlette types directly and FastMCP 4 sets a floor of 1.0.1 |
| `httpx2` | not a runtime dependency | 2.13.1 | New runtime dependency of `mcp` 2 and FastMCP 4. Pinned to the version every service's `dev` extra already pins, and each service drops that own `dev` pin |

Not pinned on purpose: `mcp-types`, which `mcp` pins exactly to its own version (the SDK guide says not to pin it separately). Unchanged: `pydantic==2.13.4` and `pydantic-settings==2.14.1` (the new floors are `pydantic>=2.12` and FastMCP's `pydantic-settings>=2.0`, both met, and the owner's list does not include them), the OpenTelemetry set 1.45.0 and 0.66b0 (FastAPI 0.142.2 needs `opentelemetry-api>=1.44.0`, met), `prometheus-fastapi-instrumentator==8.1.0` (`starlette>=1.0.0,<2`, met), `slowapi==0.1.10`. `sse-starlette` stays transitive and resolves to 3.5.0, above the SDK floor of 3.0.0. The services that import `httpx` themselves (ascend-web-hunter, ascend-memory, ascend-audio-scribe) keep their own `httpx==0.28.1` pin, because `mcp` 2 no longer brings it.

Alternatives considered: staying on FastMCP 3.4.7 with `mcp` 1.x (rejected, the owner asked for FastMCP 4 and the MCP SDK 2, and the 1.x line gets only critical fixes), and FastMCP 4 with a `mcp` range instead of a pin (rejected, one exact version per package is the library's rule).

### D2: Library major version and commit shape

The library's public types expose FastMCP (`ServiceDefinition.mcp` is a `FastMCP` server, the middlewares subclass FastMCP's `Middleware`), so moving FastMCP 3 to 4 is a breaking change of the library and its version moves to the next major (from the `1.0.0` that `add-ascend-python-common` task 8.1 cuts, to `2.0.0`).

Because the services pin the library with `==` and pip refuses a folder holding another version (`add-ascend-python-common` D3), the library version and the four pins cannot move one service at a time. The work is split so that review stays per service and the risky step is one commit:

1. One preparation commit per service, on the old versions, each green on its own gate: the tests that pin today's MCP and REST behaviour where they are missing, the tests of the `python-mcp-runtime` spec that already pass on FastMCP 3, and every change that works on both versions (no camelCase field reads, the in-memory client given an explicit protocol era where FastMCP 3 allows it).
2. One upgrade commit: the library's version set, its code changes (D3 to D9), its major version, the four service pins and whatever version-dependent fix each service needs. All five gates (library and four services) and the ascend-ocr Pact provider verification are green before it is committed.
3. One documentation commit.

Rollback is a revert of commit 2. The preparation commits stay, because they pass on both versions.

### D3: FastAPI's router tree and the route-based behaviour

After 0.137.0, a route that comes from `include_router` may sit inside an intermediate router object in `app.routes`. slowapi's middleware finds the route's endpoint by walking `app.routes` (to apply a route's own limit and the exemptions), and the Prometheus instrumentator finds the route template the same way (the `handler` label). Both descend only into `Mount`. The library's MCP path route class from `add-ascend-python-common` D12 is a direct child of the app and is not affected.

Decision: the spec requirement "Route-based behaviour keeps the route template" is written as tests first, on the old version (they pass) and then on the new one. If either library loses the route under the router tree, the library replaces that lookup with its own, written once in `ascend_python_common`: a function that resolves the matched route and its template through Starlette's own matching on the request scope (which every route and router type implements, including FastAPI's new `matches()`), used by the rate limit wiring and passed to the instrumentator. Third-party code is never patched in place, and no route is moved out of its router to get around it.

### D4: FastAPI's built-in telemetry is configured off

The library's trace path stays the OpenTelemetry ASGI middleware outside Starlette's whole stack (`add-ascend-python-common` D10), because only a span started there is still open when `ServerErrorMiddleware` builds the 500 body, which must carry `traceId`. FastAPI 0.142's own telemetry would add a second request span, add its own exporters from `OTEL_EXPORTER_OTLP_ENDPOINT` (which compose sets for the services), a second exporter beside the library's one, which exports whenever that endpoint is set (owner decision 89.14 of 2026-10-08), and write exception messages and stack traces to OpenTelemetry logs.

`create_service_app` therefore builds the app with `telemetry={"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False}`, the five keys the FastAPI documentation lists. The key names are checked against the 0.142.2 source before use (task 2.3), and a test proves the result: one HTTP server span per request, nothing sent to the endpoint with export off, no OpenTelemetry log record for an exception.

Alternative considered: adopting FastAPI's telemetry and dropping the ASGI instrumentation. Rejected for this change, because the documentation does not say where its request span starts relative to `ServerErrorMiddleware`, its exception logs carry the text the library keeps out of every response and log line, and the library's Prometheus metrics already cover what its metrics would add. The owner confirmed this on 2026-10-03 (answer 61.1, open question 1 closed): no switch to FastAPI's built-in telemetry now, the library keeps its own tracing setup.

### D5: MCP spans and the session attribute

MCP SDK 2 installs its own server tracing middleware and FastMCP 4 emits a SERVER span per MCP request, both on the global tracer provider the library installs. They are non-recording when export is off, that is with `OTEL_EXPORTER_OTLP_ENDPOINT` unset (the library's sampler is `ParentBased(ALWAYS_OFF)` then), and do not exist with `OTEL_SDK_DISABLED=true`, and become children of the HTTP server span when it is on, because the MCP request runs inside the HTTP request's context. FastMCP sets `mcp.session.id` to `ctx.session_id`, which on a sessionless request is a `uuid4()` string FastMCP makes up.

Decision (owner decision 93 of 2026-10-08, review item C10, which replaces the first plan of a conditional span processor ahead of the digest exporter wrapper): `add-ascend-python-common` already drops `mcp.session.id` from every span at span start with one span processor (its D10 and task 1.16), so a made-up `uuid4()` of a sessionless request is dropped by the same processor as a client's session id, and this change adds no processor and no condition. Task 6.4 checks on FastMCP 4 and MCP SDK 2 that the processor still sees the attribute at span start in both eras. A test with the SDK's in-memory exporter covers both eras. What is lost is grouping spans by MCP session in Tempo, which the owner accepted. The trace shape (one HTTP server span, MCP spans below it) is a test of the spec requirement "One trace per request and one exporter".

### D6: The log context and the session digest

The FastMCP log context middleware (`add-ascend-python-common` D8, taken from ascend-ocr's `request_log_context.py`) takes the session digest from `ctx.session_id` today. On FastMCP 4 that value is made up for a sessionless request. Decision: the middleware takes the session id from the `mcp-session-id` header of the HTTP request that carried the message (`fastmcp.server.dependencies.get_http_request()`, the access FastMCP 4 documents for middleware), checks it against the SDK's `SESSION_ID_PATTERN` exactly as the ASGI middleware does, and binds no digest when the header is absent. The `mcp.types` import of that module moves to `mcp_types`.

FastMCP 4 also calls `on_request` and `on_message` for notifications and for messages that fail validation. The log context middleware binds the ids for every message it sees (a notification's log lines get the request's ids too), and it tolerates a message without a FastMCP context. The rate limit and refusal middlewares stay on `on_call_tool` only, so a notification is never counted, limited or mapped. Tests send `notifications/initialized`, `notifications/cancelled` and an unknown method through each middleware.

### D7: The MCP server reports its version

MCP SDK 2 reports an empty server version when none is given. `create_service_app` passes the service version (already read through `importlib.metadata` for `/health`) to the FastMCP server, so `initialize` reports `name` and `version`. A test checks both in the handshake result.

### D8: camelCase reads fail the test gate

Every service and the library run pytest with warnings as errors, so any camelCase read through FastMCP's bridge already fails as `FastMCPDeprecationWarning`. On top of that, the library's test fixtures set `fastmcp.settings.mcp_camelcase_compat = False` for the whole session, so a leftover read fails as an `AttributeError` that names the field. Production keeps FastMCP's default: the services make no such read once the gates pass, and a third-party read would log a warning instead of failing a request.

### D9: Tests name their protocol era

`fastmcp.Client` defaults to the sessionless era in FastMCP 4. The agent speaks the handshake era. Every test that asserts session behaviour (the session digest, the `mcp-session-id` header, refusals on a session) builds the client with `mode="legacy"`, the client the agent behaves like. The library's integration test (`add-ascend-python-common` D15) runs its MCP scenarios once with `mode="legacy"` and once with `mode="auto"`, so both eras are covered. Raw HTTP tests keep sending `initialize` with an explicit `protocolVersion`.

### D10: MCP transport settings are explicit, and the Host and Origin check is on

`http_app(path="/mcp")` keeps its signature. The library passes the transport settings it relies on explicitly instead of trusting defaults that a later release could change: `stateless_http=True` (owner answer 94.2 of 2026-10-08, `add-ascend-python-common` D12: any container of a service answers any MCP request, and no tool relies on a server-to-client message between requests), `json_response=False`, `host_origin_protection=True`, `allowed_hosts` and `allowed_origins` as below, `session_idle_timeout=None`.

Host and Origin header check (owner answer 61.2 of 2026-10-03, open question 2 closed). FastMCP 4's guard against DNS rebinding is switched on in all four services, configured once in the library:

- A new setting in the library's `ServiceSettings` base (`add-ascend-python-common` D6): `MCP_ALLOWED_HOST_HEADERS`, a comma separated list of host names, read like `ALLOWED_PRIVATE_HOSTS` (the shared `CsvTuple`). Its default is the service's own compose service name plus `localhost` and `127.0.0.1`: `ascend-ocr,localhost,127.0.0.1` in ascend-ocr, and the same pattern with `ascend-memory`, `ascend-audio-scribe` and `ascend-web-hunter`. Each service subclass sets its default, as it sets `API_PORT`. The compose service name is the host name the agent container uses (`application-docker.yaml`: `http://ascend-ocr:7022`, `http://ascend-memory:7020`, `http://ascend-audio-scribe:7017`, `http://ascend-web-hunter:7021`). `localhost` and `127.0.0.1` stay in the default because the agent run on the host (`application.yaml`), the Bruno collection, the compose health checks and the e2e specs all call `http://localhost:<port>`. An empty value is refused at start-up, because it would refuse every MCP request.
- The name is not `MCP_ALLOWED_HOSTS` (renamed `ALLOWED_PRIVATE_HOSTS` by `add-ascend-python-common` D22, owner answer 68.2 of 2026-10-04), because that setting already exists with another meaning: the hosts the URI fetch guard may reach (`add-ascend-python-common` D21). The owner approved the name `MCP_ALLOWED_HOST_HEADERS` on 2026-10-04 (answer 62, open question 3 closed), so it is decided. The two names differ by direction: `ALLOWED_PRIVATE_HOSTS` is outbound (where a service may fetch from), `MCP_ALLOWED_HOST_HEADERS` is inbound (which `Host` header a caller may send to `/mcp`). D14 sets how the documentation shows them side by side.
- The library turns each host name into the entries the FastMCP 4.0.10 guard matches. Whether an entry must carry the port (`ascend-ocr:7022`) or a port wildcard is read in the installed 4.0.10 source in task 6.5, and the library builds the entries from `API_PORT` if it must, so the setting holds host names only.
- `allowed_origins` is empty: the services serve no browser, so a request that carries an `Origin` header is refused, and a request without one (the agent, Bruno, curl) is not affected.
- A refused request gets FastMCP's own answer before any session is created. Its status codes (421 for a wrong `Host` in MCP SDK 1, 403 for a wrong `Origin`) are read in the 4.0.10 source in task 6.5 and recorded in the library README. The guard covers `/mcp` only. REST routes are not affected.
- A deployment that reaches a service by another name sets the setting: the standalone ascend-web-hunter (`apps/ascend-web-hunter/deploy-standalone/`), which callers reach by the machine's own host name, documents it in its `.env.example` and README table, per the sync rule, together with the root `.env.example`.
- Compose lines (owner rule 98 of 2026-10-08, `add-ascend-python-common` D26): each compose service passes the setting with its code default, under an interpolation name that carries the service, because the four defaults differ (the reason `add-ascend-python-common` D26 gives for its `MEMORY_`, `AUDIO_SCRIBE_`, `WEB_HUNTER_` and `OCR_` names). In `compose.yaml`: `- MCP_ALLOWED_HOST_HEADERS=${MEMORY_MCP_ALLOWED_HOST_HEADERS:-ascend-memory,localhost,127.0.0.1}` on `ascend-memory`, `- MCP_ALLOWED_HOST_HEADERS=${AUDIO_SCRIBE_MCP_ALLOWED_HOST_HEADERS:-ascend-audio-scribe,localhost,127.0.0.1}` on `ascend-audio-scribe` and `- MCP_ALLOWED_HOST_HEADERS=${OCR_MCP_ALLOWED_HOST_HEADERS:-ascend-ocr,localhost,127.0.0.1}` on `ascend-ocr`. In `compose.ascend-web-hunter.yaml` and, under the sync rule, in `apps/ascend-web-hunter/deploy-standalone/compose.yaml`: `- MCP_ALLOWED_HOST_HEADERS=${WEB_HUNTER_MCP_ALLOWED_HOST_HEADERS:-ascend-web-hunter,localhost,127.0.0.1}` on `ascend-web-hunter`. The standalone operator sets `WEB_HUNTER_MCP_ALLOWED_HOST_HEADERS` in the bundle's `.env`, so the root `.env.example`, `deploy-standalone/.env.example` and the configuration table of `deploy-standalone/README.md` name that interpolation variable with its default and say that it fills `MCP_ALLOWED_HOST_HEADERS`. No other `.env.example` line is added. The bundle keeps its pinned image, so its new line takes effect once its image tag moves to a version built with this change.
- The check is a hardening step beside the service token of `add-keycloak-login`, not a replacement for it.

The 4 MiB body limit of MCP SDK 2 is kept, because every file reaches the MCP tools as a URI, and the spec requirement "The MCP endpoint refuses an oversized request body" pins it. It stays a fixed value of the SDK, not a setting of this change (owner rule 98 of 2026-10-08): MCP SDK 2.3.0 defines it as `DEFAULT_MAX_REQUEST_BODY_SIZE = 4 * 1024 * 1024` in `mcp/server/transport_security.py` and its `StreamableHTTPSessionManager` takes `max_request_body_size`, but FastMCP 4.0.10 builds that manager in `create_streamable_http_app` of `fastmcp/server/http.py` (package `fastmcp-slim` 4.0.10, which `fastmcp` 4.0.10 installs) without passing it, and `http_app` has no parameter for it (both read in the released wheels on 2026-10-09). Reaching it would mean replacing FastMCP's session manager, which the rule of D3 that third-party code is never patched forbids. When a later FastMCP release passes the limit through, the change that moves to that release makes it a setting with the same default.

### D11: uvicorn changes need no code

`uvicorn.run("src.main:app", host=..., port=...)` and the `uvicorn` command lines in the Dockerfiles and in web-hunter's `supervisord.conf` keep working. ascend-ocr keeps `--ws none`. The other three serve no WebSocket route, and with `websockets` now installed through FastMCP 4 the default `--ws auto` picks the non-deprecated `websockets-sansio`, so no deprecation warning appears. Exit code 3 on a start-up failure changes nothing for compose (`restart: unless-stopped`) or supervisord (`autorestart=true`), both restart on any code. The forwarded header changes of 0.49.0 and 0.53.0 do not reach the rate limit key, because the services trust no proxy headers beyond uvicorn's loopback default.

Stateless HTTP mode and the agent (owner answer 94.2 of 2026-10-08). In stateless mode the server answers the handshake with no `mcp-session-id` header, serves every later request in a fresh transport context, and answers a `GET` on `/mcp` with 405 (FastMCP 3.3.1 `fastmcp/server/http.py` serves only `POST` and `DELETE` there in stateless mode, read on 2026-10-08, re-read in 4.0.10 in task 6.5). Today's agent copes with both: its transport `WebClientStreamableHttpTransport` of `mcp-spring-webflux` 0.17.0 (sources jar in the local Gradle cache, read on 2026-10-08) adds the `mcp-session-id` header only when the server sent one (`transportSession.sessionId().ifPresent(...)`), and on a 405 to its `GET` it logs "The server does not support SSE streams, using request-response mode." and goes on. The proof on the running stack is the agent check of D12.

### D12: The agent side

The change is checked against today's agent, Spring Boot 3.5.14 and Spring AI 1.1.5 (owner answer 70.1 of 2026-10-04). It needs no change: its MCP Java SDK 0.17.0 negotiates 2025-06-18 over the handshake, which MCP SDK 2 serves, in stateless HTTP mode with no `mcp-session-id` (D10, owner answer 94.2 of 2026-10-08). Proof, after the images are rebuilt: today's agent MCP tests run green, `McpStartupToleranceIT` and `McpStartupTimeoutIT` under `src/test/java/com/lukk/ascend/ai/agent/integration/` and the unit tests under `src/test/java/com/lukk/ascend/ai/agent/config/mcp/` (`McpClientStartupInitializerTest`, `McpClientStatusRegistryTest`, `McpConnectionNamesTest`, `McpToolCallbackCacheTest`, `FilteredToolCallbackProviderTest`), all present on 2026-10-05, and the running agent lists the tools of all four Python servers with the same names as before (its startup log and `McpClientStatusRegistry` state, read with `docker logs`). If the Java client and a Python server disagree, the fix goes into the Python side's configuration (D10), never into a pinned older SDK.

After `upgrade-spring-boot-4` moves the agent to Spring AI 2.0.1 and MCP Java SDK 2.0.0, the same check runs again, with the handshake at 2025-11-25. That re-check is task 15.2 of `upgrade-spring-boot-4` (build group 3, position 2, its D21), not of this change, because this change lands first.

### D13: Tests and gates

- Library: its full gate (ruff, ruff format, mypy strict on `src` and `tests`, pytest with 100 percent branch coverage and warnings as errors) on the old versions after group 1 and on the new ones in group 2.
- Each service: its full gate through its own `.venv` with the 100 percent branch coverage gate, on the old versions after its preparation group and on the new ones in group 2. No `noqa`, `type: ignore`, `pragma: no cover` or `filterwarnings` ignore is added. A warning from a third-party package with no fix gets a narrow ignore naming that package's module only, the rule `add-ascend-python-common` D14 already sets, and each one is listed in the library changelog.
- ascend-ocr Pact provider verification (`python -m pytest -m contract --no-cov` from `apps/ascend-ocr`) against the committed pact, before and after. The pact itself does not change, because no REST body changes.
- Agent: D12, against today's agent. The re-check after `upgrade-spring-boot-4` is that change's task.
- Containers: each image rebuilt and started after the owner approves the Docker commands, then `/health`, `/ready`, one MCP `initialize` with 2025-11-25 and one tool call per service.
- End to end: the owner chooses the run scenario or service suite from `docs/E2E_RUN_SCENARIOS.md` before any e2e run. The heavy OCR specs run alone.

### D14: Documentation

Library `README.md` (version table) and `CHANGELOG.md` (the major version entry with every behaviour change of D4 to D10), each service's `AGENTS.md` Tech Stack line (FastMCP version, where it is named) and `CHANGELOG.md`, the root `AGENTS.md` cross-module conventions bullet if it names versions, the setting `MCP_ALLOWED_HOST_HEADERS` of D10 in the library README configuration table, each service's `AGENTS.md` environment variable list, the root `.env.example`, `apps/ascend-web-hunter/deploy-standalone/.env.example` and the configuration table of `deploy-standalone/README.md` (the sync rule), and `docs/architecture/decisions/ADR-M013-python-runtime-upgrade.md` with its line in `docs/architecture/decisions/README.md`. The ADR records D4, D5 and D10, the decisions a later reader would otherwise undo. The two settings are explained side by side wherever either is documented, in a two row table or two adjacent list entries that name the direction of each: `ALLOWED_PRIVATE_HOSTS` is outbound, the hosts the URI fetch guard may reach even at a private address, read by ascend-ocr, ascend-audio-scribe and ascend-web-hunter (`add-ascend-python-common` D21 and D22). `MCP_ALLOWED_HOST_HEADERS` is inbound, the `Host` header values the `/mcp` endpoint of a service accepts, read by all four services (D10). Each entry says that one does not replace the other, and ascend-memory, which has no `ALLOWED_PRIVATE_HOSTS`, says so next to its `MCP_ALLOWED_HOST_HEADERS` entry. The number is checked free before writing and renumbered if another change takes it first.

### D15: Service versions

Owner decision of 2026-10-08: one named version per change, in build order. This change is position 2 of build group 2 in `openspec/BUILD_ORDER.md` and takes one patch step from the version `add-ascend-python-common` (position 1, its D25) leaves:

| Service | Before | After |
| --- | --- | --- |
| ascend-memory | 0.1.4 | 0.1.5 |
| ascend-audio-scribe | 0.9.4 | 0.9.5 |
| ascend-web-hunter | 0.0.7 | 0.0.8 |
| ascend-ocr | 0.3.1 | 0.3.2 |

Each service gets exactly one `## [x.y.z] - <release date>` entry for this change, at the top of its `CHANGELOG.md`, and tasks 6.11 and 6.12 both write into it. The same commit moves `version` in the service's `pyproject.toml`, the `Version` line of its `AGENTS.md` where it has one (ascend-audio-scribe has none), and the version that `docs/architecture/arc42/02-constraints.md` names in ascend-web-hunter and ascend-ocr. `open-several-novnc-windows-at-once` (position 3) continues from ascend-web-hunter 0.0.8.

### Required edits to other changes

This change does not edit other changes (owner instruction of 2026-10-03). The owner chose one pass: every place below, the renumbering and the content edits, was made in its target change on 2026-10-03 (made, checked with `openspec validate --strict` on every active change). The renumbering below records the 18-number order of 2026-10-03, which is superseded by the owner build order of 2026-10-04 (five build groups). It is kept as history only. `open-several-novnc-windows-at-once` also states in its build order text that it lands after `add-ascend-python-common` and this change.

Build order renumbering. Every build order list gains `3 add-python-runtime-upgrades` after `2 add-ascend-python-common`, every later entry moves up by one (`add-deployment-modules` becomes 4, `add-self-built-integrations` becomes 18), the provenance note gains "number 3 inserted by owner answer 60.6 of 2026-10-03", every "This change is number N" and every "number N" that refers to this order with N of 3 or more becomes N plus 1, "seventeen planned changes" becomes "eighteen", and "number 17, the last" becomes "number 18, the last". A "number 1" or "number 2" stays. Places found with `git grep -n -E "number [0-9]+|1 \`upgrade-spring-boot-4\`|seventeen" -- openspec/changes ":!openspec/changes/archive"` on 2026-10-03 (file and line):

| Change | Places |
|---|---|
| `upgrade-spring-boot-4` | `proposal.md` 3 |
| `add-ascend-python-common` | `proposal.md` 3 and 5 (also add this change to the list of what it lands before), `design.md` 58 and 307 |
| `add-deployment-modules` | `proposal.md` 3 |
| `add-shared-scheduler` | `proposal.md` 3 |
| `add-agent-skills` | `proposal.md` 5, `design.md` 259 |
| `add-agent-subagents` | `proposal.md` 3, `design.md` 464, `tasks.md` 21 |
| `add-agent-sandbox` | `proposal.md` 3, 5 and 28, `design.md` 6 and 499 |
| `add-agent-soul` | `proposal.md` 3 |
| `add-action-approvals` | `proposal.md` 3 and 5, `design.md` 190 and 414, `tasks.md` 3 |
| `add-mcp-tool-servers` | `proposal.md` 3 and 5 |
| `add-obsidian-vault` | `proposal.md` 3 and 5, `tasks.md` 3 |
| `add-openclaw-plugin-host` | `proposal.md` 3, 5 and 20 |
| `add-file-download` | `proposal.md` 39 and 41, `design.md` 14 and 432, `tasks.md` 3 |
| `add-coding-agent-delegation` | `proposal.md` 3 and 5, `design.md` 5, 13, 14 and 606, `tasks.md` 3 |
| `add-scheduled-tasks` | `proposal.md` 3, `design.md` 200 |
| `add-self-improvement` | `proposal.md` 3 |
| `add-self-built-integrations` | `proposal.md` 3 and 5, `design.md` 16 and 442 |
| `add-observability` | `proposal.md` 54 and 57 |
| `add-document-connectors` (these build order statements moved to `add-connector-framework` with the framework on 2026-10-04) | `proposal.md` 5, `design.md` 24 to 29, `tasks.md` 16 |
| `add-document-management-api` | `proposal.md` 56, `design.md` 10 to 15, `tasks.md` 4 |
| `add-passage-level-citations` | `proposal.md` 55, `design.md` 11, `tasks.md` 7 |
| `add-web-crawl-rag-connector` | `proposal.md` 41 |
| `add-tenant-isolation` | `proposal.md` 51, `design.md` 18 |
| `add-tenant-policy` | `proposal.md` 36, `design.md` 141 |
| `add-customer-stack-installer` | `proposal.md` 21 |
| `harden-cloud-deployment` | `proposal.md` 36 |
| `update-docs-and-architecture` | `proposal.md` 9 and 32 |
| `enhance-web-search-extraction-and-tiers` | `proposal.md` 61 and 63, `design.md` 82 |
| `enhance-web-search-crawl-at-scale` | `proposal.md` 59, 62 and 64, `design.md` 120 |
| `remove-flaresolverr-tier` | `design.md` 12 (check whether the number refers to this order) |
| `add-auth-and-identity` (the service token part moved to `add-keycloak-login` on 2026-10-04) | `proposal.md` 60, `design.md` 189 (check whether the number refers to this order) |

Line numbers are those of 2026-10-03 and move when another agent edits a file. The grep above finds them again. Some hits name "number 2" (`add-ascend-python-common`), which stays.

Content edits:

| Change | Place | What must change |
|---|---|---|
| `add-ascend-python-common` | `design.md` D4 ("Kept at the version all four already share") and the Non-Goals line | Name this change as the one that moves `fastapi`, `uvicorn`, `fastmcp` and `mcp`, and add that `starlette` and `httpx2` join the set here. No version in its own D4 changes |
| `enhance-web-search-extraction-and-tiers`, `enhance-web-search-crawl-at-scale`, `detect-challenge-walls-in-any-language`, `enhance-web-search-tier-ladder` | their dependency sentence in `proposal.md` | Each also depends on `add-python-runtime-upgrades` (number 3), so its MCP tools and tests are written against FastMCP 4 and its tests that use `fastmcp.Client` name the protocol era (D9) |
| `add-file-download` | `design.md` line 92 (MCP status objects of `web_download_file`) and its MCP test tasks | Written against FastMCP 4: tool tests use `Client(mode="legacy")` where they assert session behaviour, and no camelCase field read (D8, D9) |
| `add-keycloak-login` (moved from `add-auth-and-identity` on 2026-10-04) | its `design.md` D6 and its task 4.2 (the FastMCP auth hook on the library's sample service) | The MCP token check is written against FastMCP 4's `auth` or middleware API and must hold for both protocol eras: a sessionless 2026-07-28 request carries the bearer token on every request, a handshake session carries it on each HTTP request of the session |
| `add-observability` | `proposal.md` line 57 and its Python tracing tasks | FastAPI's built-in telemetry stays off (D4), and MCP spans from FastMCP and the MCP SDK are children of the library's HTTP server span (D5). No Python dashboard may count FastMCP's MCP SERVER spans as HTTP requests |
| `add-ascend-python-common` | `design.md` D6 (the settings base) | A note that this change adds `MCP_ALLOWED_HOST_HEADERS` to `ServiceSettings`, with its per service default (D10, owner answer 61.2). Made on 2026-10-03 |
| `add-self-built-integrations` | `design.md` line 33 (says ascend-ocr pins FastMCP 3.3.1) and line 89 | After this change every Python service pins FastMCP 4.0.10 through the library. The runtime image it builds pins the FastMCP version current when its task 4.1 runs, which this change does not constrain |

### Affected files

Library: `libs/ascend-python-common/pyproject.toml`, `src/ascend_python_common/app.py`, `settings.py` (`MCP_ALLOWED_HOST_HEADERS`, D10), `request_context.py`, `tracing.py`, `rate_limit.py`, `errors/mcp.py`, `tests/**`, `README.md`, `CHANGELOG.md`.

Per service (`apps/<service>/`): `pyproject.toml` (library pin), `tests/**` that use `fastmcp.Client` or read MCP model fields (today only ascend-ocr's `tests/api/mcp/test_request_log_context.py` and `tests/test_main.py` import `mcp` or `fastmcp` client types, read with `git grep` on 2026-10-03, and `add-ascend-python-common` moves part of them into the library), `AGENTS.md`, `CHANGELOG.md`. Service `src/**` only where a test finds a version-dependent defect.

Repository: `AGENTS.md` (only where it names a version), `.env.example`, `apps/ascend-web-hunter/deploy-standalone/.env.example` and `apps/ascend-web-hunter/deploy-standalone/README.md` (the `MCP_ALLOWED_HOST_HEADERS` setting of D10, sync rule), `compose.yaml`, `compose.ascend-web-hunter.yaml` and `apps/ascend-web-hunter/deploy-standalone/compose.yaml` (one `MCP_ALLOWED_HOST_HEADERS` line per service, D10, owner rule 98 of 2026-10-08), the configuration reference (`apps/ascend-memory/docs/CONFIGURATION.md`, `apps/ascend-ocr/docs/CONFIGURATION.md`, `apps/ascend-web-hunter/docs/configuration.md` and, for ascend-audio-scribe, `docs/CONFIGURATION.md`), `docs/architecture/decisions/ADR-M013-python-runtime-upgrade.md`, `docs/architecture/decisions/README.md`. Not affected: every `Dockerfile`, `.github/workflows/**`, `contracts/pacts/**`, the agent's code.

## Risks / Trade-offs

- [slowapi or the Prometheus instrumentator loses the route under FastAPI's router tree, so a stricter limit silently stops applying or every request gets one `handler` label] → Tests first (D3), on both versions, and the library's own lookup if they fail.
- [The Host and Origin check refuses a real caller that uses another host name, such as a remote caller of the standalone ascend-web-hunter or a container alias] → The default holds every name the repository uses today (D10), the setting is documented in both `.env.example` files and the standalone README, and task 7.1 checks every service with the agent's own host name and with `localhost`.
- [FastAPI's telemetry adds a second exporter to the compose OTLP endpoint, or writes exception text to OpenTelemetry logs] → Configured off in the factory (D4), proven by a test that counts exporters and log records.
- [A raw or made-up MCP session id reaches a log line or a span on sessionless requests] → D5 and D6, tests in both eras.
- [The Java client and a Python server stop agreeing on the protocol version] → D12 runs today's agent MCP tests and a live tool listing before the change is called done. MCP SDK 2 keeps 2025-06-18 (today's agent) and 2025-11-25 (the agent after `upgrade-spring-boot-4`) in its handshake list, and `upgrade-spring-boot-4` repeats the check after its upgrade.
- [A third-party package emits a new deprecation warning under warnings as errors] → Fixed at its cause where the code is ours, a narrow ignore naming the third-party module only where it is not, each listed in the changelog (D13).
- [The upgrade commit is large] → The preparation commits take every version-neutral part out of it (D2), and its review follows the library, then each service.
- [FastMCP 4 is about one month old (4.0.0 on 2026-08-31) and has had ten patch releases] → The exact pin keeps every build on 4.0.10. A later patch is a deliberate version set change with its own changelog entry.
- [FastMCP's middleware now sees unroutable messages] → D6 tests send them through every library middleware.

## Migration Plan

1. Group 1: the library's tests for the new spec on the old versions.
2. Groups 2 to 5: one preparation group per service on the old versions (ascend-memory, ascend-audio-scribe, ascend-web-hunter, ascend-ocr, the order of `add-ascend-python-common` D16), each green on its gate and committed alone once the owner says to commit.
3. Group 6: the upgrade commit (D2), with all five gates and the Pact provider verification green.
4. Group 7: images rebuilt and checked, the agent check (D12).
5. Group 8: the e2e run the owner chooses.
6. Rollback: revert the upgrade commit, reinstall the library and each service into its `.venv` from the reverted files, rebuild the four images. The preparation commits stay. No data migration: the project is under development and nothing these versions read is stored. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

## Owner decisions of 2026-10-06

Answer 73.1: the data that exists today in the development database, Redis, Qdrant, object storage and AscendMemory is disposable. No change converts it, backfills it or depends on it, and any change may start from empty stores. No Python service stores state these versions read, so this change needs none of today's data.

## Owner decisions of 2026-10-08

- Item 18 of the review of 2026-10-07, approved by the owner on 2026-10-08: the proposal no longer says that `python-service-platform` is missing from `openspec/specs/`. It states the real reason this change has no MODIFIED delta: `add-ascend-python-common` lands and is archived first, no requirement of `python-service-platform` changes, and every rule this change adds is new and lives in `python-mcp-runtime`.
- Owner decision of 2026-10-08, "one named version per change, in build order": task 6.11 no longer bumps each service's patch version without a number. It names ascend-memory 0.1.5, ascend-audio-scribe 0.9.5, ascend-web-hunter 0.0.8 and ascend-ocr 0.3.2, one patch step after the versions of `add-ascend-python-common` (D15).

Answer 85.1: every key and secret lives in the repository `.env`, never in a shell. No task of this change exports a key or sets any value in a shell.

Answer 94.2: every Python MCP server runs FastMCP in stateless HTTP mode, so any container can answer any MCP request. D10 now passes `stateless_http=True` instead of `False`, the cited FastMCP documentation is in `add-ascend-python-common` D12, task 6.5 checks the setting on 4.0.10 and task 10.1 expects no `mcp-session-id` in a handshake answer. No tool may rely on a message the server sends to the agent between requests. This settles the open point of answer 87 below.

Answer 87 (rule R1): several containers of one service run at once. This change moves no state into a container's memory. The rate limit windows keep the storage that `add-ascend-python-common` D9 gives them (Redis for ascend-web-hunter), and the library's FastMCP middlewares keep using it on the new versions. D10 sets `stateless_http=False` explicitly, so FastMCP 4 keeps each MCP session in the memory of the container that created it, as FastMCP 3 does today. A session-based client whose calls reach another container than the one that created its session is then not served, while a sessionless 2026-07-28 client needs no session and is served by any container. Whether a service that runs as several containers gets session affinity at the address in front of them or FastMCP's stateless HTTP mode is an open owner decision, listed in the worker report of 2026-10-08 and in the Risks of `add-ascend-python-common`. This change does not decide it.

Answer 89.14: tracing exports whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is set, and OpenTelemetry's standard `OTEL_SDK_DISABLED=true` switches it off, with no custom `OTEL_ENABLED` (`add-ascend-python-common` D10). This changes D4 (FastAPI's own telemetry would add a second exporter beside the library's), D5, the Risks line on FastAPI's telemetry, the requirement "One trace per request and one exporter" with its scenarios, and tasks 1.3 and 6.3, which now test with `OTEL_SDK_DISABLED=true` in place of `OTEL_ENABLED=false`.

Answer 91.3: end-to-end specs that only repeat what lower tests prove are dropped. Task 10.4, the AI-run spec through the agent, is removed, because task 7.3 already checks that the agent lists the tools of all four services after the upgrade. The separate `mcp-runtime` spec per suite is not written: its requests extend in place the platform contract spec of `add-ascend-python-common` task 9.4, the one deterministic library spec per suite, and replace that spec's `mcp-initialize.yml`, so no behaviour is checked twice (review item B12, tasks 10.1 to 10.3, 10.5 and 10.6).

Answer 93: small simplifications that cut no feature. The candidate table row of task 10.8 is removed with the table of `add-github-actions-pipeline` task 7.3 (review item C4). `mcp.session.id` is dropped once, by the one span processor of `add-ascend-python-common` D10, from every span, in place of a conditional processor here plus the digest exporter wrapper (review item C10, D5, task 6.4). The accepted loss is grouping spans by MCP session in Tempo. Not applied, because it would remove a behaviour the owner asked for (rule R3): the Host header allow list `MCP_ALLOWED_HOST_HEADERS` of D10 (review item C9, owner answers 61.2 and 62).

Answer 98: owner rule 98 of 2026-10-08, every value with a default is a setting, applied in D10. The one setting this change adds, `MCP_ALLOWED_HOST_HEADERS`, already had a code default per service (`<compose service name>,localhost,127.0.0.1`). It now also gets a compose line `${VAR:-default}` on each of the four services, with the interpolation names `MEMORY_MCP_ALLOWED_HOST_HEADERS`, `AUDIO_SCRIBE_MCP_ALLOWED_HOST_HEADERS`, `WEB_HUNTER_MCP_ALLOWED_HOST_HEADERS` and `OCR_MCP_ALLOWED_HOST_HEADERS` (new names, in the form of `add-ascend-python-common` D26), the ascend-web-hunter line in the standalone bundle too under its sync rule (task 6.13), and one row per service in the configuration reference (task 6.14). Kept as constants, because they are not operational: `stateless_http=True` (owner answer 94.2, the mode that lets any container answer any MCP request, so a setting could break several containers), `json_response=False` (wire format), `host_origin_protection=True` and the empty `allowed_origins` (the security rule of owner answer 61.2, the services serve no browser), `session_idle_timeout=None` (no session exists in stateless mode, so it has no effect), the five FastAPI `telemetry` keys, all off (D4, owner answer 61.1), the package versions of D1 (build inputs, not runtime values), the protocol versions (protocol), and the test-only values (the 5 MiB test body, `mcp_camelcase_compat = False` in the test fixtures, `attacker.example`, `search-box`). The 4 MiB request body limit stays the fixed value of MCP SDK 2.3.0, because FastMCP 4.0.10 offers no way to pass it (D10, read in the released wheels on 2026-10-09). This change plans no module constant of round 93. No plan of this change uses LM Studio as a default in a test or a measurement, none uses the old `e2e` profile or overlay mount, and none says that running several copies in production is planned elsewhere. The paragraph "Answer 87" above is history: its open point about session affinity is settled by answer 94.2.

## Open Questions

Questions 1 and 2 were closed by the owner on 2026-10-03 and question 3 on 2026-10-04. They are kept here with their answers, so the numbers other text cites stay valid. No question is open.

1. Closed (owner answer 61.1): no switch to FastAPI's built-in telemetry now. The library keeps its own tracing setup, and FastAPI's telemetry stays configured off (D4).
2. Closed (owner answer 61.2): FastMCP's Host and Origin header check is on, with an allow list of the container names configured in the library through the setting `MCP_ALLOWED_HOST_HEADERS`, whose default per service is its compose service name plus `localhost` and `127.0.0.1` (D10).
3. Closed (owner answer 62 of 2026-10-04): the setting name `MCP_ALLOWED_HOST_HEADERS` is approved. The documentation explains it side by side with `ALLOWED_PRIVATE_HOSTS`, which names the outbound hosts of the URI fetch guard (D10, D14, task 6.12).
