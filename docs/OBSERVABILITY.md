# Observability

AscendAI ships a full three-pillar observability stack (metrics, logs, traces) as always-on containers in `compose.yaml`. This document explains what is collected, how to reach the dashboards, how to add your own instrumentation, and what to expect in terms of resource usage.

---

## Stack Overview

| Pillar | Tool | Access |
|---|---|---|
| Metrics | Prometheus + Grafana | Prometheus: http://localhost:7077, Grafana: http://localhost:7078 |
| Logs | Vector (shipper) + Loki (storage) + Grafana | http://localhost:7078 → Explore → Loki |
| Traces | OTel Collector + Tempo + Grafana | http://localhost:7078 → Explore → Tempo |

All seven observability containers start automatically with `docker compose up`. There is no profile flag required — observability is always-on.

---

## How to Reach Grafana

Open http://localhost:7078 in a browser. Grafana is configured with anonymous read-only Viewer access — no login required. The three datasources (Prometheus, Loki, Tempo) are provisioned at startup. The six dashboards below are loaded from `infra/observability/grafana/dashboards/` and visible under the Dashboards menu immediately after the stack starts.

---

## Six Dashboards

| Dashboard | UID | What it answers |
|---|---|---|
| Platform Overview | `ascend-platform-overview` | Are services up? Are requests latent or erroring? |
| AI Pipeline | `ascend-ai-pipeline` | Are tokens flowing? RAG hitting? Tool calls latent? |
| Infrastructure | `ascend-infrastructure` | Is Qdrant growing? Postgres connections healthy? |
| L1 — Token Cost | `ascend-token-cost` | What is each provider costing per day? |
| L2 — RAG Quality | `ascend-rag-quality` | Top-K score distribution; miss-rate trends; ingestion throughput |
| L3 — Cache Hit Rate | `ascend-cache-hit-rate` | Is the prompt-caching change actually saving money? |

To jump directly to a dashboard: http://localhost:7078/d/<uid>

---

## What Is Collected

### Metrics

Prometheus scrapes every 15 seconds. Scrape targets are in `infra/observability/prometheus/prometheus.yaml`.

**Spring Boot services (ascend-ai-agent :9917/actuator/prometheus, ascend-weather-mcp :9998/actuator/prometheus)**

- All JVM metrics via Micrometer: `jvm_memory_used_bytes`, `jvm_gc_pause_seconds`, `jvm_threads_*`, etc.
- HTTP request metrics: `http_server_requests_seconds_count/sum/max` with `uri`, `method`, `status` tags.
- Spring AI auto-instrumented metrics: `gen_ai_client_token_usage_total` with `gen_ai_system`, `gen_ai_request_model`, `gen_ai_token_type` tags.
- Custom domain metrics (see Metrics Inventory below).

**Python services (ports 7017, 7020, 7021, 7022 at /metrics)**

- `starlette_requests_total` and `starlette_requests_duration_seconds` per endpoint.
- `python_info` (interpreter version).
- `process_resident_memory_bytes`, `process_cpu_seconds_total`.
- Custom domain metrics (see Metrics Inventory below).

**Data-layer exporters**

- `postgres-exporter` at :9187 — `pg_stat_activity_count`, `pg_database_size_bytes`, `pg_stat_bgwriter_*`.
- `redis-exporter` at :9121 — `redis_commands_processed_total`, `redis_memory_used_bytes`, `redis_connected_clients`.
- Qdrant at host port :6333/metrics — `qdrant_collections_vectors_count`, `qdrant_collection_payload_storage_bytes`.

### Logs

Vector reads Docker container stdout/stderr via the Docker socket and ships to Loki with labels `service` (from `container_name`) and `source` (`docker`). No code changes are required in any service — they just write to stdout.

To query logs in Grafana: Explore → Loki → `{service="ascend-ai-agent"}`.

To filter by level: `{service="ascend-ai-agent"} |= "WARN"`.

### Traces

The OTel Collector receives OTLP on port 4317 (gRPC) and 4318 (HTTP) from all six application services. It batches and forwards to Tempo.

- ascend-ai-agent and ascend-weather-mcp: Spring AI 1.1 emits OTel spans for every LLM call, tool call, and embedding call when `OTEL_EXPORTER_OTLP_ENDPOINT` is set (which it is via compose.yaml). No additional code is required.
- Python services: OTel auto-instrumentation is activated when `OTEL_EXPORTER_OTLP_ENDPOINT` is set and the `opentelemetry-distro` package is installed and activated in `src/main.py`. FastAPI, httpx, and requests are auto-instrumented.

To view traces in Grafana: Explore → Tempo → search by `service.name=ascend-ai-agent`.

---

## Metrics Inventory

Every custom metric emitted by ascend-ai-agent. Micrometer converts dot-separated names to underscore-separated Prometheus metric names and appends `_total` to counters.

| Metric (Spring notation) | Prometheus name | Type | Tags | Dashboards |
|---|---|---|---|---|
| `gen_ai.client.token.usage` | `gen_ai_client_token_usage_total` | counter (auto, Spring AI) | `gen_ai_system`, `gen_ai_request_model`, `gen_ai_token_type` | AI Pipeline, L1 Token Cost |
| `memory.extraction.parse_failed` | `memory_extraction_parse_failed_total` | counter | `provider`, `model` | AI Pipeline |
| `memory.insert.failed` | `memory_insert_failed_total` | counter | `embedding_provider`, `reason` | — |
| `memory.search.duration` | `memory_search_duration_seconds_*` | timer | `embedding_provider`, `outcome` | — |
| `rag.retrieval.hits` | `rag_retrieval_hits_total` | counter | `provider`, `embedding_provider`, `above_threshold` | AI Pipeline, L2 RAG Quality |
| `rag.retrieval.duration` | `rag_retrieval_duration_seconds_*` | timer | `provider`, `outcome` | — |
| `rag.last_top_score` | `rag_last_top_score` | gauge | `provider` | L2 RAG Quality |
| `rag.top_score` | `rag_top_score_bucket` | histogram | `provider` | L2 RAG Quality |
| `mcp.tool.duration` | `mcp_tool_duration_seconds_*` | timer | `tool`, `outcome` | AI Pipeline |
| `ingestion.upload.bytes` | `ingestion_upload_bytes_total` | counter | `source_type`, `outcome` | L2 RAG Quality |
| `prompt_cache.tokens.read` | `prompt_cache_tokens_read_total` | counter | `provider` | L3 Cache Hit Rate |
| `prompt_cache.tokens.creation` | `prompt_cache_tokens_creation_total` | counter | `provider` (Anthropic only) | L3 Cache Hit Rate |
| `prompt_cache.tokens.total` | `prompt_cache_tokens_total` | counter | `provider` | L3 Cache Hit Rate |

Allowed values for `outcome` tag: `ok`, `error`, `timeout`, `rate_limited`. Never use free-form strings — see Cardinality Rules below.

---

## How to Add a Custom Metric

### Java (Spring Boot / Micrometer)

Inject `MeterRegistry` via constructor injection in the class where you want to emit the metric.

```java
private final Counter parseFailedCounter;

public MyService(MeterRegistry meterRegistry) {
    this.parseFailedCounter = Counter.builder("my.operation.failed")
        .tag("reason", "parse_error")
        .description("Count of my operation failures")
        .register(meterRegistry);
}
```

Then increment it:

```java
parseFailedCounter.increment();
```

For a timer:

```java
private final Timer operationTimer;

public MyService(MeterRegistry meterRegistry) {
    this.operationTimer = Timer.builder("my.operation.duration")
        .tag("outcome", "ok")
        .register(meterRegistry);
}

Timer.Sample sample = Timer.start(meterRegistry);
// ... do work ...
sample.stop(operationTimer);
```

Micrometer converts dots to underscores automatically. The metric appears in Prometheus as `my_operation_failed_total` and `my_operation_duration_seconds_bucket`.

### Python (prometheus-fastapi-instrumentator / prometheus_client)

Import the prometheus_client counters and histograms at module level.

```python
from prometheus_client import Counter, Histogram

MY_OPERATION_FAILED = Counter(
    "my_operation_failed_total",
    "Count of my operation failures",
    ["reason"],
)

MY_OPERATION_DURATION = Histogram(
    "my_operation_duration_seconds",
    "Duration of my operation",
    ["outcome"],
)
```

Increment from your handler:

```python
MY_OPERATION_FAILED.labels(reason="parse_error").inc()

with MY_OPERATION_DURATION.labels(outcome="ok").time():
    result = do_work()
```

The metrics appear at `/metrics` and are scraped by Prometheus.

---

## How to Add a Log Field

Python services log via the standard `logging` module. To add a structured field, use a `LogRecord` extra or a custom formatter. The log line is already tagged with `service` by Vector when it ships to Loki.

Java services use standard SLF4J + Logback. Structured logging can be added via `net.logstash.logback:logstash-logback-encoder`. The existing setup writes plain text; to add key-value fields, use MDC:

```java
MDC.put("requestId", requestId);
log.info("Processing request");
MDC.clear();
```

---

## How to Add a Span Attribute

### Java

Spring AI auto-instrumentation creates spans for LLM calls. To add attributes to a custom span:

```java
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.api.trace.Span;

Span span = tracer.spanBuilder("my-operation")
    .startSpan();
span.setAttribute("my.attribute", "value");
// ... do work ...
span.end();
```

Or, to add an attribute to the current active span:

```java
Span.current().setAttribute("rag.hit_count", hitCount);
```

### Python

With OTel auto-instrumentation active:

```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("my-operation") as span:
    span.set_attribute("my.attribute", "value")
    do_work()
```

---

## Cardinality Rules

These rules prevent Prometheus from accumulating millions of time-series (high cardinality) which causes memory exhaustion and slow queries.

1. Never tag metrics with `user_id` directly. If you need to track per-user state, use a rotating slot gauge (contact the platform team first).
2. Never tag with free-form strings such as URLs, prompt text, error messages, or model responses. Use a closed set: `outcome` must be one of `ok`, `error`, `timeout`, `rate_limited`. If you need richer error context, write a WARN log line (it goes to Loki and is searchable) instead of adding an unbounded tag.
3. The `model` tag is allowed because the set of models used is small and known (< 20 values).
4. When in doubt, query the candidate metric in Prometheus with `count(count by (<tag>) (my_metric))` to estimate cardinality before merging.

---

## Token Cost Pricing Rates

Token cost estimates in the L1 dashboard use hardcoded rates from `infra/observability/grafana/dashboards/pricing.yaml`. When a provider changes its pricing:

1. Edit `infra/observability/grafana/dashboards/pricing.yaml` with the new rates.
2. Update the matching PromQL expressions in `infra/observability/grafana/dashboards/token-cost.json` (the multiplier constants match the rates in `pricing.yaml`).
3. Restart Grafana to reload the provisioned dashboard.

```bash
docker compose restart grafana
```

---

## Vector to Cloud Migration

If you want to ship logs to Datadog, CloudWatch, or Splunk instead of (or in addition to) Loki, edit `infra/observability/vector/vector.toml`. The file contains commented-out sink blocks for each target. Uncomment the desired sink, set the required environment variable, and restart Vector.

```bash
docker compose restart vector
```

No service code changes are required. Vector handles the fan-out.

---

## Resource Usage

At idle, the seven observability containers consume approximately:

| Container | RAM (idle) |
|---|---|
| prometheus | ~80 MB |
| grafana | ~120 MB |
| loki | ~80 MB |
| vector | ~30 MB |
| otel-collector | ~40 MB |
| tempo | ~120 MB |
| **Total** | **~470 MB** |

Disk retention is bounded:
- Prometheus: 72 hours (`--storage.tsdb.retention.time=72h`), approximately 200 MB steady state under normal load.
- Loki: 168 hours (7 days), approximately 500 MB steady state.
- Tempo: 168 hours (7 days), approximately 300 MB steady state.

Total expected disk usage: approximately 1-2 GB steady state on a local development machine running representative traffic.

---

## Port Reference

| Service | Host Port | Container Port | Access |
|---|---|---|---|
| Prometheus | 7077 | 9090 | http://localhost:7077 |
| Grafana | 7078 | 3000 | http://localhost:7078 |
| Loki | docker-network only | 3100 | via Grafana Explore |
| Tempo | docker-network only | 3200 | via Grafana Explore |
| OTel Collector gRPC | docker-network only | 4317 | services write to http://otel-collector:4317 |
| OTel Collector HTTP | docker-network only | 4318 | services write to http://otel-collector:4318 |
