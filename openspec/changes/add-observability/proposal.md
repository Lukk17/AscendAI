## Why

AscendAI today is observable only via stdout logs. There are no counters, no histograms, no scrape endpoints, no dashboards, no traces, no centralised log search. When something misbehaves — Mem0 extraction fails to parse JSON, RAG retrieval misses, an MCP tool times out, an LLM provider rate-limits — the only signal is a WARN line that someone has to be `grep`-ing for in real time across multiple `docker logs` streams. Three concrete consequences:

1. **Bug-1 (the semantic memory parse failure that triggered the `fix-ascend-agent-bugs` change) was visible for an unknown amount of time before being noticed.** A `memory.extraction.parse_failed` counter on a Grafana dashboard would have surfaced it within minutes of the first occurrence.
2. **No way to alert on degradation.** Provider-switch effects, RAG misses spiking after a re-ingest, cache-hit ratio collapsing — none of these can trigger a webhook because there's no metric to threshold.
3. **No baseline for performance work.** "Is RAG retrieval slow?" / "Where in a single chat turn is the latency hiding?" / "How many tokens per turn does each provider use, and what is that costing per day?" — none of these can be answered without instrumenting first.

Spring Boot already ships Micrometer. Spring AI 1.1 auto-instruments token usage, model-call latency, and tool-call counts via OpenTelemetry when Actuator is on the classpath. The Python services have equally lightweight `prometheus-fastapi-instrumentator` for metrics and `opentelemetry-distro` for traces. We are leaving 80% of observability on the table by not wiring these up.

## What Changes

This change wires a full observability layer into the AscendAI stack: **metrics, logs, and traces in one go**, plus a curated set of dashboards that target the failure modes the recent bug investigations exposed and validate the just-shipped prompt-caching savings.

**Metrics layer (Prometheus + Grafana):**

- **AscendAgent (Spring Boot)**: add `spring-boot-starter-actuator` and `micrometer-registry-prometheus` dependencies. Expose `/actuator/health`, `/actuator/prometheus`, `/actuator/info`. Auto-pick-up Spring AI's `gen_ai.*` metrics. Add custom counters/timers/gauges for the failure modes we have already paid for once: memory extraction parse failures, memory insert failures, RAG retrieval thresholding outcomes, ingestion errors per source type, MCP tool latency. Add cache-token metrics emitted from the prompt-caching strategies so the L3 dashboard works.
- **WeatherMCP (Spring Boot)**: same Actuator + Prometheus stack, expose `/actuator/prometheus`. Minimal custom metrics (tool-call counter is enough for an MCP server).
- **Python services (AudioScribe, AscendWebSearch, AscendMemory, PaddleOCR)**: add `prometheus-fastapi-instrumentator` to FastAPI apps and expose `/metrics`. Add a small set of custom domain counters per service (transcription duration, search-result count, memory-search latency, OCR pages-processed).
- **Prometheus**: new docker-compose service `prometheus` with a checked-in `observability/prometheus/prometheus.yaml` that scrapes all six AscendAI services on their `/metrics` (or `/actuator/prometheus`) endpoints every 15 s, plus the data-layer prerequisites (Qdrant native, Redis via `redis_exporter`, Postgres via `postgres_exporter`, MinIO native).
- **Grafana**: new docker-compose service `grafana` with anonymous read-only access on a non-conflicting port (`3030` to avoid clashing with anything), provisioned with the Prometheus datasource, the Loki datasource (logs), the Tempo datasource (traces), and **six checked-in dashboards** (see below).

**Logs layer (Vector + Loki):**

- **Vector** container — ships Docker container stdout/stderr to Loki via the `docker_logs` source. **Zero code change in services** — they just need to write to stdout (which they already do).
- **Loki** container — log storage backend, single-binary mode, filesystem-backed. Queryable via Grafana's Logs panel alongside metrics on the same dashboards.
- **Vector chosen over Promtail** because Vector is vendor-neutral: a future migration to Datadog / CloudWatch / Splunk is a `vector.toml` change, services untouched. Promtail is Loki-only and would force a shipper swap on migration.

**Traces layer (OTel collector + Tempo):**

- **OpenTelemetry Collector** container — single OTLP ingestion point (gRPC `:4317` and HTTP `:4318`). Receivers: OTLP. Processors: batch, memory_limiter. Exporters: Tempo. Future Datadog / Jaeger fan-out lives here without service changes.
- **Tempo** container — trace storage backend, single-binary mode, filesystem-backed.
- **AscendAgent + WeatherMCP** — Spring AI 1.1's auto-instrumentation already emits OpenTelemetry spans for every LLM call, tool call, and embedding call. Wire them at `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`.
- **Python services** — add `opentelemetry-distro` + `opentelemetry-exporter-otlp` to `pyproject.toml`. One-line `auto_instrumentation` activation at app startup.
- **Why OTel over a vendor agent**: Spring AI emits OTel natively; OTel collector is the industry-standard router for fan-out to any backend.

**Six checked-in dashboards** (provisioned in Grafana at startup):

1. **Platform Overview** — request rate, error rate, latency, JVM/Python memory per service.
2. **AI Pipeline** — tokens per minute by provider/model, provider mix, RAG hit rate, memory parse-failure rate, MCP tool latency.
3. **Infrastructure** — Qdrant collection sizes, Redis cache stats, Postgres connections, MinIO bucket sizes.
4. **L1 — Token Cost** — per-provider $/day panel; data = `gen_ai.client.token.usage{provider="..."}` × per-provider rate (rates committed in a YAML pricing table inside `observability/grafana/dashboards/`).
5. **L2 — RAG Quality** — top-K similarity-score histogram, retrieval miss-rate over time, ingestion-events-per-hour by source type.
6. **L3 — Cache Hit Rate** — `cached_tokens / prompt_tokens` per provider, plus absolute saved-token count. Validates the prompt-caching change is actually firing in production.

**Documentation**: a new `docs/OBSERVABILITY.md` walks through what is collected (metrics + logs + traces), how to find it in Grafana, and how to add a custom metric, log field, or span. Cross-link from the root README "Documentation" section.

**Defaults**: observability stack runs **always-on** in `docker-compose.yaml`. The earlier draft included a `--profile no-observability` opt-out; user dropped it as out of scope. The actuator endpoints on the JVM services are bound to localhost-only by default; remote exposure requires an explicit env var.

## Capabilities

### New Capabilities

- `service-metrics` — every AscendAI service emits a uniform Prometheus-format metrics endpoint with framework-default metrics plus a defined minimum set of domain counters/timers, plus auto-instrumented OpenTelemetry spans.
- `observability-stack` — Prometheus + Grafana + Vector + Loki + OTel collector + Tempo run in `docker-compose.yaml` with checked-in scrape config, Vector sources/sinks, OTel collector pipeline, and six provisioned Grafana dashboards (Platform Overview, AI Pipeline, Infrastructure, Token Cost, RAG Quality, Cache Hit Rate).

### Modified Capabilities

(none — this change is additive)

## Impact

- **New runtime services** (eight new compose containers): `prometheus` (`:9090`), `grafana` (`:3030`), `vector`, `loki` (`:3100` internal), `otel-collector` (`:4317`/`:4318` internal), `tempo` (`:3200` internal), `postgres-exporter`, `redis-exporter`. Combined RAM footprint at idle: ~600 MB.
- **New code (AscendAgent)**:
  - `AscendAgent/build.gradle.kts` — actuator + micrometer-prometheus + opentelemetry-exporter-otlp dependency lines.
  - `AscendAgent/src/main/resources/application.yaml` — `management.endpoints.*`, `management.metrics.*` block; `OTEL_*` env defaults.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/MetricsConfig.java` — central `MeterRegistry` customizer, common tags (`service`, `instance`, `version`).
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryExtractor.java` — increment `memory.extraction.parse_failed`.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryClient.java` — increment `memory.insert.failed`, time `memory.search.duration`.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/RagRetrievalService.java` — counter `rag.hits.above_threshold`, gauge `rag.last_top_score`, histogram `rag.top_score` (for L2 dashboard).
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/ChatExecutor.java` — timer `mcp.tool.duration` keyed by tool name.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/AnthropicPromptCacheStrategy.java` — counter `prompt_cache.tokens.read{provider="anthropic"}` and `prompt_cache.tokens.creation{provider="anthropic"}` from `recordOutcome`. Powers L3 dashboard.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/cache/OpenAiPromptCacheStrategy.java` — counter `prompt_cache.tokens.read{provider}` from `recordOutcome` for OpenAI + Gemini providers.
- **New code (WeatherMCP)**: same dependency lines + actuator config.
- **New code (Python services)**: `prometheus-fastapi-instrumentator` + `opentelemetry-distro` + `opentelemetry-exporter-otlp` in `pyproject.toml`; one-line wiring in `src/main.py` per service for both `/metrics` and OTel auto-instrumentation; ~3 custom counters per service.
- **New files**:
  - `docker-compose.yaml` — `prometheus`, `grafana`, `vector`, `loki`, `otel-collector`, `tempo`, `postgres-exporter`, `redis-exporter` services.
  - `observability/prometheus/prometheus.yaml`
  - `observability/vector/vector.toml` (with commented placeholder sinks for Datadog / CloudWatch / Splunk)
  - `observability/loki/loki-config.yaml`
  - `observability/otel-collector/otel-collector-config.yaml`
  - `observability/tempo/tempo-config.yaml`
  - `observability/grafana/provisioning/datasources/datasources.yaml` (Prometheus + Loki + Tempo)
  - `observability/grafana/provisioning/dashboards/dashboards.yaml`
  - `observability/grafana/dashboards/platform-overview.json`
  - `observability/grafana/dashboards/ai-pipeline.json`
  - `observability/grafana/dashboards/infrastructure.json`
  - `observability/grafana/dashboards/token-cost.json`
  - `observability/grafana/dashboards/rag-quality.json`
  - `observability/grafana/dashboards/cache-hit-rate.json`
  - `observability/grafana/dashboards/pricing.yaml` (per-provider $/1k token rates consumed by the token-cost dashboard)
  - `docs/OBSERVABILITY.md`
- **Tests**: smoke test that hits `/actuator/prometheus` on the agent and asserts the custom metric names exist with the expected tags; Python integration tests assert `/metrics` endpoint exposes `python_info` plus at least one custom counter; smoke test that asserts an OTel span reaches Tempo end-to-end after a single chat turn.
- **Docs**: `docs/OBSERVABILITY.md` (new); link in main README's Documentation section.
- **Backwards compat**: fully additive. No public API changes. Existing logging is unchanged (now also shipped to Loki by Vector). Stack is **always-on** (no opt-out profile per user direction).
- **Performance overhead**: Micrometer counters are nanosecond-scale. Prometheus scrape every 15 s. Vector reads Docker socket; sub-millisecond per log line. OTel spans are batched; the LLM calls already dominate latency. Negligible.
