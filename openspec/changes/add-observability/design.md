## Context

AscendAI runs six application services in two language stacks (Java 21 / Spring Boot, Python 3.11+ / FastAPI), four data-layer prerequisites (Postgres, Redis, Qdrant, MinIO), and four support services (SearXNG, FlareSolverr, Docling, Unstructured). Today, none of them export metrics. Operational state lives entirely in `docker logs` output streamed to stdout.

The recent `fix-ascend-agent-bugs` change demonstrated the cost: a memory-extraction parse failure went unnoticed until a user reported "Mem0 isn't remembering anything." A counter on a dashboard would have caught the regression in single-digit minutes.

We want the smallest possible change that:

1. Gives us a single Prometheus instance scraping every service.
2. Provisions Grafana with a few hand-picked dashboards out of the box.
3. Exposes a uniform set of "framework default" metrics across both language stacks.
4. Adds a small, opinionated set of **domain-specific** custom metrics targeting the failure modes the bug log already named.
5. Costs ~zero CPU and stays opt-out for thin local dev.

## Goals / Non-Goals

**Goals:**
- One scrape config, one Grafana, three checked-in dashboards.
- Spring Boot Actuator + Micrometer in both Java services.
- `prometheus-fastapi-instrumentator` in all four Python services.
- Common tags on every metric: `service`, `instance`, `version`.
- Domain custom metrics that map 1:1 onto bugs we have already paid for once.
- Docker Compose profile so observability stack can be turned off (`--profile no-observability`).
- Documentation: `docs/OBSERVABILITY.md` describes what is collected and how to add a metric.

**Non-Goals:**
- Distributed tracing (OpenTelemetry / Jaeger / Tempo). Tracing is a separate, larger change — it requires `propagators`, baggage, sampling decisions, and a tracing backend. Cleanly out of scope.
- Logs aggregation (Loki / ELK). Logs already flow to `docker logs`; centralization is a separate change.
- Alerting rules / Alertmanager. Once metrics exist, alerting rules are a follow-up. We will write the metrics in a way that lets alerts be added without further code changes.
- Custom exporters for the data layer. We rely on official Prometheus exporters where they exist (`postgres_exporter`, `redis_exporter`, Qdrant native `/metrics`); MinIO ships built-in Prometheus output. No bespoke exporters.
- APM-style profiling (e.g., Pyroscope). Out of scope.
- Production-grade security on Grafana. Anonymous read-only viewer is fine for local dev; auth hardening is a follow-up if/when this stack runs in a shared environment.

## Decisions

### D1 — Stack: Prometheus + Grafana, not OpenTelemetry Collector

We use direct Prometheus scrape rather than an OpenTelemetry Collector pipeline. Reasons:

- Spring Boot Actuator's Prometheus integration is two lines of `build.gradle.kts` plus three lines of YAML. The OTel Collector would add a Java agent, exporters, configuration files, and a separate process to keep alive.
- All target metrics endpoints are static and HTTP-pull friendly. We do not need OTel's protocol-translation strengths (no push, no traces).
- Grafana speaks Prometheus natively. Done.
- We can introduce OTel later for traces without disturbing this stack — they coexist.

### D2 — Custom metric inventory (named per OpenMetrics conventions)

Every metric is in lowercase, dot-separated for the Spring side (Micrometer auto-converts to underscore for Prometheus), suffixed `_total` for counters by Prometheus convention.

**AscendAgent (`service="ascend-agent"`):**

| Metric | Type | Tags | Why |
|---|---|---|---|
| `memory.extraction.parse_failed` | counter | `provider`, `model` | Catch the bug-1 regression. Spike → prompt drift / new model misbehaving. |
| `memory.insert.failed` | counter | `embedding_provider`, `reason` | Catch silent insert failures (the failed-fact aggregation work). |
| `memory.search.duration` | timer | `embedding_provider`, `outcome` | Latency + error rate of AscendMemory calls. |
| `rag.retrieval.hits` | counter | `provider`, `embedding_provider`, `above_threshold` | Track threshold filtering ratio. |
| `rag.retrieval.duration` | timer | `provider`, `outcome` | Spot Qdrant slowdowns. |
| `rag.last_top_score` | gauge | `provider` | Smoke-test the retrieval quality post-deploy. |
| `mcp.tool.duration` | timer | `tool`, `outcome` | Per-tool latency / error rate. |
| `ingestion.upload.bytes` | counter | `source_type`, `outcome` | Catch flood scenarios + idempotency regressions. |
| `chat.history.size` | gauge | `user_id` (low-cardinality only — see D5) | Detect runaway sessions. |
| `gen_ai.client.token.usage` | (auto from Spring AI) | `model`, `type` (input/output) | Spend tracking, free with Spring AI 1.1. |

**WeatherMCP**: only `mcp.tool.duration` and the framework defaults.

**AudioScribe (`service="audio-scribe"`):**
- `transcription.duration_seconds` — histogram, tags: `provider` (local/openai/hf), `outcome`.
- `transcription.audio_duration_seconds` — histogram, tags: `provider`. (Throughput proxy.)

**AscendWebSearch (`service="ascend-web-search"`):**
- `search.results_returned` — histogram, tags: `engine`, `outcome`.
- `extraction.tier_used_total` — counter, tags: `tier` (`curl_cffi`/`flaresolverr`/`playwright`/`novnc`).
- `extraction.captcha_intervention_total` — counter.

**AscendMemory (`service="ascend-memory"`):**
- `memory.operations_total` — counter, tags: `operation` (`insert`/`search`/`wipe`/`delete`), `outcome`.
- `memory.search.duration_seconds` — histogram, tags: `embedding_provider`.

**PaddleOCR (`service="paddle-ocr"`):**
- `ocr.pages_processed_total` — counter, tags: `language`, `outcome`.
- `ocr.duration_seconds` — histogram, tags: `language`.

### D3 — Common tags

Every metric across every service carries:

- `service` — service name from `application.yaml` / FastAPI app metadata.
- `instance` — hostname (auto-populated by Prometheus from the scrape target).
- `version` — application version, resolved at build time and exposed via Spring Boot's `/actuator/info` and FastAPI's startup-injected app metadata.

A `MeterRegistryCustomizer` in `MetricsConfig.java` applies `service` and `version` tags globally. Python equivalent uses `Instrumentator().add(...)` with a `prom_default_metric_decorator`.

### D4 — Endpoint shape and security

| Service | Path | Bound to |
|---|---|---|
| AscendAgent | `/actuator/prometheus` | `127.0.0.1:9917` by default; remote exposure requires `MANAGEMENT_ENDPOINTS_WEB_EXPOSURE_REMOTE=true` |
| WeatherMCP | `/actuator/prometheus` | same model |
| Python services | `/metrics` | bound to `0.0.0.0` inside the container; exposed only on the docker network |
| Prometheus | `:9090` | exposed on host |
| Grafana | `:3030` | exposed on host (anonymous read-only Viewer) |

Actuator endpoints are exposed only via `prometheus`, `health`, `info`. `env`, `heapdump`, `threaddump`, `loggers`, `caches` stay disabled to avoid leaking config.

### D5 — Cardinality discipline

High-cardinality tags are forbidden. Two rules:

1. **Never tag with `user_id` directly.** The single allowed exception is the `chat.history.size` gauge, where the gauge is published only for the top-10 active sessions seen in the last minute (rotating slot allocation in `MetricsConfig`). Default install caps it at zero.
2. **Never tag with free-form strings (URLs, prompts, error messages).** Use a small enum-like set: `outcome ∈ {ok, error, timeout, rate_limited}`. Any new tag value must be from a closed set.

If a counter would naturally need an unbounded tag, we drop the tag and emit a separate WARN log line with the rich context.

### D6 — Provisioning Grafana, not configuring it

Grafana is fully provisioned at startup via files mounted into `/etc/grafana/provisioning/`:

- `datasources/prometheus.yml` — points at `http://prometheus:9090`, marked default.
- `dashboards/dashboards.yml` — loads `/var/lib/grafana/dashboards/*.json`.
- `dashboards/*.json` — the three checked-in dashboards.

This means a fresh `docker-compose up` produces a fully working Grafana with dashboards already loaded. No clicking through the UI to wire datasources.

The dashboards are saved as JSON via Grafana's "Share → Export" with `For external use` toggled on so they are portable. We treat them as code: any change goes through git.

### D7 — Docker Compose profiles

```yaml
services:
  prometheus:
    profiles: ["", "observability"]
  grafana:
    profiles: ["", "observability"]
```

Using an empty-string profile means the services start by default. To opt out:

```bash
docker compose --profile no-observability up -d
```

We considered the inverse (default-off, `--profile observability` to enable). Rejected because the goal is "observable by default" — making it opt-out keeps the happy path one command long.

### D8 — Why not just use `/actuator/health` for everything

Several teams stop at health checks. We do not, because:

- Health endpoints answer "is the service up?" — they cannot answer "is it degraded?", "is the LLM provider rate-limiting us?", "did Mem0 just start dropping inserts?".
- The cost of going from health-only to metrics is one dependency, three lines of YAML, and a Prometheus + Grafana sidecar pair. The marginal value (rate-of-X queries, alertable thresholds, retroactive investigation) is huge.

## Risks / Trade-offs

- **Container memory footprint.** Prometheus default retention is 15 days; on a laptop running everything locally, that is ~1 GB of disk in steady state. We set `--storage.tsdb.retention.time=72h` for local dev to bound it.
- **Dashboard rot.** Custom dashboards drift from reality as code changes. Mitigation: every dashboard panel cites the underlying metric name, and `docs/OBSERVABILITY.md` lists the metrics inventory with the dashboards using them. When a metric is renamed, the cross-reference forces an update.
- **Cardinality explosion via well-meaning new tags.** Mitigated by D5 and a code-review checklist item.
- **Spring Boot version skew.** Spring Boot 3.5.4 is on Micrometer 1.13. The Prometheus simpleclient registry has moved to OpenMetrics-format-by-default; pin the registry version explicitly.
- **Python instrumentation overhead.** `prometheus-fastapi-instrumentator` adds an ASGI middleware that times every request. Measured overhead is sub-microsecond per request; acceptable.

## Migration Plan

Strict additive change, executed in this order:

1. Add observability stack to `docker-compose.yaml` with checked-in Prometheus + Grafana configs, **no application changes yet**.
2. Wire AscendAgent first — Spring Boot is the most observable target and has the highest custom-metric value. Validate end-to-end on the AI Pipeline dashboard.
3. Wire WeatherMCP (small, exercises the JVM template).
4. Wire AscendMemory (small Python, exercises the Python template).
5. Wire AudioScribe, AscendWebSearch, PaddleOCR (template repetition).
6. Add data-layer exporters (`postgres_exporter`, `redis_exporter`, Qdrant `/metrics`, MinIO built-in).
7. Author and provision the three dashboards.
8. Write `docs/OBSERVABILITY.md`.
9. Smoke-test: every dashboard renders something non-empty after running the bug-1 / bug-2 / bug-3 / bug-4 reproduction curls.

## Open Questions

- **Should the agent expose the Prometheus endpoint on the same port as the API (`9917`) or a separate management port?** Spring Boot supports `management.server.port`. Default is the same port. Recommend keeping default for simplicity unless ops feedback says otherwise.
- **Grafana auth.** Anonymous Viewer for local. For shared dev environments, do we want OIDC via the same Keycloak the rest of the stack might use later? Out of scope here, flagged for follow-up.
- **Retention.** 72h locally; longer (or remote-write to a hosted Prometheus) when we run this on shared infra. Not decided here.
