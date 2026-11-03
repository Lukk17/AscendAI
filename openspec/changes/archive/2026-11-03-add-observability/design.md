## Context

AscendAI runs six application services in two language stacks (Java 21 / Spring Boot, Python 3.11+ / FastAPI), four data-layer prerequisites (Postgres, Redis, Qdrant, the S3-compatible object store), and four support services (SearXNG, FlareSolverr, Docling, Unstructured). Today, none of them export metrics, ship logs anywhere central, or emit traces. Operational state lives entirely in `docker logs` output streamed to stdout.

This change wires three pillars of observability - metrics, logs, traces - in a single coordinated rollout, plus six dashboards including ones that validate the recent prompt-caching change is actually saving money.

## Goals / Non-Goals

Goals:

- One Prometheus instance scraping every service.
- Centralised log search via Loki, fed by the OpenTelemetry collector reading the Docker container logs (zero code change in services, D15).
- Distributed tracing via Tempo, fed by an OTel collector that receives OTLP from every service. Spring AI (1.1.5 while this change lands) emits spans natively for LLM/tool/embedding calls.
- Grafana provisioned with three datasources (Prometheus, Loki, Tempo) and six checked-in dashboards (Platform Overview, AI Pipeline, Infrastructure, Token Cost, RAG Quality, Cache Hit Rate).
- Common tags on every metric: `service`, `instance`, `version`. Same convention extended to log labels and span attributes.
- Domain custom metrics that map 1:1 onto bugs we have already paid for once.
- Always-on stack, no opt-out profile (user direction, confirmed by the owner on 2026-10-03 in answer 52: monitoring is core and never a switchable module). Observable by default keeps the happy path one command long (D7).
- Decide that every RFC 7807 problem body carries the id of the current trace, so an error a user reports leads straight to its trace in Tempo (D12). The later changes that own the problem body shape build the field.
- Documentation: `docs/OBSERVABILITY.md` describes what is collected and how to add a metric, log field, or span.

Non-Goals:

- Alerting rules / Alertmanager. Once metrics exist, alerting rules are a follow-up. We will write the metrics in a way that lets alerts be added without further code changes.
- Custom exporters for the data layer. We rely on official Prometheus exporters where they exist (`postgres_exporter`, `redis_exporter`, Qdrant native `/metrics`). The S3-compatible object store publishes no Prometheus endpoint, so it is not scraped and no bespoke exporter is written for it either.
- APM-style profiling (e.g., Pyroscope). Out of scope.
- Production-grade security on Grafana. Anonymous read-only viewer is fine for local dev; auth hardening is a follow-up if/when this stack runs in a shared environment.
- Compose-profile opt-out. Earlier draft included `--profile no-observability`. The user dropped it, and it stays rejected: observability is always on (D7).

## Decisions

### D1 - Stack: Prometheus + Grafana + Loki + OTel collector + Tempo

Three pillars, each via the modern open-standard tool:

- Metrics - Prometheus pull-based scrape; Grafana for visualisation. Spring Boot Actuator's Prometheus integration is two lines of `build.gradle.kts` plus three lines of YAML. `prometheus-fastapi-instrumentator` is one Python dependency line plus one wiring call.
- Logs - the OTel collector reads the Docker container logs of the application services and ships them to Loki over OTLP (D15, owner answer 89.12 of 2026-10-08). The first build used Vector for this, and D15 removes it, so one collector carries traces and logs. A future migration to Datadog / CloudWatch / Splunk is an exporter change in the collector config, with services unchanged.
- Traces - OTel collector receives OTLP from every service, batches, and exports to Tempo. Spring AI already emits OTel spans natively for LLM/tool/embedding calls - exporting them takes `management.otlp.tracing.endpoint` (the Spring Boot 3.5.14 name, which `upgrade-spring-boot-4` D12 later renames) and `management.tracing.sampling.probability` (see Tracing configuration for the Java services below). Python services use the OpenTelemetry FastAPI instrumentation each service wires in `src/main.py`, which exports to `OTEL_EXPORTER_OTLP_ENDPOINT`. `add-ascend-python-common` (build group 2) later replaces it with the tracer provider and ASGI middleware of its library (its D10).

OTel collector also future-proofs the migration story: same collector pipeline can fan out to Datadog OTLP, Honeycomb, Jaeger, etc., when the operator decides to upgrade.

Alternative considered: skip logs and traces, ship metrics only (the original plan). Rejected - the user asked for both. The marginal cost of three extra containers is small relative to the operational visibility gained, and the L3 cache-hit-rate dashboard motivated the metrics extension that powers L1/L2/L3 anyway.

### D2 - Custom metric inventory (named per OpenMetrics conventions)

Every metric is in lowercase, dot-separated for the Spring side (Micrometer auto-converts to underscore for Prometheus), suffixed `_total` for counters by Prometheus convention.

The first segment is the singular name of the domain, as in `memory.`, `rag.`, `mcp.` and `chat.` below. The planned changes follow this rule as `add-agent-skills` D14 states it (`skill.`, `capability.`, `subagent.`, `sandbox.`, `approval.`, `channel.`, `coding.`, `module.`), and a new domain segment is one word without an underscore (the existing `prompt_cache.` and Spring AI's `gen_ai.` keep their names), because an underscore in the domain (`self_improvement.`) turns into `self_improvement_` in Prometheus and reads as two domains (`add-self-improvement` uses `improvement.`). Each of those changes owns and documents its own metrics.

ascend-agent (`service="ascend-agent"`):

| Metric | Type | Tags | Why |
|---|---|---|---|
| `memory.extraction.parse_failed` | counter | `provider`, `model` | Catch the bug-1 regression. Spike → prompt drift / new model misbehaving. |
| `memory.insert.failed` | counter | `embedding_provider`, `reason` | Catch silent insert failures. |
| `memory.search.duration` | timer | `embedding_provider`, `outcome` | Latency + error rate of ascend-memory calls. |
| `rag.retrieval.hits` | counter | `provider`, `embedding_provider`, `above_threshold` | Threshold filtering ratio. Powers L2 dashboard. |
| `rag.retrieval.duration` | timer | `provider`, `outcome` | Spot Qdrant slowdowns. |
| `rag.top_score` | histogram | `provider` | Top-K score distribution for L2 dashboard. |
| `mcp.tool.duration` | timer | `tool`, `outcome` | Per-tool latency / error rate. |
| `ingestion.upload.bytes` | counter | `source_type`, `outcome` | Catch flood scenarios + idempotency regressions. |
| `prompt_cache.tokens.read` | counter | `provider` | Cache-hit token count for L3 dashboard. Emitted by `AnthropicPromptCacheStrategy.recordOutcome` and `OpenAiPromptCacheStrategy.recordOutcome`. |
| `prompt_cache.tokens.creation` | counter | `provider` | Cache-write token count (Anthropic only) for L3 dashboard. |
| `gen_ai.client.token.usage` | counter, recorded by `GenAiTokenUsageRecorder` from the `recordOutcome` of every prompt cache strategy | `gen_ai_system`, `gen_ai_request_model`, `gen_ai_token_type` (`input`, `output`, `total`) | Spend tracking. Powers the L1 dashboard, and its `input` series is the denominator of the L3 hit rate (D11). |

ascend-weather-mcp: only `mcp.tool.duration` and the framework defaults.

Python services - same set as the original draft (transcription, search, memory ops, OCR pages).

Owner answer 93 of 2026-10-08 removed three rows of the first build: the stub gauge `chat.history.size` (it always read 0, review item B10), the gauge `rag.last_top_score` (the histogram `rag.top_score` already holds every hit score, review item C2) and the counter `prompt_cache.tokens.total` (it counted the same prompt tokens as the `input` series of `gen_ai.client.token.usage`, review item C2). Tasks 2.7, 4.7 and 6.7 remove them from the code.

### D3 - Common tags + log labels + span attributes

Every metric across every service carries:

- `service` - service name from `application.yaml` / FastAPI app metadata.
- `instance` - hostname (auto-populated by Prometheus from the scrape target).
- `version` - application version, resolved at build time.

The same `service` flows into the Loki log label `service` (the compose service name, D15) and both flow into the OTel resource attributes (`service.name`, `service.version`). The `service` and `version` metric tags are set once, by `management.metrics.tags` in `application.yaml` (owner answer 93 of 2026-10-08, review item C1: the second copy in `MetricsConfig` is removed). This means Grafana's "view related logs / traces" buttons on a metric panel work out of the box: same service tag everywhere.

### D4 - Endpoint shape and security

| Service | Path | Bound to |
|---|---|---|
| ascend-agent | `/actuator/prometheus` | the separate internal management port `9918` (`management.server.port: 9918`, owner decision 65.6 of 2026-10-04). Every actuator endpoint (`health`, `info`, `prometheus`) is served there and none on the application port `9917`. `compose.yaml` never publishes `9918`, so only services on the compose network, Prometheus and the container healthcheck, reach it, and the gateway of `harden-cloud-deployment` never routes to it. Only `health`, `info` and `prometheus` are exposed |
| ascend-weather-mcp | `/actuator/prometheus` | the application port `9998`, as before. Only `health`, `info` and `prometheus` are exposed |
| Python services | `/metrics` | bound to `0.0.0.0` inside the container; exposed only on the docker network |
| Prometheus | `:7077` (host) → `:9090` (container) | exposed on host |
| Grafana | `:7078` (host) → `:3000` (container) | exposed on host (anonymous Viewer, task 1.8 moves `compose.yaml` from today's `Editor` to `Viewer`) |
| container-metrics-exporter | `:8080` docker network only | per-container CPU and memory, source in `infra/observability/container-metrics-exporter/` |
| Loki | `:3100` | docker-network only |
| Tempo | `:3200` | docker-network only |
| OTel collector | `:4317` (gRPC), `:4318` (HTTP) | docker-network only |

Actuator endpoints are exposed only via `prometheus`, `health`, `info`. `env`, `heapdump`, `threaddump`, `loggers`, `caches` stay disabled to avoid leaking config.

### D5 - Cardinality discipline

High-cardinality tags are forbidden. Two rules:

1. Never tag with `user_id`, and never with a tenant id (the planned changes put tenant level detail in log lines and the audit log instead, as `add-agent-skills` D14 states). There is no exception: the per-user `chat.history.size` gauge and its setting `app.metrics.user-gauge.max-tracked` were never built beyond a stub and are dropped (owner answer 93 of 2026-10-08, review item B10).
2. Never tag with free-form strings (URLs, prompts, error messages). Use a small enum-like set: `outcome ∈ {ok, error, timeout, rate_limited, not_found}`. The set matches the service-metrics spec, which lists `not_found` with the other four ("Cardinality discipline on tag values").

If a counter would naturally need an unbounded tag, drop the tag and emit a separate WARN log line with the rich context (now searchable in Loki).

### D6 - Provisioning Grafana, not configuring it

Grafana is fully provisioned at startup via files mounted into `/etc/grafana/provisioning/`:

- `datasources/datasources.yaml` - Prometheus, Loki, Tempo (Prometheus marked default).
- `dashboards/dashboards.yaml` - loads `/var/lib/grafana/dashboards/*.json`.
- `dashboards/*.json` - six checked-in dashboards (Platform Overview, AI Pipeline, Infrastructure, Token Cost, RAG Quality, Cache Hit Rate).

A fresh `docker compose up` produces a fully working Grafana with all six dashboards already loaded across all three datasources. No clicking through the UI to wire datasources.

The dashboards are saved as JSON via Grafana's "Share → Export" with `For external use` toggled on so they are portable. We treat them as code: any change goes through git.

### D7 - Always-on, no opt-out

The earlier draft included a `--profile no-observability` opt-out. User dropped it: observability runs by default in `compose.yaml` with no profile attribute on any of the seven new containers or on `container-metrics-exporter` (eight before D15 removed `vector`).

The owner confirmed this on 2026-10-03 (answer 52): monitoring (Prometheus, Grafana, Loki, Tempo, the OpenTelemetry collector, Vector and the container metrics exporter) is core and is never a switchable module. Vector was removed later by owner answer 89.12 of 2026-10-08 (D15), and the rest stays core. `add-deployment-modules` therefore keeps observability out of its module catalog and adds no profile and no export switch:

- None of the eight containers (`prometheus`, `grafana`, `loki`, `otel-collector`, `tempo`, `postgres-exporter`, `redis-exporter`, `container-metrics-exporter`) carries `profiles:`. Every `docker compose up` starts them, whatever `COMPOSE_PROFILES` holds.
- Every service exports its traces to the collector whenever its OTLP endpoint is set, and `compose.yaml` sets it for every service. No service reads `ASCEND_MODULES` or a custom `OTEL_ENABLED` to decide whether to export (owner answer 89.14 of 2026-10-08).
- The `GRAFANA_ADMIN_PASSWORD` compose `:?` guard is added later by `harden-cloud-deployment` (build group 3, position 4, owner answer 72.1 of 2026-10-06). `grafana` carries no module profile, so the guard does not conflict with the compose rules of `add-deployment-modules`, which list it as a guard every deployment must satisfy.

An earlier edit of 2026-10-02 had moved the containers under a profile `observability` and switched the export off with the module. That edit is undone.

### D8 - Logs via Vector + Loki (superseded by D15)

The first build shipped the container logs with Vector (`timberio/vector`, the `docker_logs` source and the `loki` sink in `infra/observability/vector/vector.toml`, labels `service` from the container name and `source="docker"`, commented migration sinks for Datadog, CloudWatch and Splunk). Owner answer 89.12 of 2026-10-08 replaced it with the OpenTelemetry collector, which the stack already runs for traces, so there is one collection agent. D15 keeps every label and log feature Vector gave, and tasks 8.6, 8.7, 9.9 and 9.10 make the switch.

### D9 - Traces via OTel collector + Tempo (Spring AI emits OTel natively)

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

ascend-agent + ascend-weather-mcp: on Spring Boot 3.5.14 the OTLP tracing auto-configuration is part of Spring Boot Actuator and needs `micrometer-tracing-bridge-otel` and `opentelemetry-exporter-otlp` on the classpath. Set `MANAGEMENT_OTLP_TRACING_ENDPOINT=http://otel-collector:4318/v1/traces`, `MANAGEMENT_TRACING_SAMPLING_PROBABILITY=1.0` and `OTEL_SERVICE_NAME=ascend-agent` in `compose.yaml` (see Tracing configuration for the Java services below). `upgrade-spring-boot-4` (build group 3) later moves the auto-configuration to `spring-boot-micrometer-tracing-opentelemetry` (its D2) and renames the variable (its D12 and task 11.6). Spring AI's auto-instrumentation produces spans for every `gen_ai.client.*` call and tool invocation.

Python services: each service wires an SDK tracer provider with `service.name`, an OTLP gRPC exporter to `OTEL_EXPORTER_OTLP_ENDPOINT` and the OpenTelemetry FastAPI instrumentation in its own startup code (tasks 10.3 and 11.1 to 11.3, ascend-ocr today behind its own `OTEL_ENABLED` setting). `opentelemetry-distro` and `opentelemetry-instrument` are not used. `add-ascend-python-common` (build group 2, its D10) later replaces this per service wiring with one tracer provider and the OpenTelemetry ASGI middleware of its library, and a service then passes any extra instrumentor it needs (ascend-ocr's aiohttp client) to the library's app factory. Owner answer 89.14 of 2026-10-08: tracing exports whenever `OTEL_EXPORTER_OTLP_ENDPOINT` is set, OpenTelemetry's standard `OTEL_SDK_DISABLED=true` switches it off (in tests), and no service keeps a custom `OTEL_ENABLED`. `add-ascend-python-common` owns that change and removes ascend-ocr's setting.

Result: a single chat turn produces a trace with spans for: ascend-agent receives the request → RAG embedding call → Qdrant vector search → LLM provider call → MCP tool fan-out → response. Visible end-to-end in Grafana's Tempo panel.

### D10 - Six dashboards with cross-pillar drilldown

| # | Dashboard | Powered by | What it answers |
|---|---|---|---|
| 1 | Platform Overview | metrics | Are the services up? Are requests latent or erroring? |
| 2 | AI Pipeline | metrics | Are tokens flowing? RAG hitting? Tool calls latent? |
| 3 | Infrastructure | metrics (data-layer exporters) | Is Qdrant growing? Postgres connections healthy? |
| 4 | Token Cost (L1) | metrics + the price series Prometheus records from pricing.yaml (D16) | What is each provider costing per day? |
| 5 | RAG Quality (L2) | metrics + logs | Top-K score distribution; miss-rate trends; ingestion throughput |
| 6 | Cache Hit Rate (L3) | metrics | Is the prompt-caching change actually saving money? |

L1 - Token Cost: Multiplies `gen_ai_client_token_usage_total{gen_ai_token_type="input"}` by the per-provider $/1k input rate and `gen_ai_token_type="output"` by the $/1k output rate, both read from the price series `token_price_usd_per_1k` that Prometheus records from `infra/observability/grafana/dashboards/pricing.yaml` (D16). The rates are written only in that file, so updates go through git review and the dashboard holds no copy. `add-agent-subagents` (build group 4, its task 1.4, owner decision of 2026-10-02) later moves the file to `infra/pricing/pricing.yaml` and mounts it read-only into the agent for subagent run cost, so one price update then changes the dashboard and the run limits together. Daily-bucketed `sum by (provider)` panel; line chart per provider over time; total $ panel.

L2 - RAG Quality: Heatmap of `rag.top_score` histogram over time (shows score distribution drift). Time-series of `rag.retrieval.hits{above_threshold="false"} / sum(rag.retrieval.hits)` (miss-rate). Bar chart of ingestion-events-per-hour by `source_type` from `ingestion.upload.bytes_total`. Logs panel below pulls Loki entries matching `service="ascend-agent"` AND `level="WARN"` for retrieval-related warnings.

L3 - Cache Hit Rate: `rate(prompt_cache_tokens_read_total[5m])` divided by the `input` series of `gen_ai_client_token_usage_total` per provider - the headline cache-hit-rate ratio (owner answer 93 of 2026-10-08, D11). Side panel: absolute saved tokens per hour (`rate(prompt_cache.tokens.read[1h]) * 3600`). Validates that the prompt-caching change is firing in production. Flat-line at 0% for any provider would flag a regression.

### D11 - Why these new domain metrics on the cache strategies

The shipped `add-prompt-caching` change logs cache outcomes at INFO. That's enough to verify behaviour during dev but not enough to dashboard. This change first added three counters emitted from `recordOutcome(...)` in both strategies. Owner answer 93 of 2026-10-08 keeps the first two and drops the third (task 6.7):

- `prompt_cache.tokens.read{provider}` - incremented by `cacheReadInputTokens` (Anthropic) or `cachedTokens` (OpenAI/Gemini) on each call.
- `prompt_cache.tokens.creation{provider}` - incremented by `cacheCreationInputTokens` on each Anthropic call (zero for OpenAI/Gemini, where cache writes are implicit).
- `prompt_cache.tokens.total{provider}` - dropped. It was incremented by `promptTokens` on each call, the same number `GenAiTokenUsageRecorder` adds to `gen_ai.client.token.usage` with `gen_ai_token_type="input"` in the same call (checked in both strategies on 2026-10-08), so that `input` series is the denominator of the hit rate.

`MeterRegistry` is already on the classpath after Actuator + Micrometer dependencies land. Wiring is one constructor arg and one `Counter.builder(...).register(meterRegistry).increment(...)` call per counter.

### D12 - Every problem body carries the trace id

Owner decision of 2026-10-03 (answer 51.3). `upgrade-spring-boot-4` D19 makes every REST error body of the agent an RFC 7807 problem detail. Every one of them gains the extension field `traceId`: the 32 character lower case hex id of the trace that is current while the body is written, read from Micrometer's `Tracer` (`tracer.currentSpan().context().traceId()`). It sits at the top level next to `code`, the same way D19 renders its other extension fields. This covers the bodies of `GlobalExceptionHandler`, the 401 body of the security entry point and the `/error` body. D19 point 3 builds every one of them in one place, so the field is added there once, not per exception.

The trace exists even when the span is not sampled, so the id is always the real one. When no span is current, which happens only outside an HTTP request, the field is left out. It is never set to an empty or invented value. The id is the one Tempo stores, so an operator pastes it into Grafana's Tempo search and gets the failed request. No separate request id or correlation id is added, because the trace id already names one request across every service. The Python services carry the same `traceId` in every problem body and the trace id and request id in every log line through the `ascend-python-common` library (`add-ascend-python-common` D5, D7, D8 and D10), so this change adds no Python code for either.

The field is added by `upgrade-spring-boot-4` (build group 3) to its D19 (required edit below), because D19 owns the agent problem body shape, and by `add-ascend-python-common` (build group 2) to its D5 for the Python services. This change owns the decision only. It lands before both and builds no field. The end to end check from a problem body to its trace in Tempo and the section "From an error to its trace" of `docs/OBSERVABILITY.md` moved to those two changes (former task 16.3, part of 16.4 and 17.4, dependency fix of 2026-10-05): `add-ascend-python-common` writes the section and the platform spec with the Python half, and `upgrade-spring-boot-4` extends both with the agent half.

## Required edits to other changes

### `upgrade-spring-boot-4`

1. D19: every problem body carries the extension field `traceId`, as described in D12 of this change, including the 401 body of the security entry point and the `/error` body written by `ProblemDetailWriter`. Its line that leaves the request id or trace id to this change becomes a pointer to D12, and its required edits table row for `add-observability` drops the open decision.

Made in that change (checked 2026-10-03, its D19 point 3 and its required edits row for this change).

## Risks / Trade-offs

- Container memory footprint. Seven new containers (eight before D15 removed `vector`); ~600 MB RAM at idle. On a laptop running everything locally, this is meaningful but tolerable. Document expected RAM in OBSERVABILITY.md.
- Disk growth. Prometheus default retention 15 days at ~1 GB; Loki retention default 31 days; Tempo retention 14 days. Total local-dev disk: ~5 GB steady state. We set `--storage.tsdb.retention.time=${PROMETHEUS_RETENTION_TIME:-72h}` for Prometheus, and 2160 hours (3 months) for Loki and Tempo by default (D13), each configurable in `.env`.
- Dashboard rot. Custom dashboards drift from reality as code changes. Mitigation: every dashboard panel cites the underlying metric name, and `docs/OBSERVABILITY.md` lists the metrics inventory with the dashboards using them. When a metric is renamed, the cross-reference forces an update.
- Cardinality explosion via well-meaning new tags. Mitigated by D5 and a code-review checklist item.
- Spring Boot version skew. This change lands on Spring Boot 3.5.14 with Micrometer 1.15. `upgrade-spring-boot-4` later moves the services to Spring Boot 4.1.1 with Micrometer 1.17.1, where the Prometheus registry writes OpenMetrics format by default, so pin the registry version explicitly.
- Python instrumentation overhead. `prometheus-fastapi-instrumentator` adds an ASGI middleware that times every request. Sub-microsecond. OTel auto-instrumentation adds ~5-20 µs per span; LLM calls dominate latency anyway.
- The collector reads the Docker socket and the container log files (D15). Mounting `/var/run/docker.sock` into a container is a privilege escalation path, and the collector runs as user `0` to read them on Docker Engine for Linux, the same privilege Vector had. Mitigation: both mounts are read-only, the collector publishes no port, and the Docker documentation's warning that the `json-file` files belong to the daemon is met by reading them only.
- OTel collector single point of failure. If the collector container crashes, no traces ship until it restarts. Acceptable for v1 - local dev tolerates short blips. Production hardening (collector replicas, retry queues) is out of scope here: company plans it later in `plan-scaled-deployment` (build group 5), this change does not wait for it.

## Migration Plan

Strict additive change, executed in this order:

1. Add metrics-only stack (Prometheus + Grafana + ascend-agent actuator wiring) to `compose.yaml`.
2. Wire ascend-agent custom metrics (memory, RAG, MCP, prompt-cache).
3. Wire ascend-weather-mcp (mirror).
4. Add Loki and the collector's logs pipeline (D15). The first build used Vector here, and tasks 8.6, 8.7, 9.9 and 9.10 replace it.
5. Add OTel collector + Tempo containers + OTel config; enable Spring AI's auto-instrumentation pointing at the collector.
6. Python services get `/metrics` from `prometheus-fastapi-instrumentator`, wired per service. `add-ascend-python-common` (its D11) later moves it into its library and adds the remaining domain counters.
7. Python services get their traces from the per service FastAPI instrumentation, with no `opentelemetry-distro`. The same library later replaces it (its D10).
8. Add data-layer exporters (`postgres_exporter`, `redis_exporter`, Qdrant `/metrics`). The owner kept the Redis and Postgres exporters in scope on 2026-10-01. Their exact image versions are looked up and pinned (version tag and digest) at implementation time.
9. Author and provision the six dashboards.
10. Write `docs/OBSERVABILITY.md`.
11. Smoke-test: every dashboard renders something non-empty after running representative traffic.

### D13 - Retention of traces, logs and metrics, configurable in `.env` (owner decision 65.21 of 2026-10-04)

Traces and logs are kept at least 3 months by default, `2160h`. Every window is set in `.env` and passed through `compose.yaml`, so the operator changes it without editing a config file.

| Store | Variable | Default | Where it lands, checked against the pinned version on 2026-10-04 |
|---|---|---|---|
| Loki `grafana/loki:3.3.2` | `LOKI_RETENTION_PERIOD` | `2160h` | `limits_config.retention_period: ${LOKI_RETENTION_PERIOD:-2160h}` in `infra/observability/loki/loki-config.yaml`. Retention runs in the compactor, which already has `retention_enabled: true`, `retention_delete_delay: 2h` and the mandatory `delete_request_store: filesystem`, and needs the 24 hour index period the schema already has (Loki 3.3.x retention reference) |
| Tempo `grafana/tempo:2.6.1` | `TEMPO_BLOCK_RETENTION` | `2160h` | `compactor.compaction.block_retention: ${TEMPO_BLOCK_RETENTION:-2160h}` in `infra/observability/tempo/tempo-config.yaml` (Tempo 2.6.x configuration reference, default there 336h) |
| Prometheus `prom/prometheus:v2.55.1` | `PROMETHEUS_RETENTION_TIME` | `72h` | the command flag `--storage.tsdb.retention.time=${PROMETHEUS_RETENTION_TIME:-72h}`, filled in by compose |

Loki and Tempo read `${VAR:-default}` in their config files only when started with `-config.expand-env=true`, so both commands in `compose.yaml` gain that flag and both services get the variable in their `environment:`. A reference to an unset variable falls back to its default. The three variables get their rows in the configuration reference and no line in the root `.env.example`, because each has a default (owner rule 98 of 2026-10-08, D17, tasks 14.7 and 15.7).

Disk estimate for one server. This is a planning figure, not a measurement: the volumes measured on the development host on 2026-10-04 (`tempo-data` 24.79 MB, `loki-data` 1.77 MB, `prometheus-data` 1.83 MB) hold light development traffic of unknown age, so they give no rate. The planning assumption for one customer server is up to 10,000 chat requests a day with traces of about 20 KB each (about 200 MB a day) and about 100 MB of compressed logs a day. Over 90 days that is about 18 GB for Tempo and 9 GB for Loki, plus about 1 GB for Prometheus at 72 hours, so reserve 30 GB, and 50 GB to leave room. Task 15.5 measures the real growth rate per day of all three volumes under load and replaces this estimate in `docs/OBSERVABILITY.md` with the measured figure.

## Open Questions

- Closed (owner decision 65.6 of 2026-10-04): the agent's metrics move to the separate internal management port `9918` (`management.server.port`), reachable only on the container network by Prometheus and never through the gateway (D4). The scrape target is `ascend-agent:9918` and the agent's container healthcheck calls `http://localhost:9918/actuator/health`.
- Closed (owner decision 65.20 of 2026-10-04): Grafana login is as `harden-cloud-deployment` decides it: anonymous access off and the admin login from `GRAFANA_ADMIN_USER` and `GRAFANA_ADMIN_PASSWORD` in `.env`. The anonymous Viewer of this change holds only until that change lands, and no Keycloak sign-in for Grafana is planned.
- Closed (owner decision 65.21 of 2026-10-04): traces (Tempo) and logs (Loki) are kept at least 3 months by default, `2160h`, and Prometheus retention is configurable too, all through `.env` (D13).
- Request id or trace id in every problem body. Decided by the owner on 2026-10-03 (answer 51.3): every problem body carries `traceId`, see D12.

## Tracing configuration for the Java services

Spring Boot 3.5.14 does not read `OTEL_EXPORTER_OTLP_ENDPOINT`, so the `OTEL_EXPORTER_OTLP_ENDPOINT` entries in `compose.yaml` for `ascend-agent` and `ascend-weather-mcp` have no effect on those two services. Spring Boot 3.5.14 exports spans only when `management.otlp.tracing.endpoint` is set, and samples only `management.tracing.sampling.probability` of requests (default `0.1`). Both Java services therefore set, through `compose.yaml` environment entries so local `bootRun` stays quiet:

- `MANAGEMENT_OTLP_TRACING_ENDPOINT=http://otel-collector:4318/v1/traces` (OTLP over HTTP, the Spring Boot default transport, which the collector receives on `:4318`)
- `MANAGEMENT_TRACING_SAMPLING_PROBABILITY=1.0` for the local stack

`upgrade-spring-boot-4` (build group 3) lands later and moves both services to Spring Boot 4.1.1, where the old name is removed at level `error` and an environment variable with the old name is silently ignored. Its task 11.6 renames the entry to `MANAGEMENT_OPENTELEMETRY_TRACING_EXPORT_OTLP_ENDPOINT` (its D12), so traces keep flowing.

`OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` stay. The AI-run platform spec of task 17.7 checks that the trace in Tempo carries `service.name=ascend-agent` (task 9.7 removed by owner decision 91.3 of 2026-10-08). ascend-weather-mcp also needs the `io.opentelemetry:opentelemetry-exporter-otlp` dependency, which ascend-agent already has.

## Python metric names

The service-metrics spec is the target. Where an existing main spec already defines a metric, that spec wins: `openspec/specs/web-search-caching-observability/spec.md` owns the ascend-web-hunter strategy outcome metric (`strategy_attempts_total` with `strategy`, `outcome` and `domain`), and the ascend-ocr job metrics described in `apps/ascend-ocr/AGENTS.md` and `openspec/specs/ocr-job-admission/spec.md` (`ascendocr_jobs_total`, `ascendocr_job_queue_documents`, `ascendocr_job_queue_pages`, `ascendocr_job_queue_wait_seconds`, `ascendocr_job_duration_seconds`) replace the old per-request OCR plan, because every OCR request is now a job. The code today uses different names for ascend-memory (`memory_insert_total` and others), ascend-audio-scribe (`ascendaudioscribe_*`) and ascend-web-hunter search results (`ascendwebhunter_search_results_total`). Bringing that code to the target names, with the requirement that defines them, moved to `add-ascend-python-common` (build group 2), which adds the counters on top of its library (former tasks 10.5, 10.6, 11.5 and 11.6, dependency fix of 2026-10-05). The service-metrics spec of this change keeps only the Python metrics that exist when it lands: `/metrics` with the framework defaults, the ascend-web-hunter strategy metric and the ascend-ocr job metrics.

### D14 - The platform specs read Grafana as the anonymous Viewer (owner answer of 2026-10-08)

This change runs Grafana with the anonymous Viewer of task 1.8 and reads no admin password. `GRAFANA_ADMIN_PASSWORD` and its compose `:?` guard come with `harden-cloud-deployment` (build group 3, position 4), which lands later. So the Bruno requests of task 17.2 send no login: the datasource check reads `GET /api/frontend/settings` (its `datasources` object, by name) and the dashboard check reads `GET /api/search?type=dash-db`, both as the anonymous Viewer. `GET /api/datasources` is not used, because it needs the `datasources:read` permission, which the Viewer role does not hold (Grafana HTTP API documentation, checked through Context7 on 2026-10-08). The write check `grafana-anonymous-write.yml` stays as it is. When `harden-cloud-deployment` turns anonymous access off, that change updates the two read requests and the platform spec in place.

### D15 - Logs through the OpenTelemetry collector, Vector removed (owner answer 89.12 of 2026-10-08)

One collection agent for traces and logs. The `otel-collector` service reads the Docker logs of the application containers and sends them to Loki over OTLP. The `vector` service and `infra/observability/vector/vector.toml` are removed (task 8.6).

Pipeline (tasks 9.9 and 9.10):

- The `docker_observer` extension watches `unix:///var/run/docker.sock` (read-only mount) and reports each running container with its name, id and labels.
- A `receiver_creator` starts one `filelog` receiver per running container whose compose label `com.docker.compose.service` is one of the six application services (`ascend-agent`, `ascend-weather-mcp`, `ascend-memory`, `ascend-audio-scribe`, `ascend-web-hunter`, `ascend-ocr`). The receiver reads `/var/lib/docker/containers/<container_id>/<container_id>-json.log` (read-only mount) with the `container` operator, format `docker`, which takes the line text, the stream (`stdout` or `stderr`) and the time out of the Docker JSON. Exactly one receiver per container: `docker_observer` emits one endpoint per exposed port, so the rule matches one port per service, or uses `include_all_containers` with `port == 0` where the pinned collector version has it.
- Each entry gets the resource attributes `service` (the compose service name), `source` (`docker`) and the container name.
- The `otlphttp/loki` exporter sends to `http://loki:3100/otlp`. Loki indexes `service` and `source` as stream labels (`limits_config.otlp_config`, task 8.7) and keeps the container name and the stream as structured metadata.
- The `logs` pipeline runs through the existing `memory_limiter` and `batch` processors.

What Vector gave, and where it stays:

| Vector feature | After D15 |
|---|---|
| Label `service` from the container name | Label `service` from the compose label `com.docker.compose.service`. For each service today this is the same value as the container name, so every query `{service="..."}` keeps working |
| Label `source="docker"` | Same label, same value |
| The line text as the log entry (`encoding.codec = "text"`) | The body is the line text the `container` operator takes out of the Docker JSON, unchanged |
| `stdout` and `stderr` | Both, the stream kept as structured metadata |
| Only the six application containers | Only the six application services, matched by compose label |
| Commented migration sinks for Datadog, CloudWatch and Splunk | Commented exporter stanzas `datadog`, `awscloudwatchlogs` and `splunk_hec` in the collector config, and the recipe in `docs/OBSERVABILITY.md` |
| Read-only socket mount, runs as root | Read-only socket and log folder mounts, runs as user `0` |

Several instances (owner answer 87 of 2026-10-08, rule R1): every container of a service gets the same `service` label, because the label comes from the compose service name and not from the container name, and its container name stays apart as structured metadata. One collector reads every container of its Docker host, so a second host runs its own collector with the same config.

The first build also had a defect this fixes: `vector.toml` lists `ascend-ai-agent`, while the agent's container is named `ascend-agent` (`compose.yaml`, read on 2026-10-08), so the agent's logs did not reach Loki. Matching on the compose service label avoids the stale name.

Docker Desktop and Docker Engine for Linux (checked through Context7 on 2026-10-08):

- `opentelemetry-collector-contrib`: the `container` operator of the `filelog` receiver parses the `docker`, `cri-o` and `containerd` formats (`pkg/stanza/docs/operators/container.md`). `docker_observer` with `receiver_creator` exposes `name`, `container_id` and `labels` to the rule (`extension/observer/dockerobserver/README.md`), and `include_all_containers` is documented on the main branch only, so the pinned `0.114.0` is checked first. The `loki` exporter was deprecated on 2024-07-09 and removed (the contrib changelog), so `otlphttp` is used.
- Loki: `limits_config.otlp_config.resource_attributes.attributes_config` with `action: index_label` makes a resource attribute a stream label, and the rest becomes structured metadata (`docs/sources/send-data/otel/_index.md`, `docs/sources/shared/configuration.md`).
- Docker: `json-file` writes one JSON file per container, and the documentation warns that the files belong to the daemon (`content/manuals/engine/logging/drivers/json-file.md`). The collector only reads them. The daemon's default driver can be changed (`content/manuals/engine/logging/configure.md`), and the `local` driver writes a format the receiver cannot read, so the six application services set `logging.driver: json-file` in `compose.yaml`.
- Docker Engine for Linux: the files are under `/var/lib/docker/containers` on the host and belong to `root`, and the socket is `root:docker` (`fix-linux-docker-host-access` design). The collector runs as user `0`, the same privilege Vector has today.
- Docker Desktop: `/var/lib/docker/containers` is a path inside the Docker Desktop virtual machine, which a bind mount of a Linux path reaches. This is not stated by the pages read, so task 9.10 checks it on the owner's Docker Desktop with the logs spec of task 17.5 and stops and reports to the owner if no line arrives. No Linux host is available for a live check, so the Linux path rests on the documentation above.

### D16 - One price source: Prometheus records the rates from pricing.yaml (owner answer 89.13 of 2026-10-08)

The first build had two copies of every rate: `pricing.yaml` and the numbers written into the queries of `token-cost.json`. Nothing read `pricing.yaml`, so the spec scenario "reflects pricing.yaml updates after a restart" was false (review item B11). Now `pricing.yaml` is the only place a rate is written (task 13.11):

- When the `prometheus` container starts, the script `infra/observability/prometheus/price-rules.sh` (its entrypoint, POSIX `sh`) reads `pricing.yaml` and writes the rule file `/prometheus/token-price-rules.yaml`: one recording rule per provider and token type, recording `token_price_usd_per_1k{gen_ai_system="<provider>",gen_ai_token_type="input|output"}` as a constant. Then it starts Prometheus. A missing or unreadable file, or a provider without both rates, stops the container instead of showing a wrong cost.
- `prometheus.yaml` lists the generated file under `rule_files`. It is never committed.
- Every Token Cost query multiplies `gen_ai_client_token_usage_total` by that series with `on (gen_ai_system, gen_ai_token_type) group_left` and divides by 1000. The dashboard holds no rate.
- A rate change is a commit to `pricing.yaml` and `docker compose restart prometheus`.

The file keeps the shape it has on disk: a top-level `providers:` map, each provider with `input_per_1k` and `output_per_1k` (read on 2026-10-08). The old spec text with a flat map and `per_1k_input` was wrong and is fixed. `add-agent-subagents` task 1.4 later moves the file to `infra/pricing/pricing.yaml`, and the move takes the price rule input with it (the mount into `prometheus` and the path the script reads), sent to that change on 2026-10-08.

Rejected: Grafana provisioning, because a dashboard cannot read a YAML value. A rule file committed next to `pricing.yaml` with a test that it matches, because that is the second copy the owner removed.

### D17 - Every operational value is a setting (owner rule 98 of 2026-10-08)

Every value of this change that has a default and that an operator might need to change is read from an environment variable. Docker compose passes it as `- VAR=${VAR:-default}` on the service that reads it, and the configuration file or the code carries the same default. How each container reads it:

- Loki and Tempo expand `${VAR:-default}` in their configuration files, because both already start with `-config.expand-env=true` (D13).
- The OpenTelemetry collector expands `${env:VAR:-default}` through its `env` provider. Task 9.12 first checks that the pinned `0.114.0` accepts the `:-` form.
- Prometheus v2.55 expands environment variables only in external label values and only behind a feature flag, so the entrypoint script of D16 also renders `prometheus.yaml` from the committed file, which holds the variable names in place of the values (task 1.9).
- Grafana expands `${VAR}` in its provisioning files. Task 1.10 checks against the pinned `11.4.0` whether a default form is accepted there.
- ascend-agent and ascend-weather-mcp write `key: ${ENV:default}` in `application-docker.yaml`, the profile the compose services run with (tasks 9.5 and 9.13).
- The exporters read their own variables (`REDIS_ADDR`, `DATA_SOURCE_URI`), so only the compose line changes (task 12.6).
- The Python services read `OTEL_EXPORTER_OTLP_ENDPOINT`, the OpenTelemetry standard name (tasks 10.9 and 11.7). It is also the switch of owner answer 89.14: a service exports only when it is set, and the standalone ascend-web-hunter bundle leaves it unset. So the code keeps no address default, and the compose line is the one place the default is written.

| Service | Variable | Default | Task |
|---|---|---|---|
| `prometheus` | `PROMETHEUS_SCRAPE_INTERVAL` | `15s` | 1.9 |
| `prometheus` | `PROMETHEUS_EVALUATION_INTERVAL` | `15s` | 1.9 |
| `prometheus`, `tempo` | `OBSERVABILITY_CLUSTER_LABEL` | `ascend-ai-local` | 1.9, 9.11 |
| `prometheus` | `PROMETHEUS_QDRANT_TARGET` | `host.docker.internal:6333` | 1.9 |
| `prometheus` | `PROMETHEUS_HOST_PORT` | `7077` | 1.9 |
| `prometheus` | `PROMETHEUS_RETENTION_TIME` | `72h` | 15.7 |
| `grafana` | `GRAFANA_HOST_PORT` | `7078` | 1.10 |
| `grafana` | `GF_SERVER_ROOT_URL` | `http://localhost:7078` | 1.10 |
| `grafana` | `PROMETHEUS_SCRAPE_INTERVAL` | `15s` | 1.10 |
| `grafana` | `GRAFANA_LOKI_MAX_LINES` | `1000` | 1.10 |
| `grafana` | `GRAFANA_DASHBOARDS_UPDATE_INTERVAL_SECONDS` | `30` | 1.10 |
| `loki` | `LOKI_RETENTION_PERIOD` | `2160h` | 15.7 |
| `loki` | `LOKI_RETENTION_DELETE_DELAY` | `2h` | 8.8 |
| `loki` | `LOKI_RESULTS_CACHE_MAX_SIZE_MB` | `100` | 8.8 |
| `tempo` | `TEMPO_BLOCK_RETENTION` | `2160h` | 15.7 |
| `tempo` | `TEMPO_LOG_LEVEL` | `info` | 9.11 |
| `tempo` | `TEMPO_MAX_BLOCK_DURATION` | `5m` | 9.11 |
| `tempo` | `TEMPO_SEARCH_DURATION_SLO` | `5s` | 9.11 |
| `tempo` | `TEMPO_SEARCH_THROUGHPUT_BYTES_SLO` | `1073741824` | 9.11 |
| `tempo` | `TEMPO_TRACE_BY_ID_DURATION_SLO` | `5s` | 9.11 |
| `otel-collector` | `COLLECTOR_MEMORY_CHECK_INTERVAL` | `1s` | 9.12 |
| `otel-collector` | `COLLECTOR_MEMORY_LIMIT_MIB` | `256` | 9.12 |
| `otel-collector` | `COLLECTOR_MEMORY_SPIKE_LIMIT_MIB` | `64` | 9.12 |
| `otel-collector` | `COLLECTOR_BATCH_TIMEOUT` | `1s` | 9.12 |
| `otel-collector` | `COLLECTOR_BATCH_SIZE` | `1024` | 9.12 |
| `ascend-agent`, `ascend-weather-mcp` | `MANAGEMENT_OTLP_TRACING_ENDPOINT` | `http://otel-collector:4318/v1/traces` | 9.5, 9.13 |
| `ascend-agent`, `ascend-weather-mcp` | `MANAGEMENT_TRACING_SAMPLING_PROBABILITY` | `1.0` | 9.5, 9.13 |
| `ascend-memory`, `ascend-audio-scribe`, `ascend-ocr`, `ascend-web-hunter` | `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | 10.9, 11.7 |
| `redis-exporter` | `REDIS_ADDR` | `redis://host.docker.internal:6379` | 12.6 |
| `postgres-exporter` | `DATA_SOURCE_URI` | `host.docker.internal:5432/ascend_ai?sslmode=disable` | 12.6 |
| `ascend-agent` | `AGENT_HOST_PORT` | `9917` | 9.14 |
| `ascend-weather-mcp` | `WEATHER_MCP_HOST_PORT` | `9998` | 9.14 |

Any interval, limit or size the logs pipeline of D15 sets is a setting in the same form, and a value left at the collector's own default is not written at all (task 9.9).

Values that stay as written, because they are not operational:

- Listen ports inside a container and addresses on the compose network: `9090`, `3000`, `3100`, `3200`, `4317`, `4318`, the Tempo `frontend_address` `127.0.0.1:9095`, the agent's management port `9918`, the ports of the scrape jobs of the application services and of the exporters, and the addresses `tempo:4317`, `http://loki:3100/otlp`, `http://prometheus:9090`, `http://loki:3100` and `http://tempo:3200`. They are fixed by the image or shared between the scrape job, the healthcheck and the specs, and no port of them is published. Only the published host ports are settings.
- The stored data format of Loki: the schema `v13`, the index period `24h` and `replication_factor: 1`. Changing one on a running store breaks the stored data, so it is no tuning value.
- `ruler.alertmanager_url` of Loki: no Alertmanager runs (Non-Goals), so the value is used by nothing today.
- Names and labels: job names, the labels `service`, `source` and `source: tempo`, metric names, actuator paths, `OTEL_SERVICE_NAME` and `OTEL_RESOURCE_ATTRIBUTES` (they name a service and its version).
- The anonymous access lines of Grafana (`GF_AUTH_ANONYMOUS_ENABLED`, `GF_AUTH_ANONYMOUS_ORG_ROLE`, `GF_AUTH_DISABLE_LOGIN_FORM`): the spec requires the anonymous Viewer, and `harden-cloud-deployment` owns the login (D14).
- Dashboard queries, which are reviewed as code (D6): their ranges and the quantile `0.95` of task 13.10, and the divisor `1000` of the per 1k price (D16), a mathematical constant. The rates themselves are data in `pricing.yaml`.
- Test-only values: the waits, users, job lists and metric tests of the platform specs of group 17 and the load test of task 15.5.

Configuration reference (owner rule 98 of 2026-10-08): `fix-linux-docker-host-access` (build group 1, position 4) creates `docs/CONFIGURATION.md` and, in its section 9 inventory task, the rows of every setting that exists when that task lands. A setting of this change still open then gets its row from this change, in the same commit as the setting (task 14.7).

### D18 - The monitoring images run their latest stable release (owner rule 105.2 of 2026-10-09)

Owner rule 105.2 of 2026-10-09: always use the latest stable version where possible. Compose pins today (read from `compose.yaml` on 2026-10-09): `prom/prometheus:v2.55.1`, `grafana/grafana:11.4.0`, `grafana/loki:3.3.2`, `grafana/tempo:2.6.1` and `otel/opentelemetry-collector-contrib:0.114.0`, each with a digest. The latest stable releases on 2026-10-09 (GitHub `releases/latest` of each project, read with `curl`): Prometheus v3.15.0 (2026-09-25), Grafana v13.2.3 (2026-09-29), Loki v3.7.8 (2026-09-17), Tempo v3.1.0 (2026-09-29) and the collector releases v0.162.0 (2026-09-29). These are the values of that day only. Task 18.1 reads the latest stable release of each again at implementation time and pins it by version and digest, the form every image of `compose.yaml` already has. The same programs run in the Helm chart of `plan-scaled-deployment` (build group 5, its D9), whose dependency charts follow the same rule, so Compose and the chart run the same programs.

What each upgrade changes in this stack, read on 2026-10-09 from the vendors' upgrade guides:

- Prometheus 2 to 3, "Prometheus 3.0 migration guide" (`https://github.com/prometheus/prometheus/blob/main/docs/migration.md`, through Context7 `/prometheus/prometheus` and the raw file). "Prometheus v3 is more strict concerning the Content-Type header received when scraping ... Prometheus v3 will now fail the scrape in such cases", so every scrape target of `prometheus.yaml` (the agent, the weather MCP server, the four Python services, Qdrant, the exporters) is checked live to answer with a supported Content-Type, and a target that does not gets `fallback_scrape_protocol` on its job. "In Prometheus v3 these label values will always be normalized to a float like representation", so a dashboard or rule that names an integer `le` or `quantile` value is fixed (the dashboards of section 13 use `histogram_quantile`, which is not affected, checked again in the files). The feature flag `expand-external-labels` became the default behaviour, which leaves the rendering of `prometheus.yaml` by the entrypoint script of D16 and D17 unchanged, because the scrape and evaluation intervals are still not expanded. "a Prometheus v3 TSDB can only be read by a Prometheus v2.55 or newer", and the stack already runs v2.55.1, so the `prometheus-data` volume is kept. The entrypoint script of D16 needs `sh` in the new image, checked first.
- Grafana 11 to 13, the upgrade guides `https://grafana.com/docs/grafana/latest/upgrade-guide/upgrade-v12.0/` and `https://grafana.com/docs/grafana/latest/upgrade-guide/upgrade-v13.0/` (read on 2026-10-09, the v12 page also through Context7 `/websites/grafana_grafana`). Grafana 12 turns `failWrongDSUID` on, which refuses a data source whose uid is not letters, digits, `-` and `_` of at most 40 characters: the provisioned uids `prometheus`, `loki` and `tempo` pass. Grafana 13: "Data source APIs that reference data sources by numeric id ... In Grafana 13, they're disabled by default" (no request of this change uses a numeric id), the legacy `/api` endpoints "are not being disabled for the moment" (the Bruno requests of task 17.2 read `/api/frontend/settings` and `/api/search` and write `/api/dashboards/db`, checked live), "Grafana v13.0 automatically migrates folders and dashboards from the legacy SQL database to unified storage on startup" (the `grafana-data` volume holds SQLite, so a `database is locked` error is handled as the guide says), and "The grafana-cli and grafana-server commands ... are removed in Grafana v13.0" (no compose line uses them). The platform specs run `wget` inside the `grafana` container, so the new image is checked for it.
- Loki 3.3 to 3.7, the upgrade guide `https://github.com/grafana/loki/blob/main/docs/sources/setup/upgrade/_index.md` (raw file read on 2026-10-09, sections 3.4.0 to 3.6.0 and "Main / Unreleased"). 3.4.0 adds the Thanos storage clients as an opt-in, 3.6.0 moves the S3 client to the AWS SDK v2 with no change to the user configuration, and from 3.5.8 "shell utilities like `/bin/sh` are no longer available" in the image. `loki-config.yaml` uses the filesystem store, schema `v13` and the compactor retention of D13, none of which the guide changes up to 3.7. No compose line runs a shell in the `loki` container. The guide's own check, `-print-config-stderr` of the old and the new image on the same file, is run and its difference written into the task.
- Tempo 2 to 3, "Migrate from Tempo 2.x to 3.0" (`https://github.com/grafana/tempo/blob/main/docs/sources/tempo/set-up-for-tracing/setup-tempo/migrate-to-3.md`, versionDate 2026-08-25, through Context7 `/grafana/tempo` and the raw file). "Monolithic deployments don't require Kafka or any new components beyond the binary upgrade", and the configuration is migrated with `tempo-cli migrate config --mode=monolithic` or by hand: "remove the `ingester:`, `ingester_client:`, `compactor:`, and `metrics_generator_client:` blocks". `tempo-config.yaml` has two of them, so two settings of D17 move: `TEMPO_BLOCK_RETENTION` (D13) goes to the block retention of the backend scheduler and backend worker, which "replace the compactor for block compaction and retention" (the Tempo 3 configuration examples show `backend_scheduler.provider.compaction.compaction.block_retention` and `backend_worker.compaction.block_retention`), and `TEMPO_MAX_BLOCK_DURATION` goes to `live_store.max_block_duration`, where the live store now cuts blocks (reference default `30s`). Both keep their names and defaults (`2160h` and `5m`), and their rows in the configuration reference change only the place they land. "There is no supported downgrade path from 3.0 to 2.x", and "TraceQL metrics queries only read RF1 blocks", so TraceQL metrics cover only traces written after the upgrade, while search and trace by id cover the whole history. Tempo 3.1 writes `vParquet5` blocks by default and reads the older ones.
- OpenTelemetry collector 0.114 to the latest release, the collector `CHANGELOG.md` (through Context7 `/open-telemetry/opentelemetry-collector`): "Rename `otlp` exporter to `otlp_grpc` exporter and add deprecated alias `otlp`", so the exporter `otlp/tempo` becomes `otlp_grpc/tempo`. Every changelog entry marked breaking between the two versions, of the core and the contrib repository, is read for each component the config uses (`otlp` receiver, `memory_limiter`, `batch`, `otlp_grpc`, `otlphttp`, `filelog` with the `container` operator, `receiver_creator`, `docker_observer`) and written into the task, and the `${env:VAR:-default}` form of D17 is checked again on the new version.

Order: task 18.1 runs after the setting tasks of D17 (1.9, 1.10, 8.8, 9.11, 9.12, 15.7) and the log pipeline tasks 8.6, 8.7, 9.9 and 9.10, so it migrates the final configuration files, and before the live specs of section 17 and the load test of task 15.5, so they run against the new programs. The upgrade is one commit. Rollback is the previous pins and the volumes backed up before the upgrade (Prometheus and Tempo cannot go back over their new data, the guides above).

## Owner decisions of 2026-10-08

The owner approved on 2026-10-08 the fixes of the review of the group 1 and group 2 changes of 2026-10-07.

- Item 2: the platform specs assert Grafana as the anonymous Viewer, not with `GRAFANA_ADMIN_PASSWORD` (D14). Task 17.2 is reworded, task 16.2 no longer asks to set the variable, and task 17.8 is unticked until `docs/E2E_RUN_SCENARIOS.md` no longer names the Grafana password as a credential.
- Item 4: the evidence lines of tasks 17.1 and 17.9 describe the dash characters in words.
- Item 13: the prompt cache scenarios of `specs/service-metrics/spec.md` name `prompt_cache_tokens_total`, the name the runtime exposes and the Token Cost dashboard queries.
- Item 14: D5 lists `not_found` in the `outcome` set, as the spec does.
- Item 23: the task counts in `openspec/BUILD_ORDER.md` are recounted from this file.

Answers of the planning round of 2026-10-08 (answers 87 to 93):

- Answer 89.12: logs go through the OpenTelemetry collector to Loki and Vector is removed, with every label and log feature Vector gave (D15, D8 superseded). Vector was already built, so done tasks 8.1, 8.3, 8.4, 9.3, 9.4, 14.1, 16.2 and 17.9 keep their ticks and get the rework tasks 8.6, 8.7, 9.9, 9.10, 14.6, 16.5 and 17.10.
- Answer 89.13: one price source. Prometheus records the rates from `pricing.yaml` and the Token Cost dashboard multiplies by that series, with no copy in `token-cost.json` (D16). The false scenario of the spec is fixed. Done tasks 13.4 and 14.3 get the rework tasks 13.11 and 14.6. The move of the file by `add-agent-subagents` task 1.4 also moves the price rule input (sent through `inbox93`).
- Answer 89.14: `add-ascend-python-common` owns it. In this change the span requirement of `specs/service-metrics/spec.md` and D7 and D9 now say that a service exports its traces whenever its OTLP endpoint is set, that OpenTelemetry's standard `OTEL_SDK_DISABLED` switches a Python service off, and that no service reads a custom `OTEL_ENABLED`.
- Answer 91.3: the trace reaching Tempo is checked once, by the AI-run spec of task 17.7, which also takes the observation wiring clause of task 9.7. Open tasks 9.7, 9.8 and 15.4 are removed. The one-off smoke checks that the platform specs of group 17 repeat on every sweep are removed too (tasks 2.6, 7.4, 8.5, 12.5, 13.7 and 15.1). No platform spec is dropped.
- Answer 93: the `service` tag is set only by `management.metrics.tags` in `application.yaml` (C1), the gauge `rag.last_top_score` is dropped because the histogram `rag.top_score` holds the same data (C2), the counter `prompt_cache.tokens.total` is dropped because it equals the `input` series of `gen_ai.client.token.usage` in the code (C2, checked in both strategies), and the stub gauge `chat.history.size`, the setting `app.metrics.user-gauge.max-tracked` and the `user_id` exception of the spec are dropped (B10). Tasks 2.7, 4.7, 6.7, 13.9, 13.10, 14.6 and 15.8. In passing, the spec now names the tags `gen_ai.client.token.usage` really has (`gen_ai_system`, `gen_ai_request_model`, `gen_ai_token_type`) and says that `GenAiTokenUsageRecorder` records it.
- Answer 87 (rule R1): several agent and several ascend-web-hunter containers run at once. Prometheus finds every container of a service through DNS service discovery (task 2.8, reworking the scrape jobs of tasks 2.5, 7.3, 10.7 and 11.1 to 11.3), so each instance is its own target. The log label `service` comes from the compose service name, so every instance of a service shares it (D15). Nothing else in this change keeps state across instances.
- Answer 85.1: every key and secret is read from the repository `.env`, never set in the shell. Task 16.5 reads `SEARXNG_SECRET` from `.env`, and the postgres exporter credentials of task 12.2 already come from `.env`. No other task of this change sets a secret.

Answer 94.5: the new change `scale-ocr-and-audio-across-containers` takes build group 3, position 5, directly after `harden-cloud-deployment`, so `add-deployment-modules` is now position 6, `add-shared-scheduler` 7, `add-document-management-api` 8 and `add-chat-streaming-and-conversations` 9 (`openspec/BUILD_ORDER.md`). Every position of those changes that this change names was moved by one. Nothing else in this change changes.

Answer 95.2: the panel of the RAG Quality dashboard that replaces the dropped gauge `rag.last_top_score` reads the 95th percentile of the `rag_top_score` histogram per provider over the last 5 minutes, `histogram_quantile(0.95, sum by (provider, le) (rate(rag_top_score_bucket[5m])))`, and names that query in its description (task 13.10).

Answer 98: every operational value of this change is a setting with its default in the compose line and in the configuration file or code (D17, which lists each setting with its default and the values kept as constants with the reason). Done tasks keep their ticks and get rework tasks: 1.1 and 1.4 get 1.9 (Prometheus), 1.2, 1.3 and 1.5 get 1.10 (Grafana), 8.1 and 8.2 get 8.8 (Loki), 9.1 and 9.2 get 9.11 (Tempo), 9.3 and 9.4 get 9.12 (the collector), 9.6 gets 9.13 (ascend-weather-mcp tracing defaults in code), 10.4 gets 10.9 and 11.1 to 11.3 get 11.7 (the OTLP endpoint of the Python services), 12.1 and 12.2 get 12.6 (the exporter addresses), and 12.3 gets 1.9 (the Qdrant target). Open tasks 9.5 (the code defaults of the agent) and 15.7 (no `.env.example` line for the retention settings) changed, and task 9.9 makes any value of the logs pipeline a setting. The Python OTLP endpoint has its default only in the compose line, because the variable is the switch of answer 89.14 and the standalone ascend-web-hunter bundle leaves it unset. Task 14.7 adds the rows of the configuration reference: `fix-linux-docker-host-access` (build group 1, position 4) adds the rows of every setting that exists when its section 9 inventory task lands, and this change adds the rows of a task still open then itself. Task 15.5 named the Bruno request of the removed task 9.7 and now names the file itself, `weather-mcp-prompt.yml` with provider `minimax`. No test or measurement of this change uses LM Studio as a default.

Answer 98.6 and 99.1: the one place this change said that running several copies is out of scope (the collector risk in Risks / Trade-offs) now names `plan-scaled-deployment`: company plans it later in `plan-scaled-deployment` (build group 5), this change does not wait for it. No host port range is planned.

## Owner decisions of 2026-10-09

Answer 100.6: every published host port is a setting `${<SERVICE>_HOST_PORT:-<today's port>}:<container port>`, carried by the change that first owns the compose service in build groups 1 and 2. This change already made `PROMETHEUS_HOST_PORT` (7077, task 1.9) and `GRAFANA_HOST_PORT` (7078, task 1.10) settings. It is also the first change of the two groups that touches the `ascend-agent` and `ascend-weather-mcp` services (tasks 9.5 and 9.13), so new task 9.14 adds `AGENT_HOST_PORT` (9917) and `WEATHER_MCP_HOST_PORT` (9998), with their rows in task 14.7 (the agent row in `apps/ascend-agent/docs/CONFIGURATION.md`, the weather row in `docs/CONFIGURATION.md`) and two rows in the D17 table. The container ports stay fixed. The ports of the four Python services are carried by `add-ascend-python-common`, which writes their port lines, and the ports of `docling-serve`, `unstructured-api`, `searxng` and `flaresolverr` by `fix-linux-docker-host-access`.

Answer 105.2 (owner rule: always use the latest stable version where possible): this change owns the Compose monitoring images, so the new open task 18.1 raises Prometheus, Grafana, Loki, Tempo and the OpenTelemetry collector to their latest stable release, pinned by version and digest read at implementation time, with every configuration change the new major versions need and a live check (D18, which cites the upgrade guide of each, read on 2026-10-09). The Helm chart of `plan-scaled-deployment` runs the same latest stable programs in its dependency charts, so Compose and the chart then run the same programs. No done task changes.
