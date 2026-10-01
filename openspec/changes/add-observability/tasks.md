## 1. Bring up Prometheus + Grafana with empty scrape config

- [x] 1.1 Create `infra/observability/prometheus/prometheus.yaml` with `global.scrape_interval: 15s`, an empty `scrape_configs` list, and external labels `{cluster: "ascend-ai-local"}` (note: `.yaml` extension to match repo convention)
- [x] 1.2 Create `infra/observability/grafana/provisioning/datasources/datasources.yaml` declaring three datasources (`Prometheus` → `http://prometheus:9090`, `Loki` → `http://loki:3100`, `Tempo` → `http://tempo:3200`); `Prometheus` marked default
- [x] 1.3 Create `infra/observability/grafana/provisioning/dashboards/dashboards.yaml` that mounts `/var/lib/grafana/dashboards/` as the dashboard provider
- [x] 1.4 Add `prometheus` service to `compose.yaml` (image `prom/prometheus:v2.55.x`, volume mount config, port `7077:9090`, command flag `--storage.tsdb.retention.time=72h`)
- [x] 1.5 Add `grafana` service to `compose.yaml` (image `grafana/grafana:11.x.x`, volume mounts for provisioning + dashboards directory, port `7078:3000`, env `GF_AUTH_ANONYMOUS_ENABLED=true`). The anonymous role is task 1.8
- [ ] 1.6 Smoke test: `docker compose up -d prometheus grafana`, then `curl -s -o /dev/null -w "%{http_code}" http://localhost:7077/-/ready` and `curl -s -o /dev/null -w "%{http_code}" http://localhost:7078/api/health`. Pass: both print `200`
- [x] 1.7 Both services start by default (no profile attribute). Observability is always on per the owner's direction
- [ ] 1.8 Set `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer` on the `grafana` service in `compose.yaml` (today it is `Editor`, which the spec does not allow). Check: `curl -s http://localhost:7078/api/user` without credentials, or `curl -s -X POST http://localhost:7078/api/dashboards/db -H "Content-Type: application/json" -d "{\"dashboard\":{\"title\":\"x\"}}"`, answers `401` or `403`, never `200`

## 2. Wire ascend-agent (Spring Boot) - metrics

- [x] 2.1 Add `org.springframework.boot:spring-boot-starter-actuator` and `io.micrometer:micrometer-registry-prometheus` to `apps/ascend-agent/build.gradle.kts`
- [x] 2.2 In `apps/ascend-agent/src/main/resources/application.yaml`, add `management.endpoints.web.exposure.include: health,info,prometheus`, `management.endpoint.health.show-details: when-authorized`, `management.metrics.tags.service: ascend-agent`, `management.metrics.tags.version: @project.version@`
- [x] 2.3 Enable `processResources` filtering for `application.yaml` in `build.gradle.kts` so `@project.version@` resolves at build time
- [x] 2.4 Create `apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/config/MetricsConfig.java` with a `MeterRegistryCustomizer<MeterRegistry>` bean that applies common tags (`service`, `version`) globally
- [x] 2.5 Add scrape job for ascend-agent to `infra/observability/prometheus/prometheus.yaml`: `job_name: ascend-agent`, `metrics_path: /actuator/prometheus`, `static_configs.targets: [ascend-agent:9917]` over the compose network
- [ ] 2.6 Smoke test: hit `http://localhost:9917/actuator/prometheus`, confirm body contains `jvm_memory_used_bytes`, `gen_ai_client_token_usage_total` (after one prompt), and the `service="ascend-agent"` tag appears on every line

## 3. Custom metrics - semantic memory

- [x] 3.1 Inject `MeterRegistry` into `SemanticMemoryExtractor`
- [x] 3.2 In the parse-failure branch (after the JSON-array extractor returns empty), increment `Counter` `memory.extraction.parse_failed` with tags `provider`, `model`
- [x] 3.3 Inject `MeterRegistry` into `SemanticMemoryClient`
- [x] 3.4 Wrap `performInsertCall` in a `try` that on failure increments `memory.insert.failed` with tags `embedding_provider`, `reason` (closed set: `4xx`, `5xx`, `timeout`, `connect_error`); the throw behavior unchanged
- [x] 3.5 Wrap `performSearchCall` in a `Timer.Sample`; stop the sample with `memory.search.duration` keyed by `embedding_provider` and `outcome`
- [x] 3.6 Test (`SemanticMemoryClientMetricsTest`): force a 5xx response, assert `memory_insert_failed_total{reason="5xx"}` increments by 1
- [ ] 3.7 Add `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryExtractorMetricsTest.java`. Build the extractor with a `SimpleMeterRegistry` and a stubbed chat response that holds only thinking prose and no JSON array. Assert the counter `memory.extraction.parse_failed` with tags `provider` and `model` equal to the stub's values reads `1.0`, and reads `0.0` after a valid JSON array response. Run `./gradlew test --tests "com.lukk.ascend.ai.agent.service.memory.SemanticMemoryExtractorMetricsTest"` from `apps/ascend-agent`. Pass: the test is green and `./gradlew jacocoTestCoverageVerification` still passes

## 4. Custom metrics - RAG retrieval

- [x] 4.1 Inject `MeterRegistry` into `RagRetrievalService`
- [x] 4.2 After Qdrant search, count hits as `rag.retrieval.hits` with tag `above_threshold` set per-hit (`true`/`false`) - split increments per bucket
- [x] 4.3 Wrap retrieval call in `Timer.Sample`; record `rag.retrieval.duration` keyed by `provider`, `outcome`
- [x] 4.4 Publish a gauge `rag.last_top_score` from the highest-scoring hit on the most recent query, keyed by `provider` (use `MultiGauge` for per-provider lookup)
- [x] 4.5 Publish a histogram `rag.top_score` of every hit's score keyed by `provider` for the L2 dashboard score-distribution heatmap
- [x] 4.6 Test (`RagRetrievalServiceMetricsTest`): mock Qdrant returning 5 hits with scores `[0.91, 0.85, 0.80, 0.74, 0.60]` and threshold `0.75`; assert above_threshold counter incremented by 3 and below_threshold by 2

## 5. Custom metrics - MCP tool calls

- [x] 5.1 In the MCP tool invocation path (`apps/ascend-agent/src/main/java/com/lukk/ascend/ai/agent/service/chat/ChatExecutor.java`), wrap each tool invocation in `Timer.Sample`
- [x] 5.2 Record `mcp.tool.duration` keyed by `tool` (the MCP tool's logical name) and `outcome` (`ok`, `error`, `timeout`)
- [ ] 5.3 Add `apps/ascend-agent/src/test/java/com/lukk/ascend/ai/agent/service/chat/McpToolMetricsTest.java`. With a `SimpleMeterRegistry`, run three stubbed tool callbacks through `ChatExecutor`: one that returns at once, one that sleeps 200 ms, one that throws. Assert `mcp.tool.duration` has count `1` for each `tool` tag, `outcome=ok` for the first two and `outcome=error` for the third, and that the slow tool's total time is at least 200 ms. Run `./gradlew test --tests "com.lukk.ascend.ai.agent.service.chat.McpToolMetricsTest"` from `apps/ascend-agent`. Pass: green

## 6. Custom metrics - prompt-cache (powers L3 dashboard)

- [x] 6.1 Inject `MeterRegistry` into `AnthropicPromptCacheStrategy`
- [x] 6.2 In `recordOutcome(...)`, increment `prompt_cache.tokens.read{provider="anthropic"}` by `cacheReadInputTokens`, `prompt_cache.tokens.creation{provider="anthropic"}` by `cacheCreationInputTokens`, `prompt_cache.tokens.total{provider="anthropic"}` by `promptTokens`
- [x] 6.3 Inject `MeterRegistry` into `OpenAiPromptCacheStrategy`
- [x] 6.4 In `recordOutcome(...)`, increment `prompt_cache.tokens.read{provider}` by `cachedTokens` (where `provider` is the strategy's constructor-injected provider name - `openai` or `gemini`), `prompt_cache.tokens.total{provider}` by `promptTokens`. (No `creation` counter - OpenAI/Gemini cache writes are implicit, not surfaced.)
- [x] 6.5 Test (`AnthropicPromptCacheStrategyMetricsTest`): stub a response with `cacheReadInputTokens=487`, assert all three counters increment correctly
- [x] 6.6 Test (`OpenAiPromptCacheStrategyMetricsTest`): stub a response with `cachedTokens=512`, assert read + total counters increment

## 7. Wire ascend-weather-mcp (Spring Boot template)

- [x] 7.1 Add Actuator + Prometheus dependencies to `apps/ascend-weather-mcp/build.gradle.kts`
- [x] 7.2 Mirror `application.yaml` management block from ascend-agent with `service: ascend-weather-mcp`
- [x] 7.3 Add scrape job `ascend-weather-mcp` to `infra/observability/prometheus/prometheus.yaml`
- [ ] 7.4 Smoke test: `curl -s http://localhost:9998/actuator/prometheus`. Pass: status 200 and every sample line carries `service="ascend-weather-mcp"`

## 8. Logs layer - Vector + Loki

- [x] 8.1 Create `infra/observability/loki/loki-config.yaml` (single-binary mode, filesystem store, retention 168h)
- [x] 8.2 Add `loki` service to `compose.yaml` (image `grafana/loki:3.x.x`, volume mount config, port `3100` docker-network only)
- [x] 8.3 Create `infra/observability/vector/vector.toml` with: `[sources.docker]` reading via `docker_logs` source for the six AscendAI services; `[sinks.loki]` shipping to `http://loki:3100` with labels `service`, `source`. Add commented placeholder sinks for Datadog / CloudWatch / Splunk to document the migration story.
- [x] 8.4 Add `vector` service to `compose.yaml` (image `timberio/vector:0.42.x-alpine`, volume mount config, mount `/var/run/docker.sock:/var/run/docker.sock:ro`)
- [ ] 8.5 Smoke test: tail a log line in any AscendAI service container, then query Loki via Grafana Logs panel: `{service="ascend-agent"}` should return the line within 5 seconds. Check without the UI: `docker compose exec grafana wget -qO- "http://loki:3100/loki/api/v1/query_range?query=%7Bservice%3D%22ascend-agent%22%7D&limit=5"` lists the line

## 9. Traces layer - OTel collector + Tempo

- [x] 9.1 Create `infra/observability/tempo/tempo-config.yaml` (single-binary mode, filesystem store, retention 168h, OTLP receiver on `:4317`)
- [x] 9.2 Add `tempo` service to `compose.yaml` (image `grafana/tempo:2.x.x`, volume mount config, port `3200` docker-network only, OTLP `4317` docker-network only)
- [x] 9.3 Create `infra/observability/otel-collector/otel-collector-config.yaml` with OTLP receivers (gRPC `:4317`, HTTP `:4318`), `batch` + `memory_limiter` processors, OTLP exporter to Tempo
- [x] 9.4 Add `otel-collector` service to `compose.yaml` (image `otel/opentelemetry-collector-contrib:0.x.x`, volume mount config, ports `4317` + `4318` docker-network only)
- [ ] 9.5 Spring Boot 3.5.14 does not read `OTEL_EXPORTER_OTLP_ENDPOINT`, so the entry already in `compose.yaml` exports nothing. On the `ascend-agent` service in `compose.yaml` add `MANAGEMENT_OTLP_TRACING_ENDPOINT=http://otel-collector:4318/v1/traces` and `MANAGEMENT_TRACING_SAMPLING_PROBABILITY=1.0`, and remove the dead `OTEL_EXPORTER_OTLP_ENDPOINT` line. Keep `OTEL_SERVICE_NAME=ascend-agent` and `OTEL_RESOURCE_ATTRIBUTES`. Check: `docker compose exec ascend-agent printenv MANAGEMENT_OTLP_TRACING_ENDPOINT` prints the URL
- [ ] 9.6 Same for ascend-weather-mcp: add `implementation("io.opentelemetry:opentelemetry-exporter-otlp")` to `apps/ascend-weather-mcp/build.gradle.kts` (it has the tracing bridge but no exporter today), and the same two `MANAGEMENT_*` entries on the `ascend-weather-mcp` service in `compose.yaml`, removing its dead `OTEL_EXPORTER_OTLP_ENDPOINT` line. Check: `./gradlew build` passes in `apps/ascend-weather-mcp`
- [ ] 9.7 After 9.5, send one prompt with `bru run "ascend-agent/testing/weather-mcp-prompt.yml" --env ascend-local` from `docs/api/request/AscendAI`, wait 10 seconds, then run `docker compose exec grafana wget -qO- "http://tempo:3200/api/search?tags=service.name%3Dascend-agent&limit=5"`. Pass: at least one trace is listed, and fetching it with `docker compose exec grafana wget -qO- http://tempo:3200/api/traces/<traceID>` shows a span from Spring AI's chat client observation (a span name that starts with `chat` or `spring_ai`) and a span for the MCP tool call. If no Spring AI span appears, add the missing observation wiring in ascend-agent as part of this task
- [ ] 9.8 Smoke test: send one chat prompt via ascend-agent → query Tempo via Grafana Explore: search by `service.name=ascend-agent` → expect a single trace with spans for the LLM call

## 10. Wire ascend-memory (Python - metrics + traces)

- [x] 10.1 Add `prometheus-fastapi-instrumentator`, `opentelemetry-sdk`, `opentelemetry-instrumentation-fastapi` and `opentelemetry-exporter-otlp` to `apps/ascend-memory/pyproject.toml`
- [x] 10.2 In `apps/ascend-memory/src/main.py`, after FastAPI app construction: `Instrumentator().instrument(app).expose(app)` for `/metrics`
- [x] 10.3 Activate OTel tracing with `FastAPIInstrumentor().instrument()` in `apps/ascend-memory/src/main.py`
- [x] 10.4 Set OTel env in `compose.yaml` for the service: `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317`, `OTEL_SERVICE_NAME=ascend-memory`
- [ ] 10.5 Bring the ascend-memory metrics module to the spec. Today it defines `memory_insert_total`, `memory_search_total`, `memory_delete_total`, `memory_wipe_total` and four `*_duration_seconds` histograms. Replace the four counters with one `Counter("memory_operations_total", ["operation", "outcome"])` (operation in `insert`, `search`, `delete`, `wipe`, outcome from the closed set in the spec), and make `memory_search_duration_seconds` carry the label `embedding_provider`. Update `infra/observability/grafana/dashboards/*.json` panels that read the old names (`grep -rn "memory_insert_total\|memory_search_total" infra/observability`)
- [ ] 10.6 Wire the 10.5 metrics into the REST handlers and MCP tools of ascend-memory, and update its tests. Run `.venv/Scripts/python.exe -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` from `apps/ascend-memory`. Pass: green with 100 percent branch coverage
- [x] 10.7 Add scrape job `ascend-memory` to `infra/observability/prometheus/prometheus.yaml`
- [ ] 10.8 Smoke test: `curl -s http://localhost:7020/metrics`. Pass: status 200, body has `python_info` and `memory_operations_total`. Then send one search request (`curl -s "http://localhost:7020/api/v1/memory/search?query=test&user_id=smoke"`) and run `docker compose exec grafana wget -qO- "http://tempo:3200/api/search?tags=service.name%3Dascend-memory&limit=5"`. Pass: at least one trace

## 11. Wire ascend-audio-scribe, ascend-web-hunter, ascend-ocr (Python repetition)

- [x] 11.1 ascend-audio-scribe: dependencies, `Instrumentator(...).expose(app)`, OTel tracing, scrape job. The spec metric names are task 11.5
- [x] 11.2 ascend-web-hunter: dependencies, expose, OTel, scrape job, and `strategy_attempts_total{strategy,outcome,domain}` plus `human_intervention_total` as defined by `openspec/specs/web-search-caching-observability/spec.md`. The search result metric is task 11.6
- [x] 11.3 ascend-ocr: dependencies, expose, OTel, scrape job, and the job metrics `ascendocr_jobs_total{outcome}`, `ascendocr_job_duration_seconds`, `ascendocr_job_queue_wait_seconds`, `ascendocr_job_queue_documents` and `ascendocr_job_queue_pages` in `apps/ascend-ocr/src/observability/metrics.py`
- [ ] 11.4 Smoke test for each: `curl -s http://localhost:7017/metrics`, `curl -s http://localhost:7021/metrics`, `curl -s http://localhost:7022/metrics`. Pass: status 200 and the body has the names in the spec table for that service. Then one request per service and the Tempo search from 10.8 with that service's `service.name` lists at least one trace
- [ ] 11.5 ascend-audio-scribe metric names: today the code has `ascendaudioscribe_transcription_duration_seconds` and no audio length histogram. Rename it to `transcription_duration_seconds` with labels `provider` and `outcome`, and add `transcription_audio_duration_seconds` with label `provider`, observed with the input audio length. Update dashboards that read the old name and the tests. Run `.venv/Scripts/python.exe -m pytest` from `apps/ascend-audio-scribe`. Pass: green with the configured 100 percent branch gate
- [ ] 11.6 ascend-web-hunter search metric: today the code has `ascendwebhunter_search_results_total`. Add the spec histogram `search_results_returned` with labels `engine` and `outcome`, observed with the number of results per search, and remove the old counter after updating every dashboard that reads it. Run `.venv/Scripts/python.exe -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100` from `apps/ascend-web-hunter`. Pass: green

## 12. Data-layer exporters

- [ ] 12.1 Add a `redis-exporter` service (`oliver006/redis_exporter`, in scope by owner decision of 2026-10-01: at implementation time look up the latest release, pin that exact version tag, never a `.x` or `latest` tag, and pin it by digest like the other observability images) to `compose.yaml` with `REDIS_ADDR=redis://host.docker.internal:6379` (Redis is an external prerequisite, not a compose service), and a scrape job `redis` targeting `redis-exporter:9121` in `infra/observability/prometheus/prometheus.yaml`. Neither exists today. Acceptance: `docker compose config` shows the image with an exact version tag and a digest, and the `redis` target is `up` in Prometheus
- [ ] 12.2 Add a `postgres-exporter` service (`prometheuscommunity/postgres-exporter`, in scope by owner decision of 2026-10-01: at implementation time look up the latest release, pin that exact version tag, never a `.x` or `latest` tag, and pin it by digest) to `compose.yaml` with `DATA_SOURCE_URI=host.docker.internal:5432/ascend_ai?sslmode=disable` and `DATA_SOURCE_USER` and `DATA_SOURCE_PASS` taken from `.env` (add both names to `.env.example`), and a scrape job `postgres` targeting `postgres-exporter:9187`. Neither exists today. Acceptance: `docker compose config` shows the image with an exact version tag and a digest, and the `postgres` target is `up` in Prometheus
- [x] 12.3 Confirm Qdrant `:6333/metrics` endpoint is reachable (it ships built-in); add scrape job
- [x] 12.4 Object-store metrics: not applicable. The S3-compatible object store used locally (Floci) publishes no Prometheus endpoint, so no scrape job is added for it. See `replace-minio-with-floci`.
- [ ] 12.5 Smoke test: `curl -s http://localhost:7077/api/v1/targets`. Pass: the jobs `qdrant`, `redis` and `postgres` each report `"health":"up"`

## 13. Provision dashboards (six total)

- [x] 13.1 Build `infra/observability/grafana/dashboards/platform-overview.json` with panels: request rate per service, error rate per service, p95 latency per service, JVM heap, Python RSS
- [x] 13.2 Build `infra/observability/grafana/dashboards/ai-pipeline.json` with panels: tokens per minute by provider/model, provider mix, RAG hit-rate, memory parse-failure rate, MCP tool call rate
- [x] 13.3 Build `infra/observability/grafana/dashboards/infrastructure.json` with panels: Qdrant collection point counts, Redis ops/sec + used memory, Postgres connections + db size
- [x] 13.4 L1 - Token Cost (`infra/observability/grafana/dashboards/token-cost.json`): per-provider $/day computed via `gen_ai.client.token.usage{provider="...",type="input"} × pricing_input + ... type="output" × pricing_output`. Pricing rates committed in `infra/observability/grafana/dashboards/pricing.yaml` keyed by provider; loaded into the dashboard via JSON variable substitution at build time
- [x] 13.5 L2 - RAG Quality (`infra/observability/grafana/dashboards/rag-quality.json`): heatmap of `rag_top_score_bucket` over time, time-series of miss-rate (`rag.retrieval.hits{above_threshold="false"} / sum(rag.retrieval.hits)`), bar chart of ingestion-events-per-hour by `source_type`. Logs panel below querying Loki for `{service="ascend-agent"} |~ "Retrieval:"`
- [x] 13.6 L3 - Cache Hit Rate (`infra/observability/grafana/dashboards/cache-hit-rate.json`): primary panel `rate(prompt_cache.tokens.read[5m]) / rate(prompt_cache.tokens.total[5m])` per provider; side panel absolute saved-token count `rate(prompt_cache.tokens.read[1h]) * 3600` per provider; flat-line-at-zero alert annotation (UI only, no Alertmanager)
- [ ] 13.7 Generate traffic: run the e2e specs 1, 2 and 3 of `apps/ascend-agent/e2e/` once each (ask the owner which scenario first, as AGENTS.md requires), with at least one Anthropic or OpenAI prompt for the cache panels. Then for each of the six dashboards run `docker compose exec grafana wget -qO- "http://localhost:3000/api/dashboards/uid/<uid>"`, take every panel query, and run it against `http://localhost:7077/api/v1/query`. Pass: every panel query returns at least one series, or the panel is listed in `docs/OBSERVABILITY.md` as needing a provider that was not used
- [ ] 13.8 Sanity-check dashboard portability: each panel JSON cites its underlying metric/log/trace query in a description field; no hard-coded datasource UIDs other than the provisioned `Prometheus` / `Loki` / `Tempo` names

## 14. Documentation

- [x] 14.1 Author `docs/OBSERVABILITY.md`: stack overview (three pillars), what each dashboard shows, how to access Prometheus / Grafana / Loki / Tempo, how to add a custom metric in Java (snippet) and Python (snippet), how to add a span attribute, the cardinality discipline rules from D5, the Vector → Datadog migration recipe
- [ ] 14.2 Add a "Metrics Inventory" table to OBSERVABILITY.md listing every custom metric, type, tags, and the dashboard(s) that use it - so renaming a metric flags downstream impact
- [ ] 14.3 Add a "Pricing Rates" section explaining how to update `infra/observability/grafana/dashboards/pricing.yaml` when provider pricing changes (commit + restart Grafana to reload)
- [x] 14.4 Update root `README.md` Documentation section to link `docs/OBSERVABILITY.md`
- [ ] 14.5 Add a one-liner to each module's `AGENTS.md` referencing OBSERVABILITY.md for instrumenting new code

## 15. Hardening and verification

- [ ] 15.1 Confirm `/actuator/env`, `/actuator/heapdump`, `/actuator/threaddump`, `/actuator/loggers`, `/actuator/caches` return 404 by default on ascend-agent and ascend-weather-mcp
- [ ] 15.2 Add Spring Boot integration test `MetricsEndpointIT` that asserts `/actuator/prometheus` returns 200 and contains the names of every custom metric defined in this change (including the three new prompt-cache counters)
- [ ] 15.3 Python test per service asserting `/metrics` returns 200 and includes the spec metric names (the tests today assert the current code names, so they change with 10.5, 11.5 and 11.6)
- [ ] 15.4 Add an integration test `OtelTraceShipsToTempoIT` that sends one chat prompt via ascend-agent, polls Tempo for a trace with `service.name=ascend-agent`, asserts the trace has at least one LLM-call span
- [ ] 15.5 Run a 30-minute load test: one chat prompt every 10 seconds against `POST http://localhost:9917/api/v1/ai/prompt` (180 prompts, a loop over the Bruno request in 9.7 is enough) with the whole stack up. Record `docker system df -v` sizes of the volumes `prometheus-data`, `loki-data` and `tempo-data` at minute 0, 10, 20 and 30. Pass: no container restarts (`docker compose ps` shows no restart count change), Prometheus, Loki and Tempo answer `/ready` with 200 at minute 30, each volume grows at a steady or falling rate between the 10 to 20 and 20 to 30 minute windows, and the growth per hour projected over each retention window (72 h Prometheus, 168 h Loki and Tempo) stays under 5 GiB per volume. Write the measured rates and projected steady-state sizes into `docs/OBSERVABILITY.md`
- [x] 15.6 Update `openspec/changes/add-observability/tasks.md` checkboxes as work proceeds
