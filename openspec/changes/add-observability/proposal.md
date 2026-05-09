## Why

AscendAI today is observable only via stdout logs. There are no counters, no histograms, no scrape endpoints, no dashboards. When something misbehaves — Mem0 extraction fails to parse JSON, RAG retrieval misses, an MCP tool times out, an LLM provider rate-limits — the only signal is a WARN line that someone has to be `grep`-ing for in real time. Three concrete consequences:

1. **Bug-1 (the semantic memory parse failure that triggered the `fix-ascend-agent-bugs` change) was visible for an unknown amount of time before being noticed.** A `memory.extraction.parse_failed` counter on a Grafana dashboard would have surfaced it within minutes of the first occurrence, not after a user noticed Mem0 was empty.
2. **No way to alert on degradation.** Provider-switch effects (e.g., MiniMax-M2.7 returning prose, RAG misses spiking after a re-ingest) cannot trigger PagerDuty / a webhook because there's no metric to threshold.
3. **No baseline for performance work.** "Is RAG retrieval slow?" / "Is the bottleneck the embedding call or the Qdrant search?" / "How many tokens per turn does each provider use?" — none of these can be answered without instrumenting first.

Spring Boot already ships with Micrometer (the metrics façade) baked in via Actuator. Spring AI 1.1 auto-instruments token usage, model-call latency, and tool-call counts when Actuator is on the classpath. The Python services (FastAPI / FastMCP) have an equally lightweight `prometheus-fastapi-instrumentator` library. We are leaving 80% of observability on the table by not wiring these up.

## What Changes

This change wires Micrometer + Prometheus + Grafana into the AscendAI stack as a first-class operational layer, alongside a small set of **domain-specific custom metrics** that target the exact pain points the recent bug investigations exposed.

- **AscendAgent (Spring Boot)**: add `spring-boot-starter-actuator` and `micrometer-registry-prometheus` dependencies. Expose `/actuator/health`, `/actuator/prometheus`, `/actuator/info`. Auto-pick-up Spring AI's `gen_ai.*` metrics. Add custom counters/timers/gauges for the failure modes we have already paid for once: memory extraction parse failures, memory insert failures, RAG retrieval thresholding outcomes, ingestion errors per source type, MCP tool latency.
- **WeatherMCP (Spring Boot)**: same Actuator + Prometheus stack, expose `/actuator/prometheus`. Minimal custom metrics (tool-call counter is enough for an MCP server).
- **Python services (AudioScribe, AscendWebSearch, AscendMemory, PaddleOCR)**: add `prometheus-fastapi-instrumentator` to FastAPI apps and expose `/metrics`. Add a small set of custom domain counters per service (transcription duration, search-result count, memory-search latency, OCR pages-processed).
- **Prometheus**: new docker-compose service `prometheus` with a checked-in `prometheus.yml` that scrapes all six AscendAI services on their `/metrics` (or `/actuator/prometheus`) endpoints every 15 s, plus the data-layer prerequisites (Qdrant, Redis, Postgres) via official exporters where available.
- **Grafana**: new docker-compose service `grafana` with anonymous read-only access on a non-conflicting port (`3030` to avoid clashing with anything), provisioned with the Prometheus datasource and three dashboards: **Platform Overview** (request rate, error rate, latency, JVM), **AI Pipeline** (tokens, provider mix, RAG hit rate, memory parse-failure rate), **Infrastructure** (Qdrant collection sizes, Redis cache stats, Postgres connections).
- **Documentation**: a new `docs/OBSERVABILITY.md` walks through what is collected, how to find it, and how to add a custom metric. Cross-link from the root README "Documentation" section.
- **Defaults**: observability stack runs by default in `docker-compose.yaml` but is opt-out via a compose profile (`--profile no-observability`) for thin local dev. The actuator endpoints on the JVM services are bound to localhost-only by default; remote exposure requires an explicit env var.

## Capabilities

### New Capabilities

- `service-metrics` — every AscendAI service emits a uniform Prometheus-format metrics endpoint with framework-default metrics plus a defined minimum set of domain counters/timers.
- `observability-stack` — Prometheus + Grafana run in `docker-compose.yaml` with a checked-in scrape config and provisioned dashboards.

### Modified Capabilities

(none — this change is additive)

## Impact

- **New runtime services**: `prometheus` (port `9090`), `grafana` (port `3030`).
- **New code (AscendAgent)**:
  - `AscendAgent/build.gradle.kts` — two dependency lines.
  - `AscendAgent/src/main/resources/application.yaml` — `management.endpoints.*`, `management.metrics.*` block.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/MetricsConfig.java` — central `MeterRegistry` customizer, common tags (`service`, `instance`).
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryExtractor.java` — increment `memory.extraction.parse_failed`.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/memory/SemanticMemoryClient.java` — increment `memory.insert.failed`, time `memory.search.duration`.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/RagRetrievalService.java` — counter `rag.hits.above_threshold`, gauge `rag.last_top_score`.
  - `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/service/ChatExecutor.java` — timer `mcp.tool.duration` keyed by tool name.
- **New code (WeatherMCP)**: same two dependency lines + actuator config.
- **New code (Python services)**: `prometheus-fastapi-instrumentator` in `pyproject.toml`; one-line wiring in `src/main.py` per service; ~3 custom counters per service.
- **New files**:
  - `docker-compose.yaml` — `prometheus` and `grafana` services.
  - `observability/prometheus/prometheus.yml`
  - `observability/grafana/provisioning/datasources/prometheus.yml`
  - `observability/grafana/provisioning/dashboards/dashboards.yml`
  - `observability/grafana/dashboards/platform-overview.json`
  - `observability/grafana/dashboards/ai-pipeline.json`
  - `observability/grafana/dashboards/infrastructure.json`
  - `docs/OBSERVABILITY.md`
- **Tests**: smoke test that hits `/actuator/prometheus` on the agent and asserts the custom metric names exist with the expected tags; Python integration tests assert `/metrics` endpoint exposes `python_info` plus at least one custom counter.
- **Docs**: `docs/OBSERVABILITY.md` (new); link in main README's Documentation section.
- **Backwards compat**: fully additive. No public API changes. Existing logging is unchanged. Stack can be skipped via `--profile no-observability`.
- **Performance overhead**: Micrometer counters are nanosecond-scale. Prometheus scrape every 15 s. Negligible.
