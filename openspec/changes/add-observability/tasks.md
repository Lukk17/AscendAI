## 1. Bring up Prometheus + Grafana with empty scrape config

- [ ] 1.1 Create `observability/prometheus/prometheus.yml` with `global.scrape_interval: 15s`, an empty `scrape_configs` list, and external labels `{cluster: "ascend-ai-local"}`
- [ ] 1.2 Create `observability/grafana/provisioning/datasources/prometheus.yml` pointing the default datasource at `http://prometheus:9090`
- [ ] 1.3 Create `observability/grafana/provisioning/dashboards/dashboards.yml` that mounts `/var/lib/grafana/dashboards/` as the dashboard provider
- [ ] 1.4 Add `prometheus` service to `docker-compose.yaml` (image `prom/prometheus:v2.55.x`, volume mount config, port `9090`, command flag `--storage.tsdb.retention.time=72h`, profile attribute as in D7)
- [ ] 1.5 Add `grafana` service to `docker-compose.yaml` (image `grafana/grafana:11.x.x`, volume mounts for provisioning + dashboards directory, port `3030:3000`, env `GF_AUTH_ANONYMOUS_ENABLED=true`, `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer`, profile attribute)
- [ ] 1.6 Smoke test: `docker compose up -d prometheus grafana`, confirm `http://localhost:9090/-/ready` returns 200 and `http://localhost:3030/api/health` returns 200
- [ ] 1.7 Verify opt-out: `docker compose --profile no-observability up -d` does NOT start prometheus or grafana

## 2. Wire AscendAgent (Spring Boot) — primary target

- [ ] 2.1 Add `org.springframework.boot:spring-boot-starter-actuator` and `io.micrometer:micrometer-registry-prometheus` to `AscendAgent/build.gradle.kts`
- [ ] 2.2 In `AscendAgent/src/main/resources/application.yaml`, add `management.endpoints.web.exposure.include: health,info,prometheus`, `management.endpoint.health.show-details: when-authorized`, `management.metrics.tags.service: ascend-agent`, `management.metrics.tags.version: @project.version@`
- [ ] 2.3 Enable `processResources` filtering for `application.yaml` in `build.gradle.kts` so `@project.version@` resolves at build time
- [ ] 2.4 Create `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/MetricsConfig.java` with a `MeterRegistryCustomizer<MeterRegistry>` bean that applies common tags (`service`, `version`) globally
- [ ] 2.5 Add scrape job for AscendAgent to `observability/prometheus/prometheus.yml`: `job_name: ascend-agent`, `metrics_path: /actuator/prometheus`, `static_configs.targets: [host.docker.internal:9917]`
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
- [ ] 4.5 Test (`RagRetrievalServiceMetricsTest`): mock Qdrant returning 5 hits with scores `[0.91, 0.85, 0.80, 0.74, 0.60]` and threshold `0.75`; assert above_threshold counter incremented by 3 and below_threshold by 2

## 5. Custom metrics — MCP tool calls

- [ ] 5.1 In the MCP tool invocation path (likely `ChatExecutor` or its tool-callback wrapper), wrap each tool invocation in `Timer.Sample`
- [ ] 5.2 Record `mcp.tool.duration` keyed by `tool` (the MCP tool's logical name) and `outcome` (`ok`, `error`, `timeout`)
- [ ] 5.3 Test (`McpToolMetricsTest`): mock a slow + a fast + a failing tool; assert all three timer buckets increment correctly

## 6. Wire WeatherMCP (Spring Boot template)

- [ ] 6.1 Add Actuator + Prometheus dependencies to `WeatherMCP/build.gradle.kts`
- [ ] 6.2 Mirror `application.yaml` management block from AscendAgent with `service: weather-mcp`
- [ ] 6.3 Add scrape job `weather-mcp` to `observability/prometheus/prometheus.yml`
- [ ] 6.4 Smoke test: `/actuator/prometheus` reachable, `service="weather-mcp"` tag present

## 7. Wire AscendMemory (Python template)

- [ ] 7.1 Add `prometheus-fastapi-instrumentator` to `AscendMemory/pyproject.toml`
- [ ] 7.2 In `AscendMemory/src/main.py`, after FastAPI app construction: `Instrumentator().instrument(app).expose(app)`
- [ ] 7.3 Add a small `metrics.py` module that defines `Counter("memory_operations_total", ["operation","outcome"])` and `Histogram("memory_search_duration_seconds", ["embedding_provider"])`
- [ ] 7.4 Wire counter/histogram increments into the REST handlers in `src/api/rest/rest_endpoints.py`
- [ ] 7.5 Add scrape job `ascend-memory` to `observability/prometheus/prometheus.yml`
- [ ] 7.6 Smoke test: `GET http://localhost:7020/metrics` returns 200 and includes `python_info{...}` plus `memory_operations_total`

## 8. Wire AudioScribe, AscendWebSearch, PaddleOCR (Python repetition)

- [ ] 8.1 AudioScribe: dependency, `Instrumentator(...).expose(app)`, custom `transcription_duration_seconds` histogram + `transcription_audio_duration_seconds` histogram, scrape job
- [ ] 8.2 AscendWebSearch: dependency, expose, custom `search_results_returned` histogram + `extraction_tier_used_total` counter + `extraction_captcha_intervention_total` counter, scrape job
- [ ] 8.3 PaddleOCR: dependency, expose, custom `ocr_pages_processed_total` counter + `ocr_duration_seconds` histogram, scrape job
- [ ] 8.4 Smoke test for each: `GET /metrics` returns 200 with the expected custom metric names

## 9. Data-layer exporters

- [ ] 9.1 Add `redis_exporter` (`oliver006/redis_exporter:v1.65.x`) to docker-compose pointed at `redis:6379`; add scrape job
- [ ] 9.2 Add `postgres_exporter` (`prometheuscommunity/postgres-exporter:v0.16.x`) wired with `DATA_SOURCE_NAME` for the `ascend_ai` database; add scrape job
- [ ] 9.3 Confirm Qdrant `:6333/metrics` endpoint is reachable (it ships built-in); add scrape job
- [ ] 9.4 Confirm MinIO Prometheus output is reachable on `:9070/minio/v2/metrics/cluster` (built-in, requires JWT or anonymous mode); add scrape job. If JWT required, document the auth approach in OBSERVABILITY.md but do NOT bake credentials into the scrape config — use docker-compose env interpolation
- [ ] 9.5 Smoke test: every data-layer target reports `health=up` in `http://localhost:9090/api/v1/targets`

## 10. Provision dashboards

- [ ] 10.1 Build `observability/grafana/dashboards/platform-overview.json` with panels: request rate per service (PromQL: `sum by (service) (rate(http_server_requests_seconds_count[1m]))` for Java + `rate(http_requests_total[1m])` for Python), error rate per service, p95 latency per service, JVM heap, Python RSS
- [ ] 10.2 Build `observability/grafana/dashboards/ai-pipeline.json` with panels: tokens per minute by model (`sum by (model,type) (rate(gen_ai_client_token_usage_total[1m]))`), provider mix (pie chart), RAG hit-rate (`sum(rate(rag_retrieval_hits_total{above_threshold="true"}[1m])) / sum(rate(rag_retrieval_hits_total[1m]))`), memory parse-failure rate, MCP tool call rate
- [ ] 10.3 Build `observability/grafana/dashboards/infrastructure.json` with panels: Qdrant collection point counts, Redis ops/sec + used memory, Postgres connections + db size, MinIO bucket sizes
- [ ] 10.4 Verify each dashboard renders non-empty data after running the bug-1 / bug-2 / bug-3 / bug-4 reproduction curls (or any synthetic prompt traffic)
- [ ] 10.5 Sanity-check dashboard portability: each panel JSON cites its underlying metric in a description field; no hard-coded datasource UIDs other than the provisioned `Prometheus` name

## 11. Documentation

- [ ] 11.1 Author `docs/OBSERVABILITY.md`: stack overview, what each dashboard shows, how to add a custom metric in Java (snippet) and Python (snippet), the cardinality discipline rules from D5
- [ ] 11.2 Add a "Metrics Inventory" table to OBSERVABILITY.md listing every custom metric, type, tags, and the dashboard(s) that use it — so renaming a metric flags downstream impact
- [ ] 11.3 Update root `README.md` Documentation section to link `docs/OBSERVABILITY.md`
- [ ] 11.4 Add a one-liner to each module's `AGENTS.md` referencing OBSERVABILITY.md for instrumenting new code

## 12. Hardening and verification

- [ ] 12.1 Confirm `/actuator/env`, `/actuator/heapdump`, `/actuator/threaddump`, `/actuator/loggers`, `/actuator/caches` return 404 by default on AscendAgent and WeatherMCP
- [ ] 12.2 Add Spring Boot integration test `MetricsEndpointIT` that asserts `/actuator/prometheus` returns 200 and contains the names of every custom metric defined in this change
- [ ] 12.3 Add Python integration test per service asserting `/metrics` returns 200 and includes the custom metric names
- [ ] 12.4 Run a 30-minute load test (or an extended reproduction of the bug-1 curl loop) and observe Prometheus disk growth stays bounded under the 72h retention; document expected steady-state size in OBSERVABILITY.md
- [ ] 12.5 Update `openspec/changes/add-observability/tasks.md` checkboxes as work proceeds
