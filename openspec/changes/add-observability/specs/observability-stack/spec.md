## ADDED Requirements

### Requirement: Prometheus runs in docker-compose with checked-in scrape config

`docker-compose.yaml` SHALL define a `prometheus` service that uses a checked-in `observability/prometheus/prometheus.yaml` configuration (`.yaml` extension to match the repo's YAML convention). The Prometheus instance SHALL scrape every AscendAI application service plus the data-layer prerequisites (Qdrant native, Redis via `redis_exporter`, Postgres via `postgres_exporter`, MinIO native).

#### Scenario: Prometheus targets are healthy after stack startup

- **WHEN** `docker compose up -d` completes and 30 seconds elapse
- **AND** `GET http://localhost:9090/api/v1/targets` is invoked
- **THEN** every target with `job` ∈ {`ascend-agent`, `audio-scribe`, `ascend-web-search`, `ascend-memory`, `paddle-ocr`, `weather-mcp`, `qdrant`, `redis`, `postgres`, `minio`} reports `health="up"`

#### Scenario: Scrape interval is 15 seconds by default

- **WHEN** the Prometheus configuration is loaded
- **THEN** the global `scrape_interval` is 15s and individual jobs may override it but no override is shorter than 5s

### Requirement: Logs ship to Loki via Vector

`docker-compose.yaml` SHALL define a `vector` service and a `loki` service. Vector SHALL read Docker container stdout/stderr via the `docker_logs` source and ship to Loki via the `loki` sink. Vector SHALL be the chosen shipper (not Promtail) so the `vector.toml` can swap the destination to Datadog / CloudWatch / Splunk in future without service changes.

#### Scenario: Log line reaches Loki within 5 seconds

- **WHEN** any AscendAI service writes a log line to stdout
- **AND** `{service="<that-service>"}` is queried via Grafana's Logs panel within 5 seconds
- **THEN** the line is returned

#### Scenario: Vector config documents migration sinks

- **WHEN** `observability/vector/vector.toml` is read
- **THEN** the file contains commented placeholder sink stanzas for `datadog_logs`, `aws_cloudwatch_logs`, and `splunk_hec` showing the migration recipe

### Requirement: Traces ship to Tempo via the OTel collector

`docker-compose.yaml` SHALL define an `otel-collector` service and a `tempo` service. The OTel collector SHALL accept OTLP receivers on gRPC `:4317` and HTTP `:4318`, batch and memory-limit-process spans, and export to Tempo via OTLP. AscendAgent and WeatherMCP SHALL be configured with `OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317` so Spring AI's auto-emitted spans land in Tempo. Python services SHALL be configured equivalently via `opentelemetry-distro`.

#### Scenario: A single chat turn produces a queryable trace

- **WHEN** AscendAgent serves one `POST /api/v1/ai/prompt` request
- **AND** Tempo is queried via Grafana's Tempo datasource within 10 seconds
- **THEN** a trace with `service.name=ascend-agent` exists for that request
- **AND** the trace contains at least one Spring AI auto-emitted LLM-call span

### Requirement: Grafana runs in docker-compose with provisioned datasources and six dashboards

`docker-compose.yaml` SHALL define a `grafana` service exposed on host port `3030` with anonymous Viewer access enabled by default. Grafana SHALL be provisioned at startup with three datasources (`Prometheus`, `Loki`, `Tempo`) and six checked-in dashboards (`Platform Overview`, `AI Pipeline`, `Infrastructure`, `Token Cost`, `RAG Quality`, `Cache Hit Rate`).

#### Scenario: Grafana is reachable after stack startup

- **WHEN** `docker compose up -d` completes and 30 seconds elapse
- **AND** `GET http://localhost:3030/api/health` is invoked
- **THEN** the response status is 200

#### Scenario: All three datasources are provisioned

- **WHEN** Grafana has finished startup
- **AND** `GET http://localhost:3030/api/datasources` is invoked
- **THEN** the response includes datasources named `Prometheus`, `Loki`, `Tempo` of the corresponding types
- **AND** `Prometheus` is marked as the default datasource

#### Scenario: All six dashboards are provisioned

- **WHEN** Grafana has finished startup
- **THEN** the dashboards `Platform Overview`, `AI Pipeline`, `Infrastructure`, `Token Cost`, `RAG Quality`, `Cache Hit Rate` are loadable via the Grafana UI without any manual import

### Requirement: Observability stack is always-on (no opt-out profile)

The `prometheus`, `grafana`, `vector`, `loki`, `otel-collector`, `tempo`, `postgres-exporter`, and `redis-exporter` services in `docker-compose.yaml` SHALL run by default with no `profiles:` attribute. There SHALL NOT be a `--profile no-observability` opt-out — observability is part of the always-on happy path. Operators who do not want it must comment the services out manually.

#### Scenario: Default install includes all observability containers

- **WHEN** `docker compose up -d` is run with no profile flags
- **THEN** all eight observability containers are running

#### Scenario: No opt-out profile exists

- **WHEN** `docker compose --profile no-observability up -d` is run
- **THEN** Docker Compose's default behaviour applies (the unknown profile name is silently ignored)
- **AND** all eight observability containers still start (because none of them have a `profiles:` attribute restricting them)

### Requirement: Retention is bounded for local development

The `prometheus` service SHALL pass `--storage.tsdb.retention.time=72h` to bound disk usage. The `loki` service SHALL configure `retention_period: 168h` (7 days). The `tempo` service SHALL configure `retention: 168h` (7 days).

#### Scenario: Prometheus retention flag is set

- **WHEN** the Prometheus container is started
- **AND** the container's command line is inspected
- **THEN** it includes `--storage.tsdb.retention.time=72h`

### Requirement: Six dashboards cover platform, AI pipeline, infrastructure, cost, quality, cache

Six Grafana dashboards SHALL be checked into `observability/grafana/dashboards/` and provisioned at startup.

| Dashboard | Required panels |
|---|---|
| Platform Overview | request rate per service, error rate per service, p95 latency per service, JVM heap (Java services), Python process memory (Python services) |
| AI Pipeline | tokens per minute by model, provider mix (pie / bar), RAG hit-rate (above_threshold / total), memory parse-failure rate, MCP tool call rate by tool |
| Infrastructure | Qdrant collection sizes, Redis ops/sec and memory, Postgres connection count, MinIO bucket sizes |
| Token Cost (L1) | Per-provider $/day computed via `gen_ai.client.token.usage` × per-provider pricing rates from `observability/grafana/dashboards/pricing.yaml` |
| RAG Quality (L2) | Heatmap of `rag_top_score_bucket` over time; time-series of retrieval miss-rate; bar chart of ingestion-events-per-hour by source type; embedded Loki logs panel |
| Cache Hit Rate (L3) | `rate(prompt_cache.tokens.read[5m]) / rate(prompt_cache.tokens.total[5m])` per provider; absolute saved-token panel; 0%-flatline annotation per provider |

#### Scenario: Cache Hit Rate dashboard renders after representative traffic

- **WHEN** the stack has been running for 5 minutes and at least 4 chat prompts have been sent (2 against `provider=openai`, 2 against `provider=anthropic`)
- **AND** the `Cache Hit Rate` dashboard is opened
- **THEN** the per-provider cache-hit-rate panel reports a non-zero ratio for both `openai` and `anthropic` rows
- **AND** the absolute-saved-tokens panel reports a non-zero count

#### Scenario: Token Cost dashboard reflects pricing.yaml updates

- **WHEN** an operator edits `observability/grafana/dashboards/pricing.yaml` to change a provider's `per_1k_input` rate
- **AND** Grafana is restarted (`docker compose restart grafana`)
- **THEN** the Token Cost dashboard's $/day panel for that provider reflects the new rate
- **AND** no other dashboard is affected

#### Scenario: Platform Overview renders non-empty data after stack startup

- **WHEN** the stack has been running for 1 minute and any prompt request has been served
- **AND** the `Platform Overview` dashboard is opened
- **THEN** every panel reports at least one data point

### Requirement: Pricing rates committed in version control

The per-provider $/1k-token pricing rates consumed by the L1 Token Cost dashboard SHALL be committed to `observability/grafana/dashboards/pricing.yaml`. The file SHALL be a flat YAML map keyed by provider name with `per_1k_input` and `per_1k_output` numeric fields. Updates SHALL go through git review.

#### Scenario: Pricing file shape

- **WHEN** `observability/grafana/dashboards/pricing.yaml` is read
- **THEN** it parses as a YAML map
- **AND** at minimum it contains entries for `anthropic`, `openai`, `gemini`, `minimax`, `lmstudio`
- **AND** every entry has numeric `per_1k_input` and `per_1k_output` fields

### Requirement: Documentation cross-links the observability stack

`docs/OBSERVABILITY.md` SHALL exist and describe (a) the metrics inventory, (b) how to access Prometheus, Grafana, Loki, Tempo, (c) how to add a new custom metric in either Java or Python, (d) how to add a span attribute, (e) the cardinality discipline rules, (f) the Vector → Datadog migration recipe, (g) how to update `pricing.yaml` for the L1 dashboard. The root `README.md` Documentation section SHALL link to it.

#### Scenario: Observability doc exists and is linked

- **WHEN** the repository is checked out
- **THEN** `docs/OBSERVABILITY.md` exists
- **AND** the root `README.md` contains a markdown link whose target is `docs/OBSERVABILITY.md`
