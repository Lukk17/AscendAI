# ADR-M013: Python Runtime Upgrade (FastAPI 0.147, FastMCP 4.1, MCP SDK 2.3)

---

### Status

Accepted (2026-10-19)

---

### Context

The four Python services (ascend-audio-scribe, ascend-web-hunter, ascend-memory, ascend-ocr) share one framework version set in `libs/ascend-python-common` (see [ADR-M012](ADR-M012-shared-python-library.md)). The set moved to FastAPI 0.147.0, Starlette 1.9.0, uvicorn 0.54.0, FastMCP 4.1.1, MCP SDK 2.3.0 and httpx2 2.14.0 (owner pin 2026-10-19). Three framework behaviors of the new versions tempted a redesign, and this record fixes the chosen answers so a later reader does not undo them.

---

### Decision

1. FastAPI's built-in OpenTelemetry stays switched off. `create_service_app` builds the app with `telemetry={"tracing": False, "metrics": False, "logs": False, "operation_spans": False, "auto_configure": False}`. The library keeps its own trace path: the OpenTelemetry ASGI middleware outside the whole Starlette stack, so the server span is still open when `ServerErrorMiddleware` builds the 500 body that carries the trace id, and exactly one exporter (the library's) sends whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is set. FastAPI 0.147 would otherwise add a second request span, a second exporter from the environment, and exception messages with stack traces in OpenTelemetry logs.

2. MCP spans keep one processor and no condition. `add-ascend-python-common` drops `mcp.session.id` from every span at span start. FastMCP 4.1 re-adds the attribute after span start when it enriches its server span, so the same value is also scrubbed on the way out by the export-time wrapper in `tracing.py`. No new span processor and no conditional logic were added. Grouping spans by MCP session in Tempo is accepted as lost; the raw and made-up session ids stay out of every log line and every span.

3. The MCP transport settings are explicit and the Host and Origin check is on. `http_app` is called with `stateless_http=True` (any container answers any MCP request, no tool relies on a server-to-client message between requests), `json_response=False`, `session_idle_timeout=None`, `host_origin_protection=True`, explicit `allowed_hosts` and an empty `allowed_origins`. The allow list is the new `MCP_ALLOWED_HOST_HEADERS` setting (inbound: which `Host` values `/mcp` accepts, read by all four services, default per service: its compose service name, `localhost`, `127.0.0.1`). It sits beside `ALLOWED_PRIVATE_HOSTS` (outbound: which hosts the URI fetch guard may reach at a private address); one does not replace the other. A refused `Host` answers 421, a refused `Origin` answers 403, REST routes are never checked.

The operating details are in the [2.0.0 entry of the library changelog](../../../libs/ascend-python-common/CHANGELOG.md) and the full design in [openspec/changes/add-python-runtime-upgrades/design.md](../../../openspec/changes/add-python-runtime-upgrades/design.md).

---

### Alternatives Considered

#### Alternative 1: Adopt FastAPI's built-in telemetry and drop the library's ASGI middleware

- Pros: One less instrumentation layer, framework-native spans and metrics.
- Cons: The request span no longer starts outside `ServerErrorMiddleware`, FastAPI adds its own exporters from the environment beside the library's, and exception texts land in OpenTelemetry logs.
- Why not: The library's trace id in error bodies and the single-exporter rule (owner decision 89.14) both break.

#### Alternative 2: A conditional span processor or a digest exporter wrapper for the session id

- Pros: Keeps the drop logic next to the tracing setup.
- Cons: A second processor with a condition per era, plus a wrapper that replaces the exporter, for one attribute.
- Why not: Owner decision 93 settled this: one unconditional processor, extended with an unconditional export-time scrub when FastMCP 4.1 proved the start-time drop insufficient.

#### Alternative 3: Session affinity or a stateful MCP transport instead of stateless HTTP mode

- Pros: The server could keep per-session state in memory.
- Cons: Any container must then answer every request of a session, which the multi-container rollout cannot promise without affinity at the address in front.
- Why not: Owner answer 94.2 settled this: stateless HTTP mode, no tool relies on a server-to-client message between requests.

---

### Consequences

- Positive: One HTTP server span per request and one exporter, on every framework version the set names.
- Positive: No MCP session id, raw or as a digest, in any log line or span, in both the handshake era and the sessionless 2026-07-28 era.
- Positive: DNS-rebinding protection on `/mcp` in every service with no code change per service beyond the setting default.
- Negative: FastAPI telemetry improvements (its metrics, its operation spans) stay unused until a later change deliberately adopts them.
- Negative: MCP spans can no longer be grouped by session in Tempo.
