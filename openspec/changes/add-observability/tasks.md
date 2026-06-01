## 1. Bring up Prometheus + Grafana with empty scrape config

- [ ] 1.1 Create `observability/prometheus/prometheus.yaml` with `global.scrape_interval: 15s`, an empty `scrape_configs` list, and external labels `{cluster: "ascend-ai-local"}` (note: `.yaml` extension to match repo convention)
- [ ] 1.2 Create `observability/grafana/provisioning/datasources/datasources.yaml` declaring three datasources (`Prometheus` → `http://prometheus:9090`, `Loki` → `http://loki:3100`, `Tempo` → `http://tempo:3200`); `Prometheus` marked default
- [ ] 1.3 Create `observability/grafana/provisioning/dashboards/dashboards.yaml` that mounts `/var/lib/grafana/dashboards/` as the dashboard provider
- [ ] 1.4 Add `prometheus` service to `docker-compose.yaml` (image `prom/prometheus:v2.55.x`, volume mount config, port `9090`, command flag `--storage.tsdb.retention.time=72h`)
- [ ] 1.5 Add `grafana` service to `docker-compose.yaml` (image `grafana/grafana:11.x.x`, volume mounts for provisioning + dashboards directory, port `3030:3000`, env `GF_AUTH_ANONYMOUS_ENABLED=true`, `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer`)
- [ ] 1.6 Smoke test: `docker compose up -d prometheus grafana`, confirm `http://localhost:9090/-/ready` returns 200 and `http://localhost:3030/api/health` returns 200
- [ ] 1.7 Both services start by default (no profile attribute) — observability is always-on per user direction

## 2. Wire AscendAgent (Spring Boot) — metrics

- [ ] 2.1 Add `org.springframework.boot:spring-boot-starter-actuator` and `io.micrometer:micrometer-registry-prometheus` to `AscendAgent/build.gradle.kts`
- [ ] 2.2 In `AscendAgent/src/main/resources/application.yaml`, add `management.endpoints.web.exposure.include: health,info,prometheus`, `management.endpoint.health.show-details: when-authorized`, `management.metrics.tags.service: ascend-agent`, `management.metrics.tags.version: @project.version@`
- [ ] 2.3 Enable `processResources` filtering for `application.yaml` in `build.gradle.kts` so `@project.version@` resolves at build time
- [ ] 2.4 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/MetricsConfig.java` with a `MeterRegistryCustomizer<MeterRegistry>` bean that applies common tags (`service`, `version`) globally
- [ ] 2.5 Add scrape job for AscendAgent to `observability/prometheus/prometheus.yaml`: `job_name: ascend-agent`, `metrics_path: /actuator/prometheus`, `static_configs.targets: [host.docker.internal:9917]`
- [ ] 2.6 Smoke test: hit `http://localhost:9917/actuator/prometheus`, confirm body contains `jvm_memory_used_bytes`, `gen_ai_client_token_usage_total` (after one prompt), and the `service="ascend-agent"` tag appears on every line

## 3. Custom metrics — semantic memory

- [ ] 3.1 Inject `MeterRegistry` into `SemanticMemoryExtractor`
- [ ] 3.2 In the parse-failure branch (after the JSON-array extractor returns empty), increment `Counter` `memory.extraction.parse_failed` with tags `provider`, `model`
- [ ] 3.3 Inject `MeterRegistry` into `SemanticMemoryClient`
- [ ] 3.4 Wrap `performInsertCall` in a `try` that on failure increments `memory.insert.failed` with tags `embedding_provider`, `reason` (closed set: `4xx`, `5xx`, `timeout`, `connect_error`); the throw behavior unchanged
- [ ] 3.5 Wrap `performSearchCall` in a `Timer.Sample`; stop the sample with `memory.search.duration` keyed by `embedding_provider` and `outcome`
- [ ] 3.6 Test (`SemanticMemoryClientMetricsTest`): force a 5xx response, assert `memory_insert_failed_total{reason="5xx"}` increments by 1
- [ ] 3.7 Test (`SemanticMemoryExtractorMetricsTest`): feed a thinking-prose-only response, assert `memory_extraction_parse_failed_total{provider="<p>"}` increments by 1

## 4. Custom metrics — RAG retrieval

- [ ] 4.1 Inject `MeterRegistry` into `RagRetrievalService`
- [ ] 4.2 After Qdrant search, count hits as `rag.retrieval.hits` with tag `above_threshold` set per-hit (`true`/`false`) — split increments per bucket
- [ ] 4.3 Wrap retrieval call in `Timer.Sample`; record `rag.retrieval.duration` keyed by `provider`, `outcome`
- [ ] 4.4 Publish a gauge `rag.last_top_score` from the highest-scoring hit on the most recent query, keyed by `provider` (use `MultiGauge` for per-provider lookup)
- [ ] 4.5 Publish a histogram `rag.top_score` of every hit's score keyed by `provider` for the L2 dashboard score-distribution heatmap
- [ ] 4.6 Test (`RagRetrievalServiceMetricsTest`): mock Qdrant returning 5 hits with scores `[0.91, 0.85, 0.80, 0.74, 0.60]` and threshold `0.75`; assert above_threshold counter incremented by 3 and below_threshold by 2

## 5. Custom metrics — MCP tool calls

- [ ] 5.1 In the MCP tool invocation path (likely `ChatExecutor` or its tool-callback wrapper), wrap each tool invocation in `Timer.Sample`
- [ ] 5.2 Record `mcp.tool.duration` keyed by `tool` (the MCP tool's logical name) and `outcome` (`ok`, `error`, `timeout`)
- [ ] 5.3 Test (`McpToolMetricsTest`): mock a slow + a fast + a failing tool; assert all three timer buckets increment correctly

## 6. Custom metrics — prompt-cache (powers L3 dashboard)

- [ ] 6.1 Inject `MeterRegistry` into `AnthropicPromptCacheStrategy`
- [ ] 6.2 In `recordOutcome(...)`, increment `prompt_cache.tokens.read{provider="anthropic"}` by `cacheReadInputTokens`, `prompt_cache.tokens.creation{provider="anthropic"}` by `cacheCreationInputTokens`, `prompt_cache.tokens.total{provider="anthropic"}` by `promptTokens`
- [ ] 6.3 Inject `MeterRegistry` into `OpenAiPromptCacheStrategy`
- [ ] 6.4 In `recordOutcome(...)`, increment `prompt_cache.tokens.read{provider}` by `cachedTokens` (where `provider` is the strategy's constructor-injected provider name — `openai` or `gemini`), `prompt_cache.tokens.total{provider}` by `promptTokens`. (No `creation` counter — OpenAI/Gemini cache writes are implicit, not surfaced.)
- [ ] 6.5 Test (`AnthropicPromptCacheStrategyMetricsTest`): stub a response with `cacheReadInputTokens=487`, assert all three counters increment correctly
- [ ] 6.6 Test (`OpenAiPromptCacheStrategyMetricsTest`): stub a response with `cachedTokens=512`, assert read + total counters increment

## 7. Wire WeatherMCP (Spring Boot template)

- [ ] 7.1 Add Actuator + Prometheus dependencies to `WeatherMCP/build.gradle.kts`
- [ ] 7.2 Mirror `application.yaml` management block from AscendAgent with `service: weather-mcp`
- [ ] 7.3 Add scrape job `weather-mcp` to `observability/prometheus/prometheus.yaml`
- [ ] 7.4 Smoke test: `/actuator/prometheus` reachable, `service="weather-mcp"` tag present

## 8. Logs layer — Vector + Loki

- [ ] 8.1 Create `observability/loki/loki-config.yaml` (single-binary mode, filesystem store, retention 168h)
- [ ] 8.2 Add `loki` service to `docker-compose.yaml` (image `grafana/loki:3.x.x`, volume mount config, port `3100` docker-network only)
- [ ] 8.3 Create `observability/vector/vector.toml` with: `[sources.docker]` reading via `docker_logs` source for the six AscendAI services; `[sinks.loki]` shipping to `http://loki:3100` with labels `service`, `source`. Add commented placeholder sinks for Datadog / CloudWatch / Splunk to document the migration story.
- [ ] 8.4 Add `vector` service to `docker-compose.yaml` (image `timberio/vector:0.42.x-alpine`, volume mount config, mount `/var/run/docker.sock:/var/run/docker.sock:ro`)
- [ ] 8.5 Smoke test: tail a log line in any AscendAI service container, then query Loki via Grafana Logs panel: `{service="ascend-agent"}` should return the line within 5 seconds

## 9. Traces layer — OTel collector + Tempo

- [ ] 9.1 Create `observability/tempo/tempo-config.yaml` (single-binary mode, filesystem store, retention 168h, OTLP receiver on `:4317`)
- [ ] 9.2 Add `tempo` service to `docker-compose.yaml` (image `grafana/tempo:2.x.x`, volume mount config, port `3200` docker-network only, OTLP `4317` docker-network only)
- [ ] 9.3 Create `observability/otel-collector/otel-collector-config.yaml` with OTLP receivers (gRPC `:4317`, HTTP `:4318`), `batch` + `memory_limiter` processors, OTLP exporter to Tempo
- [ ] 9.4 Add `otel-collector` service to `docker-compose.yaml` (image `otel/opentelemetry-collector-contrib:0.x.x`, volume mount config, ports `4317` + `4318` docker-network only)
- [ ] 9.5 In `AscendAgent/src/main/resources/application-docker.yaml`, set `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`, `OTEL_SERVICE_NAME=ascend-agent`, `OTEL_RESOURCE_ATTRIBUTES=service.version=@project.version@`
- [ ] 9.6 Same for `WeatherMCP/src/main/resources/application-docker.yaml` with `OTEL_SERVICE_NAME=weather-mcp`
- [ ] 9.7 Verify Spring AI's existing OTel integration emits spans for LLM/tool calls without further wiring (Spring AI 1.1 ships OTel auto-instrumentation when the OTel BOM is on the classpath via Spring AI's transitive deps)
- [ ] 9.8 Smoke test: send one chat prompt via AscendAgent → query Tempo via Grafana Explore: search by `service.name=ascend-agent` → expect a single trace with spans for the LLM call

## 10. Wire AscendMemory (Python — metrics + traces)

- [ ] 10.1 Add `prometheus-fastapi-instrumentator`, `opentelemetry-distro`, `opentelemetry-exporter-otlp` to `AscendMemory/pyproject.toml`
- [ ] 10.2 In `AscendMemory/src/main.py`, after FastAPI app construction: `Instrumentator().instrument(app).expose(app)` for `/metrics`
- [ ] 10.3 Activate OTel auto-instrumentation: either run uvicorn under `opentelemetry-instrument` in the Dockerfile entrypoint, OR add `from opentelemetry.instrumentation.auto_instrumentation import sitecustomize` import shim
- [ ] 10.4 Set OTel env in `docker-compose.yaml` for the service: `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`, `OTEL_SERVICE_NAME=ascend-memory`
- [ ] 10.5 Add a small `metrics.py` module that defines `Counter("memory_operations_total", ["operation","outcome"])` and `Histogram("memory_search_duration_seconds", ["embedding_provider"])`
- [ ] 10.6 Wire counter/histogram increments into the REST handlers in `src/api/rest/rest_endpoints.py`
- [ ] 10.7 Add scrape job `ascend-memory` to `observability/prometheus/prometheus.yaml`
- [ ] 10.8 Smoke test: `GET http://localhost:7020/metrics` returns 200 and includes `python_info{...}` plus `memory_operations_total`. Also send one search request → confirm Tempo has a trace with `service.name=ascend-memory`.

## 11. Wire AudioScribe, AscendWebSearch, PaddleOCR (Python repetition)

- [ ] 11.1 AudioScribe: dependencies, `Instrumentator(...).expose(app)`, OTel auto-instrumentation, `transcription_duration_seconds` + `transcription_audio_duration_seconds` histograms, scrape job
- [ ] 11.2 AscendWebSearch: dependencies, expose, OTel, `search_results_returned` histogram + `extraction_tier_used_total` counter + `extraction_captcha_intervention_total` counter, scrape job
- [ ] 11.3 PaddleOCR: dependencies, expose, OTel, `ocr_pages_processed_total` counter + `ocr_duration_seconds` histogram, scrape job
- [ ] 11.4 Smoke test for each: `GET /metrics` returns 200 with the expected custom metric names; one request per service produces a trace in Tempo

## 12. Data-layer exporters

- [ ] 12.1 Add `redis_exporter` (`oliver006/redis_exporter:v1.65.x`) to docker-compose pointed at `redis:6379`; add scrape job
- [ ] 12.2 Add `postgres_exporter` (`prometheuscommunity/postgres-exporter:v0.16.x`) wired with `DATA_SOURCE_NAME` for the `ascend_ai` database; add scrape job
- [ ] 12.3 Confirm Qdrant `:6333/metrics` endpoint is reachable (it ships built-in); add scrape job
- [ ] 12.4 Confirm MinIO Prometheus output is reachable on `:9070/minio/v2/metrics/cluster` (built-in); add scrape job. Use docker-compose env interpolation if auth needed.
- [ ] 12.5 Smoke test: every data-layer target reports `health=up` in `http://localhost:9090/api/v1/targets`

## 13. Provision dashboards (six total)

- [ ] 13.1 Build `observability/grafana/dashboards/platform-overview.json` with panels: request rate per service, error rate per service, p95 latency per service, JVM heap, Python RSS
- [ ] 13.2 Build `observability/grafana/dashboards/ai-pipeline.json` with panels: tokens per minute by provider/model, provider mix, RAG hit-rate, memory parse-failure rate, MCP tool call rate
- [ ] 13.3 Build `observability/grafana/dashboards/infrastructure.json` with panels: Qdrant collection point counts, Redis ops/sec + used memory, Postgres connections + db size, MinIO bucket sizes
- [ ] 13.4 **L1 — Token Cost** (`observability/grafana/dashboards/token-cost.json`): per-provider $/day computed via `gen_ai.client.token.usage{provider="...",type="input"} × pricing_input + ... type="output" × pricing_output`. Pricing rates committed in `observability/grafana/dashboards/pricing.yaml` keyed by provider; loaded into the dashboard via JSON variable substitution at build time
- [ ] 13.5 **L2 — RAG Quality** (`observability/grafana/dashboards/rag-quality.json`): heatmap of `rag_top_score_bucket` over time, time-series of miss-rate (`rag.retrieval.hits{above_threshold="false"} / sum(rag.retrieval.hits)`), bar chart of ingestion-events-per-hour by `source_type`. Logs panel below querying Loki for `{service="ascend-agent"} |~ "Retrieval:"`
- [ ] 13.6 **L3 — Cache Hit Rate** (`observability/grafana/dashboards/cache-hit-rate.json`): primary panel `rate(prompt_cache.tokens.read[5m]) / rate(prompt_cache.tokens.total[5m])` per provider; side panel absolute saved-token count `rate(prompt_cache.tokens.read[1h]) * 3600` per provider; flat-line-at-zero alert annotation (UI only, no Alertmanager)
- [ ] 13.7 Verify each dashboard renders non-empty data after running representative traffic
- [ ] 13.8 Sanity-check dashboard portability: each panel JSON cites its underlying metric/log/trace query in a description field; no hard-coded datasource UIDs other than the provisioned `Prometheus` / `Loki` / `Tempo` names

## 14. Documentation

- [ ] 14.1 Author `docs/OBSERVABILITY.md`: stack overview (three pillars), what each dashboard shows, how to access Prometheus / Grafana / Loki / Tempo, how to add a custom metric in Java (snippet) and Python (snippet), how to add a span attribute, the cardinality discipline rules from D5, the Vector → Datadog migration recipe
- [ ] 14.2 Add a "Metrics Inventory" table to OBSERVABILITY.md listing every custom metric, type, tags, and the dashboard(s) that use it — so renaming a metric flags downstream impact
- [ ] 14.3 Add a "Pricing Rates" section explaining how to update `observability/grafana/dashboards/pricing.yaml` when provider pricing changes (commit + restart Grafana to reload)
- [ ] 14.4 Update root `README.md` Documentation section to link `docs/OBSERVABILITY.md`
- [ ] 14.5 Add a one-liner to each module's `AGENTS.md` referencing OBSERVABILITY.md for instrumenting new code

## 15. Hardening and verification

- [ ] 15.1 Confirm `/actuator/env`, `/actuator/heapdump`, `/actuator/threaddump`, `/actuator/loggers`, `/actuator/caches` return 404 by default on AscendAgent and WeatherMCP
- [ ] 15.2 Add Spring Boot integration test `MetricsEndpointIT` that asserts `/actuator/prometheus` returns 200 and contains the names of every custom metric defined in this change (including the three new prompt-cache counters)
- [ ] 15.3 Add Python integration test per service asserting `/metrics` returns 200 and includes the custom metric names
- [ ] 15.4 Add an integration test `OtelTraceShipsToTempoIT` that sends one chat prompt via AscendAgent, polls Tempo for a trace with `service.name=ascend-agent`, asserts the trace has at least one LLM-call span
- [ ] 15.5 Run a 30-minute load test and observe Prometheus + Loki + Tempo disk growth stays bounded under their respective retention windows; document expected steady-state size in OBSERVABILITY.md
- [ ] 15.6 Update `openspec/changes/add-observability/tasks.md` checkboxes as work proceeds
