# 8. Crosscutting Concepts

---

### Liveness, readiness, and the warmup gate

`/health` is liveness: always 200 once uvicorn binds. The Docker `HEALTHCHECK` and compose healthcheck both target
it. `/ready` is readiness: it actively probes Qdrant `/healthz`, the default embedding API `/models`, and constructs
the mem0 client (which fails fast on a missing API key). It returns 200 only when every probe is ok, 503 otherwise.
A combined-shape `/health/legacy` endpoint preserves the pre-split contract (503 during warmup, 200 after) for older
callers.

The `is_ready` global flag in `src/main.py` continues to drive `/health/legacy`. It starts `False`, flips to `True`
after a background `warmup_client` task successfully calls `client.search("startup_warmup", "system_warmup")`. The
warmup retries 60 × 5 s (5-minute cold-boot budget); if every attempt fails, `is_ready` stays `False` and the legacy
endpoint never returns 200 until the process restarts.

(`src/main.py`, `src/api/readiness.py`)

---

### Logging and request correlation

All log lines begin with `[AscendMemory]` and carry a `[request_id]` slot. The format is set by
`CenteredLevelFormatter` in `src/config/logging_config.py`. Level names are padded to 8 characters. `colorlog`
provides colour on TTYs. The uvicorn loggers use the same formatter via the dict returned by
`get_uvicorn_log_config()`.

`RequestIdMiddleware` echoes any caller-supplied `X-Request-ID` (regex-validated, max 128 chars) back on every
response. A malformed header or no header at all results in a fresh UUID4. The value is stored in a
`contextvars.ContextVar` and injected into every log record via `CorrelationFilter`, so all logs for a request can be
reassembled from a single Loki filter.

(`src/observability/request_context.py`, `src/config/logging_config.py`)

---

### Metrics

`/metrics` exposes a Prometheus payload. Four counters (`memory_insert_total`, `memory_search_total`,
`memory_delete_total`, `memory_wipe_total`) carry `provider` and `outcome` labels. Four histograms
(`memory_*_duration_seconds`) carry the `provider` label with operation-tuned buckets (insert covers 0.1-60 s, search
covers 0.05-30 s, delete covers 0.05-5 s, wipe covers 0.5-120 s).

The endpoint is unauthenticated; it is reachable only from the platform's private network.

(`src/observability/metrics.py`, `src/main.py`)

---

### Provider singletons

`get_memory_client(provider)` returns a cached `AscendMemoryClient` per provider name. The cache is a module-level
dict `_client_instances` in `src/service/memory_client.py`. The first call for a given provider constructs a new
instance (expensive: LLM client init, Qdrant collection check); subsequent calls return the cached instance. A
`threading.Lock` guards the check-then-set so two concurrent first-hit requests for the same provider can't both
construct an `AscendMemoryClient` (which would open redundant Qdrant + LLM connections). Inside the lock the cache
is re-checked, so the loser of the race returns the cached instance constructed by the winner.

(`src/service/memory_client.py`)

---

### MCP mount order

The MCP ASGI app must be mounted last in the FastAPI app. Any route registered after `app.mount("/", mcp_asgi_app)`
would be shadowed by the catch-all mount. The REST router and `/health` are registered before the mount.

(`src/main.py:75-93`)

---

### LM Studio LLM backend (native, no monkey-patch)

mem0ai 2.x ships a native `lmstudio` LLM provider that knows the `response_format` quirks of LM Studio (some models
reject `{"type": "json_object"}`). The service selects it by setting `llm.provider="lmstudio"` with
`lmstudio_base_url` in the mem0 config for the `lmstudio` provider entry. The `openai` and `gemini` provider entries
use `llm.provider="openai"` with `openai_base_url`.

This replaces the prior monkey-patch on `OpenAILLM.generate_response` and removes the runtime dependency on a private
mem0 method. See [ADR-006](../decisions/ADR-006-mem0ai-2x-upgrade.md).

(`src/service/memory_client.py`, `src/config/config.py`)

---

### Error handling (RFC 7807)

Errors use [RFC 7807](https://www.rfc-editor.org/rfc/rfc7807) problem documents with
`Content-Type: application/problem+json`. `ValueError` raised anywhere in the request lifecycle (unknown provider,
missing API key, empty text, schema violation in the service layer) maps to `400` with `detail` carrying the
service-authored message. Unhandled exceptions map to `500` with `detail` omitted — only the request path is
surfaced — so upstream stack traces and DSNs never reach the caller. The full exception is logged with
`logger.exception` and correlated by `X-Request-ID`.

`AscendMemoryClient.search` re-raises upstream failures (was previously swallowed and returned `[]`); the global
handler maps them to 500 problem documents. This makes Qdrant outages observable end-to-end instead of disguising
them as empty result sets.

The MCP tools wrap each call in a try/except and return a structured envelope:
`{"status": "error", "code": "validation_error" | "internal_error", "operation": "...", "message": "..."}`. MCP tool
results are JSON, so this is the MCP equivalent of an HTTP status code split.

(`src/api/exception_handlers.py`, `src/api/mcp/mcp_server.py`, `src/service/memory_client.py`)

---

### Embedding provider consistency

Once memories are stored with a given provider's embedding model, they must be searched with the same provider (same
model, same dimensions, same Qdrant collection). If a caller uses `provider=lmstudio` to insert and `provider=openai`
to search, the search hits the `ascend_memory_1536` collection which contains no `lmstudio` memories. The service
does not detect or warn about this mismatch.

(`src/config/config.py:10-31`, `docs/CONFIGURATION.md`)
