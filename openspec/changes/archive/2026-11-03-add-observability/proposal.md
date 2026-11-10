## Why

AscendAI today is observable only via stdout logs. There are no counters, no histograms, no scrape endpoints, no dashboards, no traces, no centralised log search. When something misbehaves - Mem0 extraction fails to parse JSON, RAG retrieval misses, an MCP tool times out, an LLM provider rate-limits - the only signal is a WARN line that someone has to be `grep`-ing for in real time across multiple `docker logs` streams. Three concrete consequences:

1. Bug-1 (the semantic memory parse failure that triggered the `2026-05-12-fix-ascend-agent-bugs` change) was visible for an unknown amount of time before being noticed. A `memory.extraction.parse_failed` counter on a Grafana dashboard would have surfaced it within minutes of the first occurrence.
2. No way to alert on degradation. Provider-switch effects, RAG misses spiking after a re-ingest, cache-hit ratio collapsing - none of these can trigger a webhook because there's no metric to threshold.
3. No baseline for performance work. "Is RAG retrieval slow?" / "Where in a single chat turn is the latency hiding?" / "How many tokens per turn does each provider use, and what is that costing per day?" - none of these can be answered without instrumenting first.

Spring Boot already ships Micrometer. Spring AI 1.1.5, which the agent runs while this change lands, auto-instruments token usage, model-call latency, and tool-call counts via OpenTelemetry when Actuator is on the classpath. The Python services get equally lightweight `prometheus-fastapi-instrumentator` metrics and OpenTelemetry SDK traces, wired per service by this change. `add-ascend-python-common` (build group 2) later moves that wiring into its shared library. We are leaving 80% of observability on the table by not wiring these up.

## What Changes

This change wires a full observability layer into the AscendAI stack: metrics, logs, and traces in one go, plus a curated set of dashboards that target the failure modes the recent bug investigations exposed and validate the just-shipped prompt-caching savings.

Metrics layer (Prometheus + Grafana):

- ascend-agent (Spring Boot): add `spring-boot-starter-actuator` and `micrometer-registry-prometheus` dependencies. Expose `/actuator/health`, `/actuator/prometheus`, `/actuator/info` on the separate internal management port `9918` (owner decision 65.6 of 2026-10-04), never published and never routed by the gateway. Auto-pick-up Spring AI's `gen_ai.*` metrics. Add custom counters/timers/gauges for the failure modes we have already paid for once: memory extraction parse failures, memory insert failures, RAG retrieval thresholding outcomes, ingestion errors per source type, MCP tool latency. Add cache-token metrics emitted from the prompt-caching strategies so the L3 dashboard works.
- ascend-weather-mcp (Spring Boot): same Actuator + Prometheus stack, expose `/actuator/prometheus`. Minimal custom metrics (tool-call counter is enough for an MCP server).
- Python services (ascend-audio-scribe, ascend-web-hunter, ascend-memory, ascend-ocr): `/metrics` through `prometheus-fastapi-instrumentator`, wired per service in `src/main.py` (tasks 10.1 to 10.3 and 11.1 to 11.3), plus the ascend-web-hunter strategy metrics and the ascend-ocr job metrics. The other Python domain counters (transcription duration, search-result count, memory operations) and their smoke tests moved to `add-ascend-python-common` (build group 2), which replaces the per service wiring with its shared library (its D11) and adds the counters on top of it (dependency fix of 2026-10-05).
- Prometheus: new docker-compose service `prometheus` with a checked-in `infra/observability/prometheus/prometheus.yaml` that scrapes all six AscendAI services on their `/metrics` (or `/actuator/prometheus`) endpoints every 15 s, plus the data-layer prerequisites that publish metrics (Qdrant native, Redis via `redis_exporter`, Postgres via `postgres_exporter`). The S3-compatible object store publishes no Prometheus endpoint and is not scraped.
- Grafana: new docker-compose service `grafana` with anonymous read-only access on a non-conflicting port (`7078` to avoid clashing with anything), provisioned with the Prometheus datasource, the Loki datasource (logs), the Tempo datasource (traces), and six checked-in dashboards (see below).

Logs layer (OTel collector + Loki):

- The OpenTelemetry collector (the same container as the traces layer) reads the Docker logs of the six application services through its `filelog` receiver and ships them to Loki over OTLP, with the labels `service` and `source`. Zero code change in services - they just need to write to stdout (which they already do). The first build used a Vector container for this, and owner answer 89.12 of 2026-10-08 removes it, so one collection agent carries traces and logs (design D15).
- Loki container - log storage backend, single-binary mode, filesystem-backed. Queryable via Grafana's Logs panel alongside metrics on the same dashboards.
- A future migration to Datadog / CloudWatch / Splunk is an exporter change in the collector config, services untouched.

Traces layer (OTel collector + Tempo):

- OpenTelemetry Collector container - single OTLP ingestion point (gRPC `:4317` and HTTP `:4318`). Receivers: OTLP. Processors: batch, memory_limiter. Exporters: Tempo. Future Datadog / Jaeger fan-out lives here without service changes.
- Tempo container - trace storage backend, single-binary mode, filesystem-backed.
- ascend-agent + ascend-weather-mcp - Spring AI's auto-instrumentation already emits OpenTelemetry spans for every LLM call, tool call, and embedding call. Export them by setting `management.otlp.tracing.endpoint` to `http://otel-collector:4318/v1/traces` and `management.tracing.sampling.probability`. That is the Spring Boot 3.5.14 name the services run with while this change lands. Spring Boot 3.5.14 does not read `OTEL_EXPORTER_OTLP_ENDPOINT`, so both services are configured through the Spring property only. `upgrade-spring-boot-4` (build group 3) later renames the property to `management.opentelemetry.tracing.export.otlp.endpoint` (its D12 and task 11.6).
- Python services - tracing is the OpenTelemetry FastAPI instrumentation each service wires in `src/main.py` (tasks 10.3 and 11.1 to 11.3), exporting OTLP gRPC to `OTEL_EXPORTER_OTLP_ENDPOINT`. `opentelemetry-distro` and `opentelemetry-instrument` are not used. `add-ascend-python-common` later replaces the per service wiring with the tracer provider and ASGI middleware of its library (its D10).
- Why OTel over a vendor agent: Spring AI emits OTel natively; OTel collector is the industry-standard router for fan-out to any backend.

Six checked-in dashboards (provisioned in Grafana at startup):

1. Platform Overview - request rate, error rate, latency, JVM/Python memory per service.
2. AI Pipeline - tokens per minute by provider/model, provider mix, RAG hit rate, memory parse-failure rate, MCP tool latency.
3. Infrastructure - Qdrant collection sizes, Redis cache stats, Postgres connections.
4. L1 - Token Cost - per-provider $/day panel; data = `gen_ai.client.token.usage{provider="..."}` × per-provider rate (rates committed only in the YAML pricing table `infra/observability/grafana/dashboards/pricing.yaml`, which Prometheus records as the series `token_price_usd_per_1k` at start, so the dashboard holds no copy (owner answer 89.13 of 2026-10-08, design D16). `add-agent-subagents` (build group 4) later moves it to `infra/pricing/pricing.yaml` and lets the agent read it for subagent run cost).
5. L2 - RAG Quality - top-K similarity-score histogram, retrieval miss-rate over time, ingestion-events-per-hour by source type.
6. L3 - Cache Hit Rate - `cached_tokens / prompt_tokens` per provider (the prompt tokens are the `input` series of `gen_ai.client.token.usage`), plus absolute saved-token count. Validates the prompt-caching change is actually firing in production.

Documentation: a new `docs/OBSERVABILITY.md` walks through what is collected (metrics + logs + traces), how to find it in Grafana, and how to add a custom metric, log field, or span. Cross-link from the root README "Documentation" section.

Error bodies: every RFC 7807 problem body carries a `traceId` field with the id of the current trace, so an error a user reports leads straight to its trace in Tempo (owner answer 51.3 of 2026-10-03, design D12). This change records the decision and builds no field. The field is built by the changes that own the problem body shape, both later: `add-ascend-python-common` (build group 2, its D5) for the Python services and `upgrade-spring-boot-4` (build group 3, its D19) for the agent. The end to end check from a problem body to its trace moved with them (dependency fix of 2026-10-05).

Defaults: observability stack runs always-on in `compose.yaml`. The earlier draft included a `--profile no-observability` opt-out. The user dropped it as out of scope. The owner confirmed on 2026-10-03 (answer 52) that monitoring is core and never a switchable deployment module, so no observability container carries a compose profile and every service always exports its traces. The agent serves its actuator endpoints only on the internal management port `9918`, which `compose.yaml` never publishes (owner decision 65.6 of 2026-10-04, design D4). ascend-weather-mcp keeps them on its application port `9998`. Actuator exposes only `health`, `info` and `prometheus` on both.

## Relation to the planned changes

Build order (owner build order of 2026-10-04, which supersedes the earlier orders, among them the order of 2026-10-02 with owner answers 56 and 60.6 of 2026-10-03): build group 1 (finish started work), position 1. It needs no earlier change and runs against today's services (Spring Boot 3.5.14, Spring AI 1.1.5, the per service Python wiring). Later changes that plug into it:

- `add-ascend-python-common` (build group 2, position 1): moves the Python metrics and tracing wiring of this change into its library (its D10 and D11), adds the request id and the trace and span ids to Python log lines (its D7 and D8) and the `traceId` to every Python problem body (its D5). It also carries the Python domain counters, their smoke tests and the Python half of the error to trace check that moved out of this change (dependency fix of 2026-10-05).
- `add-python-runtime-upgrades` (build group 2, position 2): FastAPI's built-in telemetry stays off (its D4), so the library's ASGI middleware span is the one HTTP server span per request, and the MCP spans of FastMCP and the MCP SDK are children of that HTTP server span (its D5). No Python dashboard of this change counts FastMCP's MCP SERVER spans as HTTP requests.
- `upgrade-spring-boot-4` (build group 3, position 2): Spring Boot 4.1.1 with Micrometer 1.17.1 and Spring AI 2.0.1. It renames the OTLP property this change sets (its D12 and task 11.6), builds the `traceId` field of this change's D12 into every agent problem body (its D19), and carries the agent half of the error to trace check (former task 16.3).
- `add-deployment-modules` (build group 3, position 6): keeps observability out of its module catalog, because monitoring is core and always on (owner answer 52 of 2026-10-03). It adds no profile to the observability containers and no export switch to any service, accepts the `GRAFANA_ADMIN_PASSWORD` guard of `harden-cloud-deployment` on the always-on `grafana` service, carries the preset check of former task 16.1, and adapts the platform specs of this change to the module list.
- `add-agent-subagents` (build group 4, position 2): moves the price table to `infra/pricing/pricing.yaml` (its task 1.4), so the agent reads the same file for subagent run cost, and updates the pricing section of `docs/OBSERVABILITY.md` (part of former task 14.3).
- `add-shared-scheduler`, `add-agent-skills`, `add-agent-subagents`, `add-agent-sandbox`, `add-agent-soul`, `add-action-approvals`, `add-mcp-tool-servers`, `add-obsidian-vault`, `add-openclaw-plugin-host`, `add-coding-agent-delegation`, `add-scheduled-tasks`, `add-self-improvement` and `add-self-built-integrations` name their metrics after D2 and D5 of this change's design. This change adds no metric for them: each owns its metrics and their documentation.

## Capabilities

### New Capabilities

- `service-metrics` - every AscendAI service emits a uniform Prometheus-format metrics endpoint with framework-default metrics plus a defined minimum set of domain counters/timers, plus auto-instrumented OpenTelemetry spans.
- `observability-stack` - Prometheus + Grafana + Loki + OTel collector + Tempo run always on in `compose.yaml`, with no compose profile, with checked-in scrape config, the OTel collector pipelines for traces and logs, and six provisioned Grafana dashboards (Platform Overview, AI Pipeline, Infrastructure, Token Cost, RAG Quality, Cache Hit Rate).

### Modified Capabilities

(none - this change is additive)

## Impact

- New runtime services (seven new compose containers, after owner answer 89.12 of 2026-10-08 removed `vector`): `prometheus` (`:7077`), `grafana` (`:7078`), `loki` (`:3100` internal), `otel-collector` (`:4317`/`:4318` internal), `tempo` (`:3200` internal), `postgres-exporter`, `redis-exporter`. Combined RAM footprint at idle: ~600 MB.
- New code (ascend-agent):
  - `apps/ascend-agent/build.gradle.kts` - actuator + micrometer-prometheus + opentelemetry-exporter-otlp dependency lines.
  - `apps/ascend-agent/src/main/resources/application.yaml` - `management.endpoints.*`, `management.metrics.*` block; `OTEL_*` env defaults.
  - The common tags `service` and `version` come from `management.metrics.tags` in `application.yaml` only. The first build also had `MetricsConfig.java` with a second copy of the `service` tag and a stub gauge `chat.history.size`, both removed by owner answer 93 of 2026-10-08.
  - `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryExtractor.java` - increment `memory.extraction.parse_failed`.
  - `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryClient.java` - increment `memory.insert.failed`, time `memory.search.duration`.
  - `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/rag/RagRetrievalService.java` - counter `rag.hits.above_threshold`, histogram `rag.top_score` (for L2 dashboard). The gauge `rag.last_top_score` of the first build is dropped, because the histogram holds the same data (owner answer 93 of 2026-10-08).
  - `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/ChatExecutor.java` - timer `mcp.tool.duration` keyed by tool name.
  - `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/cache/AnthropicPromptCacheStrategy.java` - counter `prompt_cache.tokens.read{provider="anthropic"}` and `prompt_cache.tokens.creation{provider="anthropic"}` from `recordOutcome`. Powers L3 dashboard, which divides by the `input` series of `gen_ai.client.token.usage` (no separate total counter, owner answer 93 of 2026-10-08).
  - `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/cache/OpenAiPromptCacheStrategy.java` - counter `prompt_cache.tokens.read{provider}` from `recordOutcome` for OpenAI + Gemini providers.
- New code (ascend-weather-mcp): same dependency lines + actuator config.
- New code (Python services): the OpenTelemetry and Prometheus dependencies, `/metrics` and the tracing setup per service in `src/main.py` (tasks 10.1 to 10.3 and 11.1 to 11.3), the ascend-web-hunter strategy metrics and the ascend-ocr job metrics. The `ascend-python-common` library of `add-ascend-python-common` later pins these once for all four services, replaces the per service wiring and adds the remaining domain counters.
- New files:
  - `compose.yaml` - `prometheus`, `grafana`, `loki`, `otel-collector`, `tempo`, `postgres-exporter`, `redis-exporter` services, plus the existing `container-metrics-exporter` (built from `infra/observability/container-metrics-exporter/`, scraped as job `container-metrics-exporter`), which reports per-container CPU and memory because cAdvisor cannot read Docker Desktop containers.
  - `infra/observability/prometheus/prometheus.yaml`
  - `infra/observability/prometheus/price-rules.sh` (records the rates of `pricing.yaml` in Prometheus at start, design D16)
  - `infra/observability/loki/loki-config.yaml`
  - `infra/observability/otel-collector/otel-collector-config.yaml` (traces and logs pipelines, with commented placeholder exporters for Datadog / CloudWatch / Splunk)
  - `infra/observability/tempo/tempo-config.yaml`
  - `infra/observability/grafana/provisioning/datasources/datasources.yaml` (Prometheus + Loki + Tempo)
  - `infra/observability/grafana/provisioning/dashboards/dashboards.yaml`
  - `infra/observability/grafana/dashboards/platform-overview.json`
  - `infra/observability/grafana/dashboards/ai-pipeline.json`
  - `infra/observability/grafana/dashboards/infrastructure.json`
  - `infra/observability/grafana/dashboards/token-cost.json`
  - `infra/observability/grafana/dashboards/rag-quality.json`
  - `infra/observability/grafana/dashboards/cache-hit-rate.json`
  - `infra/observability/grafana/dashboards/pricing.yaml` (per-provider $/1k token rates, the only place a rate is written, recorded by Prometheus at start for the token-cost dashboard). `add-agent-subagents` task 1.4 later moves it to `infra/pricing/pricing.yaml` with every reference to it, so the agent reads it for subagent run cost too (owner decision of 2026-10-02)
  - `docs/OBSERVABILITY.md`
- Tests: smoke test that hits `/actuator/prometheus` on the agent and asserts the custom metric names exist with the expected tags; Python checks assert the `/metrics` endpoint exposes `python_info` (the custom counter checks moved to `add-ascend-python-common`); the AI-run platform spec of task 17.7, the one check that an OTel span reaches Tempo end-to-end after a chat turn (owner answer 91.3 of 2026-10-08).
- Docs: `docs/OBSERVABILITY.md` (new); link in main README's Documentation section.
- Settings: every operational value of the stack (intervals, limits, retention, published ports, collector and data store addresses) is read from an environment variable that `compose.yaml` passes as `${VAR:-default}`, with the same default in the configuration file or the code, and each setting gets its row in the configuration reference (owner rule 98 of 2026-10-08, design D17, tasks 1.9, 1.10, 8.8, 9.5, 9.11 to 9.13, 10.9, 11.7, 12.6, 14.7 and 15.7).
- Backwards compat: fully additive. No public API changes. Existing logging is unchanged (now also shipped to Loki by the OTel collector). Stack is always-on (no profile and no opt-out profile, per user direction and owner answer 52). The `traceId` field that the later changes add to the problem body is an extra field, so a client that reads only the known fields is unaffected.
- Image versions: the five monitoring images (Prometheus, Grafana, Loki, Tempo, the OpenTelemetry collector) run their latest stable release, pinned by version and digest at implementation time, with every configuration change their upgrade guides require (owner rule 105.2 of 2026-10-09, design D18, task 18.1). The Helm chart of `plan-scaled-deployment` runs the same programs.
- Performance overhead: Micrometer counters are nanosecond-scale. Prometheus scrape every 15 s. The OTel collector reads the Docker log files; sub-millisecond per log line. OTel spans are batched; the LLM calls already dominate latency. Negligible.

## Relevant Skills

Load these from `.agents/skills/` before implementing this change:

- `springboot-patterns` and `java-coding-standards` for Actuator, Micrometer and OTLP tracing in ascend-agent and ascend-weather-mcp
- `python-patterns` for the Python service metrics and their tests
- `docker-patterns` for the compose services and exporters
- `tdd-workflow` for the metric tests written before the code changes
- `e2e-runbooks` for the platform specs of task group 17 and the 15.5 load test
- `markdown-writer` for `docs/OBSERVABILITY.md`
