# 8. Crosscutting Concepts

---

### Liveness, readiness, and the warmup gate

`/health` is liveness: always 200 with `{"status": "ok", "service": "ascend-memory", "version": ...}` once uvicorn
binds. The Docker `HEALTHCHECK` and compose healthcheck both target it. `/ready` is readiness: it actively probes
Qdrant `/healthz`, the default embedding API `/models`, and constructs the mem0 client (which fails fast on a
missing API key). Probes run at once with a 3 s budget each through the `ascend-python-common` readiness
aggregator. It returns 200 `{"status": "ready", ...}` when every probe is ok or skipped, else 503 `{"status":
"not-ready", ...}` with the same body shape (`service`, `version`, `checks`).
A combined-shape `/health/legacy` endpoint preserves the pre-split contract (503 during warmup, 200 after) for older
callers.

The `is_ready` global flag in `src/main.py` continues to drive `/health/legacy`. It starts `False`, flips to `True`
after a background `warmup_client` task successfully calls `client.search("startup_warmup", "system_warmup")`. The
warmup retries 60 × 5 s (5-minute cold-boot budget); if every attempt fails, `is_ready` stays `False` and the legacy
endpoint never returns 200 until the process restarts. The warmup task runs as the service lifespan inside
`create_service_app`.

(`src/main.py`, `src/api/readiness.py`)

---

### Logging and request correlation

All log lines begin with `[ascend-memory]` and carry the request id. Logging comes from `ascend-python-common`
(`configure_logging`): `LOG_LEVEL` is honoured on the root handler, `LOG_FORMAT` selects `json` (containers) or
`color` (local runs), and the uvicorn and fastmcp loggers propagate through the root handler. There is no service
`logging_config.py`.

The library's pure ASGI correlation middleware echoes any caller-supplied `X-Request-ID` (regex-validated, max 128
chars) back on every response. A malformed header or no header at all results in a fresh UUID4. The value is stored
in a `contextvars.ContextVar` and injected into every log record, so all logs for a request can be reassembled from
a single Loki filter.

(`ascend-python-common` `log_config.py` and `request_context.py`, wired by `create_service_app` in `src/main.py`)

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

The MCP app is attached by `create_service_app` at the `/mcp` path only. Every other path reaches the FastAPI
router, so an unknown path answers the problem 404 and a wrong method the problem 405 instead of the MCP app's
plain-text 404.

(`src/main.py`, `src/api/mcp/mcp_server.py`)

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
`Content-Type: application/problem+json`, built by the `ascend-python-common` problem builder. Every body carries
`type`, `title`, `status`, `detail`, `instance`, `code`, and `traceId` (32 lower case hex characters).
`ValueError` raised anywhere in the request lifecycle (unknown provider, missing API key, empty text, schema
violation in the service layer) maps to `400` with code `validation` and the service-authored message in `detail`.
A request the router cannot validate answers `400` with code `validation` and an `errors` array sorted by `field`
(each entry has `field` and `message`). Unhandled exceptions map to `500` with code `internal` and a fixed generic
detail, so upstream stack traces and DSNs never reach the caller. The full exception is logged with
`logger.exception` and correlated by `X-Request-ID` and `traceId`.

`AscendMemoryClient.search` re-raises upstream failures (was previously swallowed and returned `[]`); the global
handler maps them to 500 problem documents. This makes Qdrant outages observable end-to-end instead of disguising
them as empty result sets.

The MCP tools raise registered exceptions and map them to tool errors whose text starts with the registry code
(`validation: ...`, `internal: ...` with the fixed detail). MCP tool results are JSON, so this is the MCP
equivalent of an HTTP status code split.

(`src/api/exception_handlers.py`, `src/api/mcp/mcp_server.py`, `src/service/memory_client.py`)

---

### Embedding provider consistency

Once memories are stored with a given provider's embedding model, they must be searched with the same provider (same
model, same dimensions, same Qdrant collection). If a caller uses `provider=lmstudio` to insert and `provider=openai`
to search, the search hits the `ascend_memory_1536` collection which contains no `lmstudio` memories. The service
does not detect or warn about this mismatch.

(`src/config/config.py:10-31`, `docs/CONFIGURATION.md`)
