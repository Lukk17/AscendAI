## Context

AscendAI runs six application services in two language stacks (Java 21 / Spring Boot, Python 3.11+ / FastAPI), four data-layer prerequisites (Postgres, Redis, Qdrant, MinIO), and four support services (SearXNG, FlareSolverr, Docling, Unstructured). Today, none of them export metrics, ship logs anywhere central, or emit traces. Operational state lives entirely in `docker logs` output streamed to stdout.

This change wires three pillars of observability — metrics, logs, traces — in a single coordinated rollout, plus six dashboards including ones that validate the recent prompt-caching change is actually saving money.

## Goals / Non-Goals

**Goals:**

- One Prometheus instance scraping every service.
- Centralised log search via Loki, fed by Vector reading Docker stdout (zero code change in services).
- Distributed tracing via Tempo, fed by an OTel collector that receives OTLP from every service. Spring AI 1.1 emits spans natively for LLM/tool/embedding calls.
- Grafana provisioned with three datasources (Prometheus, Loki, Tempo) and six checked-in dashboards (Platform Overview, AI Pipeline, Infrastructure, Token Cost, RAG Quality, Cache Hit Rate).
- Common tags on every metric: `service`, `instance`, `version`. Same convention extended to log labels and span attributes.
- Domain custom metrics that map 1:1 onto bugs we have already paid for once.
- **Always-on stack** — no opt-out profile (user direction). Observable by default keeps the happy path one command long.
- Documentation: `docs/OBSERVABILITY.md` describes what is collected and how to add a metric, log field, or span.

**Non-Goals:**

- Alerting rules / Alertmanager. Once metrics exist, alerting rules are a follow-up. We will write the metrics in a way that lets alerts be added without further code changes.
- Custom exporters for the data layer. We rely on official Prometheus exporters where they exist (`postgres_exporter`, `redis_exporter`, Qdrant native `/metrics`); MinIO ships built-in Prometheus output. No bespoke exporters.
- APM-style profiling (e.g., Pyroscope). Out of scope.
- Production-grade security on Grafana. Anonymous read-only viewer is fine for local dev; auth hardening is a follow-up if/when this stack runs in a shared environment.
- Compose-profile opt-out. Earlier draft included `--profile no-observability`; user dropped it.

## Decisions

### D1 — Stack: Prometheus + Grafana + Vector + Loki + OTel collector + Tempo

Three pillars, each via the modern open-standard tool:

- **Metrics** — Prometheus pull-based scrape; Grafana for visualisation. Spring Boot Actuator's Prometheus integration is two lines of `build.gradle.kts` plus three lines of YAML. `prometheus-fastapi-instrumentator` is one Python dependency line plus one wiring call.
- **Logs** — Vector reads Docker container stdout via the `docker_logs` source, ships to Loki via the `loki` sink. Vector chosen over Promtail because Vector is vendor-neutral; a future migration to Datadog / CloudWatch / Splunk is a `vector.toml` change with services unchanged.
- **Traces** — OTel collector receives OTLP from every service, batches, and exports to Tempo. Spring AI 1.1 already emits OTel spans natively for LLM/tool/embedding calls — wiring it is `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`. Python services add `opentelemetry-distro` for one-line auto-instrumentation.

OTel collector also future-proofs the migration story: same collector pipeline can fan out to Datadog OTLP, Honeycomb, Jaeger, etc., when the operator decides to upgrade.

**Alternative considered**: skip logs and traces, ship metrics only (the original plan). Rejected — the user asked for both. The marginal cost of three extra containers is small relative to the operational visibility gained, and the L3 cache-hit-rate dashboard motivated the metrics extension that powers L1/L2/L3 anyway.

### D2 — Custom metric inventory (named per OpenMetrics conventions)

Every metric is in lowercase, dot-separated for the Spring side (Micrometer auto-converts to underscore for Prometheus), suffixed `_total` for counters by Prometheus convention.

**AscendAgent (`service="ascend-agent"`):**

| Metric | Type | Tags | Why |
|---|---|---|---|
| `memory.extraction.parse_failed` | counter | `provider`, `model` | Catch the bug-1 regression. Spike → prompt drift / new model misbehaving. |
| `memory.insert.failed` | counter | `embedding_provider`, `reason` | Catch silent insert failures. |
| `memory.search.duration` | timer | `embedding_provider`, `outcome` | Latency + error rate of AscendMemory calls. |
| `rag.retrieval.hits` | counter | `provider`, `embedding_provider`, `above_threshold` | Threshold filtering ratio. Powers L2 dashboard. |
| `rag.retrieval.duration` | timer | `provider`, `outcome` | Spot Qdrant slowdowns. |
| `rag.last_top_score` | gauge | `provider` | Smoke-test retrieval quality post-deploy. |
| `rag.top_score` | histogram | `provider` | Top-K score distribution for L2 dashboard. |
| `mcp.tool.duration` | timer | `tool`, `outcome` | Per-tool latency / error rate. |
| `ingestion.upload.bytes` | counter | `source_type`, `outcome` | Catch flood scenarios + idempotency regressions. |
| `chat.history.size` | gauge | `user_id` (low-cardinality only — see D5) | Detect runaway sessions. |
| `prompt_cache.tokens.read` | counter | `provider` | Cache-hit token count for L3 dashboard. Emitted by `AnthropicPromptCacheStrategy.recordOutcome` and `OpenAiPromptCacheStrategy.recordOutcome`. |
| `prompt_cache.tokens.creation` | counter | `provider` | Cache-write token count (Anthropic only) for L3 dashboard. |
| `prompt_cache.tokens.total` | counter | `provider` | Total prompt tokens (cached + uncached) for L3 ratio computation. |
| `gen_ai.client.token.usage` | (auto from Spring AI) | `model`, `type` (input/output), `provider` | Spend tracking, free with Spring AI 1.1. Powers L1 dashboard. |

**WeatherMCP**: only `mcp.tool.duration` and the framework defaults.

**Python services** — same set as the original draft (transcription, search, memory ops, OCR pages).

### D3 — Common tags + log labels + span attributes

Every metric across every service carries:

- `service` — service name from `application.yaml` / FastAPI app metadata.
- `instance` — hostname (auto-populated by Prometheus from the scrape target).
- `version` — application version, resolved at build time.

The same `service` and `version` flow into Vector's log labels (`labels.service` from container metadata) and OTel resource attributes (`service.name`, `service.version`). This means Grafana's "view related logs / traces" buttons on a metric panel work out of the box: same service tag everywhere.

### D4 — Endpoint shape and security

| Service | Path | Bound to |
|---|---|---|
| AscendAgent | `/actuator/prometheus` | `127.0.0.1:9917` by default; remote exposure requires `MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_REMOTE=true` |
| WeatherMCP | `/actuator/prometheus` | same model |
| Python services | `/metrics` | bound to `0.0.0.0` inside the container; exposed only on the docker network |
| Prometheus | `:9090` | exposed on host |
| Grafana | `:3030` | exposed on host (anonymous read-only Viewer) |
| Loki | `:3100` | docker-network only |
| Tempo | `:3200` | docker-network only |
| OTel collector | `:4317` (gRPC), `:4318` (HTTP) | docker-network only |

Actuator endpoints are exposed only via `prometheus`, `health`, `info`. `env`, `heapdump`, `threaddump`, `loggers`, `caches` stay disabled to avoid leaking config.

### D5 — Cardinality discipline

High-cardinality tags are forbidden. Two rules:

1. **Never tag with `user_id` directly.** Single allowed exception: `chat.history.size` gauge, published only for the top-10 active sessions seen in the last minute (rotating slot allocation in `MetricsConfig`). Default install caps it at zero.
2. **Never tag with free-form strings (URLs, prompts, error messages).** Use a small enum-like set: `outcome ∈ {ok, error, timeout, rate_limited}`.

If a counter would naturally need an unbounded tag, drop the tag and emit a separate WARN log line with the rich context (now searchable in Loki).

### D6 — Provisioning Grafana, not configuring it

Grafana is fully provisioned at startup via files mounted into `/etc/grafana/provisioning/`:

- `datasources/datasources.yaml` — Prometheus, Loki, Tempo (Prometheus marked default).
- `dashboards/dashboards.yaml` — loads `/var/lib/grafana/dashboards/*.json`.
- `dashboards/*.json` — six checked-in dashboards (Platform Overview, AI Pipeline, Infrastructure, Token Cost, RAG Quality, Cache Hit Rate).

A fresh `docker-compose up` produces a fully working Grafana with all six dashboards already loaded across all three datasources. No clicking through the UI to wire datasources.

The dashboards are saved as JSON via Grafana's "Share → Export" with `For external use` toggled on so they are portable. We treat them as code: any change goes through git.

### D7 — Always-on, no opt-out

The earlier draft included a `--profile no-observability` opt-out. User dropped it: observability runs by default in `docker-compose.yaml` with no profile attribute on any of the eight new containers. Operators who don't want it can comment out the services in `docker-compose.yaml` (manual edit), which is acceptable given the always-on default makes the happy path simpler.

### D8 — Logs via Vector + Loki (Vector chosen for vendor-neutrality)

Vector container reads Docker container logs via the `docker_logs` source:

```toml
[sources.docker]
type = "docker_logs"
include_containers = ["ascend-agent", "weather-mcp", "ascend-memory", "audio-scribe", "ascend-web-search", "paddle-ocr"]
```

Then ships to Loki via the `loki` sink:

```toml
[sinks.loki]
type = "loki"
inputs = ["docker"]
endpoint = "http://loki:3100"
labels = { service = "{{ container_name }}", source = "docker" }
```

The `vector.toml` includes commented placeholder sinks for Datadog, CloudWatch, and Splunk so the migration story is documented inline:

```toml
# [sinks.datadog]
# type = "datadog_logs"
# inputs = ["docker"]
# default_api_key = "${DATADOG_API_KEY}"
# site = "datadoghq.eu"
```

To migrate, the operator uncomments the alternative sink, removes (or keeps) the Loki sink, sets the env var, and `docker compose restart vector`. **Services are unaffected.** This is the property that motivates Vector over Promtail.

### D9 — Traces via OTel collector + Tempo (Spring AI emits OTel natively)

OTel collector pipeline:

```yaml
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317
      http:
        endpoint: 0.0.0.0:4318

processors:
  batch:
  memory_limiter:
    check_interval: 1s
    limit_mib: 256

exporters:
  otlp/tempo:
    endpoint: tempo:4317
    tls:
      insecure: true

service:
  pipelines:
    traces:
      receivers: [otlp]
      processors: [memory_limiter, batch]
      exporters: [otlp/tempo]
```

**AscendAgent + WeatherMCP**: Spring Boot 3 already wires OpenTelemetry SDK by default when the OTel BOM is on the classpath (Spring AI 1.1 brings it transitively). Set `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317` via `application-docker.yaml` and `OTEL_SERVICE_NAME=ascend-agent`. Spring AI's auto-instrumentation produces spans for every `gen_ai.client.*` call and tool invocation.

**Python services**: add `opentelemetry-distro` + `opentelemetry-exporter-otlp` to `pyproject.toml`. Activate via `opentelemetry-instrument uvicorn ...` in the entrypoint command, OR via the `auto_instrumentation` entry point in `src/main.py`. FastAPI / requests / httpx are auto-instrumented out of the box.

Result: a single chat turn produces a trace with spans for: AscendAgent receives the request → RAG embedding call → Qdrant vector search → LLM provider call → MCP tool fan-out → response. Visible end-to-end in Grafana's Tempo panel.

### D10 — Six dashboards with cross-pillar drilldown

| # | Dashboard | Powered by | What it answers |
|---|---|---|---|
| 1 | Platform Overview | metrics | Are the services up? Are requests latent or erroring? |
| 2 | AI Pipeline | metrics | Are tokens flowing? RAG hitting? Tool calls latent? |
| 3 | Infrastructure | metrics (data-layer exporters) | Is Qdrant growing? Postgres connections healthy? |
| 4 | Token Cost (L1) | metrics + pricing.yaml | What is each provider costing per day? |
| 5 | RAG Quality (L2) | metrics + logs | Top-K score distribution; miss-rate trends; ingestion throughput |
| 6 | Cache Hit Rate (L3) | metrics | Is the prompt-caching change actually saving money? |

**L1 — Token Cost**: Multiplies `gen_ai.client.token.usage{provider="...",type="input"}` by per-provider $/1k input rates and `type="output"` by $/1k output rates. Rates are committed in `observability/grafana/dashboards/pricing.yaml` so updates go through git review. Daily-bucketed `sum by (provider)` panel; line chart per provider over time; total $ panel.

**L2 — RAG Quality**: Heatmap of `rag.top_score` histogram over time (shows score distribution drift). Time-series of `rag.retrieval.hits{above_threshold="false"} / sum(rag.retrieval.hits)` (miss-rate). Bar chart of ingestion-events-per-hour by `source_type` from `ingestion.upload.bytes_total`. Logs panel below pulls Loki entries matching `service="ascend-agent"` AND `level="WARN"` for retrieval-related warnings.

**L3 — Cache Hit Rate**: `rate(prompt_cache.tokens.read[5m]) / rate(prompt_cache.tokens.total[5m])` per provider — the headline cache-hit-rate ratio. Side panel: absolute saved tokens per hour (`rate(prompt_cache.tokens.read[1h]) * 3600`). Validates that the prompt-caching change is firing in production. Flat-line at 0% for any provider would flag a regression.

### D11 — Why these new domain metrics on the cache strategies

The shipped `add-prompt-caching` change logs cache outcomes at INFO. That's enough to verify behaviour during dev but not enough to dashboard. This change adds three counters emitted from `recordOutcome(...)` in both strategies:

- `prompt_cache.tokens.read{provider}` — incremented by `cacheReadInputTokens` (Anthropic) or `cachedTokens` (OpenAI/Gemini) on each call.
- `prompt_cache.tokens.creation{provider}` — incremented by `cacheCreationInputTokens` on each Anthropic call (zero for OpenAI/Gemini, where cache writes are implicit).
- `prompt_cache.tokens.total{provider}` — incremented by `promptTokens` on each call (the denominator for the hit-rate ratio).

`MeterRegistry` is already on the classpath after Actuator + Micrometer dependencies land. Wiring is one constructor arg and three `Counter.builder(...).register(meterRegistry).increment(...)` calls per strategy.

## Risks / Trade-offs

- **Container memory footprint.** Eight new containers; ~600 MB RAM at idle. On a laptop running everything locally, this is meaningful but tolerable. Document expected RAM in OBSERVABILITY.md.
- **Disk growth.** Prometheus default retention 15 days at ~1 GB; Loki retention default 31 days; Tempo retention 14 days. Total local-dev disk: ~5 GB steady state. We set `--storage.tsdb.retention.time=72h` for Prometheus, `retention_period: 168h` for Loki, and `retention: 168h` for Tempo to bound it.
- **Dashboard rot.** Custom dashboards drift from reality as code changes. Mitigation: every dashboard panel cites the underlying metric name, and `docs/OBSERVABILITY.md` lists the metrics inventory with the dashboards using them. When a metric is renamed, the cross-reference forces an update.
- **Cardinality explosion via well-meaning new tags.** Mitigated by D5 and a code-review checklist item.
- **Spring Boot version skew.** Spring Boot 3.5.4 is on Micrometer 1.13. The Prometheus simpleclient registry has moved to OpenMetrics-format-by-default; pin the registry version explicitly.
- **Python instrumentation overhead.** `prometheus-fastapi-instrumentator` adds an ASGI middleware that times every request. Sub-microsecond. OTel auto-instrumentation adds ~5–20 µs per span; LLM calls dominate latency anyway.
- **Vector reads Docker socket.** Mounting `/var/run/docker.sock` into a container is a privilege escalation vector. Mitigation: Vector container runs as `read-only` against the socket (mount with `:ro`) and has no other privileges.
- **OTel collector single point of failure.** If the collector container crashes, no traces ship until it restarts. Acceptable for v1 — local dev tolerates short blips. Production hardening (collector replicas, retry queues) is out of scope.

## Migration Plan

Strict additive change, executed in this order:

1. Add metrics-only stack (Prometheus + Grafana + AscendAgent actuator wiring) to `docker-compose.yaml`.
2. Wire AscendAgent custom metrics (memory, RAG, MCP, prompt-cache).
3. Wire WeatherMCP (mirror).
4. Add Vector + Loki containers + Vector config.
5. Add OTel collector + Tempo containers + OTel config; enable Spring AI's auto-instrumentation pointing at the collector.
6. Wire Python services for metrics (`prometheus-fastapi-instrumentator`).
7. Wire Python services for traces (`opentelemetry-distro`).
8. Add data-layer exporters (`postgres_exporter`, `redis_exporter`, Qdrant `/metrics`, MinIO native).
9. Author and provision the six dashboards.
10. Write `docs/OBSERVABILITY.md`.
11. Smoke-test: every dashboard renders something non-empty after running representative traffic.

## Open Questions

- **Should the agent expose the Prometheus endpoint on the same port as the API (`9917`) or a separate management port?** Spring Boot supports `management.server.port`. Default is the same port. Recommend keeping default for simplicity unless ops feedback says otherwise.
- **Grafana auth.** Anonymous Viewer for local. For shared dev environments, do we want OIDC via the same Keycloak the rest of the stack might use later? Out of scope here, flagged for follow-up.
- **Tempo retention.** 168h locally; longer (or remote-write) when we run this on shared infra. Not decided here.
