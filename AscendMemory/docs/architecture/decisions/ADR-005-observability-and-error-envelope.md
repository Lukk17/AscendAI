# ADR-005: Liveness / Readiness Split, RFC 7807 Errors, Prometheus `/metrics`

**Date**: 2026-06-01
**Status**: Accepted
**Deciders**: Łukasz Sarna

---

## Context

The previous design had one `/health` endpoint that doubled as liveness and readiness. It returned 503 during the
Qdrant warmup window. Kubernetes (and Docker `HEALTHCHECK` with a too-short `start_period`) read 503 as "restart the
container," so the service would loop on cold boot. The service also returned ad-hoc `{"error": "..."}` JSON for
failures, leaking upstream messages (mem0 stack traces, Qdrant DSNs) verbatim to the caller. There was no Prometheus
endpoint, so latency and error-rate were invisible to the platform's observability stack.

---

## Decision

Three coordinated changes, shipped together because they share consumers.

**Liveness and readiness are separate endpoints.** `/health` returns 200 the moment uvicorn binds and stays 200 for
the life of the process. `/ready` actively probes Qdrant, the default embedding API, and constructs the mem0 client.
It returns 200 when every probe is ok, 503 otherwise. The legacy combined contract stays available at
`/health/legacy` for callers still on the old shape, with a `Deprecation` and `Sunset` header (informally documented
here; not yet emitted programmatically). The Docker `HEALTHCHECK` and `docker-compose` healthcheck both target
`/health`, never `/ready`, because the container is "alive" the moment the process can respond. Orchestrators that
want readiness should call `/ready` directly. (`src/main.py`, `src/api/readiness.py`)

**Error responses use RFC 7807 problem documents.** A `ValueError` raised anywhere in the request lifecycle maps to
`400 application/problem+json` with `type`, `title`, `status`, `detail`, `instance`. Unhandled exceptions map to
`500 application/problem+json` with the same envelope, but `detail` is dropped server-side so upstream stack traces
never reach the caller. The full exception is logged with `logger.exception` for observability. The MCP surface
returns a structured envelope (`{status: "error", code: "validation_error" | "internal_error", operation, message}`)
because MCP tool results are JSON, not HTTP. (`src/api/exception_handlers.py`, `src/api/mcp/mcp_server.py`)

**`/metrics` exposes Prometheus counters and histograms.** Four counters (`memory_insert_total`,
`memory_search_total`, `memory_delete_total`, `memory_wipe_total`) labelled by `provider` and `outcome`, plus four
histograms (`memory_*_duration_seconds`) labelled by `provider` with operation-tuned buckets. The endpoint is
unauthenticated because the service runs behind the AscendAgent in a private network and the registered scrapers all
share that network. (`src/observability/metrics.py`, `src/main.py`)

**`X-Request-ID` middleware** echoes any caller-supplied request ID (regex-validated, max 128 chars) back on every
response, and generates a UUID4 when no header is sent or the value is malformed (CR/LF injection guard). The ID is
stored in a `contextvars.ContextVar` and threaded into every log line via the `CorrelationFilter` so logs from a
single request can be reassembled from log aggregation. (`src/observability/request_context.py`,
`src/config/logging_config.py`)

---

## Alternatives Considered

### Alternative 1: Keep the single `/health` endpoint, increase Docker `start_period`

- **Pros**: One less endpoint to document.
- **Cons**: Conflates two operationally distinct concepts. The Kubernetes liveness probe needs to fire fast (every
  10 s typically) to detect a wedged process; readiness probes can run slower (every 30 s) and check expensive
  upstreams. Sharing the endpoint forces the slowest probe to set the cadence.
- **Why not**: The two probes have different consumers (kubelet vs Service load balancer) and different failure
  semantics (kill vs drop from rotation).

### Alternative 2: Return ad-hoc JSON for errors with full stack traces in dev

- **Pros**: Easier to debug locally.
- **Cons**: Production leaks (file paths, package versions, DSNs) become a recurring incident pattern; dev/prod
  divergence introduces "works on my machine" surface area.
- **Why not**: Errors should be redacted by default, with full diagnostics in logs. RFC 7807 is the industry-standard
  shape and gives consistent client behaviour.

### Alternative 3: OpenTelemetry traces instead of Prometheus metrics

- **Pros**: Traces give per-request causality; metrics give aggregate-only.
- **Cons**: The platform's existing observability layer (Grafana + Prometheus + Loki) is metric-and-log centric. OTel
  traces would require adding Tempo and re-instrumenting other services.
- **Why not**: Prometheus is the cheaper, already-deployed answer. OTel can be added later as a separate decision.

---

## Consequences

### Positive

- Kubernetes / Docker treat the cold-boot window correctly. No restart loops.
- Error responses are uniform across REST and MCP; clients can switch on `type` / `code`.
- Per-provider latency histograms surface "is OpenAI slower than LM Studio today?" without ad-hoc logging.
- Request correlation across logs becomes trivial: filter Loki on `request_id="..."`.

### Negative

- Two probe endpoints to keep working. CI must hit both, and the legacy `/health/legacy` path must be removed on a
  defined schedule.
- Per-provider labels on Prometheus counters create cardinality (3 providers × 3 outcomes × 4 counters = 36 series).
  Acceptable today; revisit if the provider list grows past ~20.

### Risks

- **`/ready` probe blocks**: Each probe has a 3 s budget; total worst-case latency is ~9 s. If a load balancer's
  health-check timeout is shorter than that, the service flaps. Document the budget in the deployment guide.
- **`X-Request-ID` reflection without validation could enable response splitting**: Mitigated by the regex
  `^[A-Za-z0-9._-]{1,128}$` and a fallback to UUID4 on mismatch.
