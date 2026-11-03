## ADDED Requirements

### Requirement: Prometheus runs in docker-compose with checked-in scrape config

`compose.yaml` SHALL define a `prometheus` service that uses a checked-in `infra/observability/prometheus/prometheus.yaml` configuration (`.yaml` extension to match the repo's YAML convention). The Prometheus instance SHALL scrape every AscendAI application service plus the data-layer prerequisites that publish metrics (Qdrant native, Redis via `redis_exporter`, Postgres via `postgres_exporter`). The S3-compatible object store publishes no Prometheus endpoint and is not scraped. Each application job SHALL find its targets through DNS service discovery on the compose service name, so every running container of a service is scraped as its own target (owner answer 87 of 2026-10-08).

#### Scenario: Prometheus targets are healthy after stack startup

- **WHEN** `docker compose up -d` completes and 30 seconds elapse
- **AND** `GET http://localhost:7077/api/v1/targets` is invoked
- **THEN** every target with `job` ∈ {`ascend-agent`, `ascend-audio-scribe`, `ascend-web-hunter`, `ascend-memory`, `ascend-ocr`, `ascend-weather-mcp`, `qdrant`, `redis`, `postgres`} reports `health="up"`

#### Scenario: Prometheus scrapes every instance

- **WHEN** two containers of the same application service run
- **AND** the Prometheus targets page is read
- **THEN** that service's job lists two targets, one per container, each with its own `instance` label and state `up`

#### Scenario: Scrape interval is 15 seconds by default

- **WHEN** the Prometheus configuration is loaded with `PROMETHEUS_SCRAPE_INTERVAL` unset
- **THEN** the global `scrape_interval` is 15s and individual jobs may override it but no override is shorter than 5s

### Requirement: Logs ship to Loki through the OpenTelemetry collector

`compose.yaml` SHALL define a `loki` service and SHALL NOT define a `vector` service (owner answer 89.12 of 2026-10-08). The `otel-collector` service SHALL read the stdout and stderr of every running container of the six AscendAI application services (`ascend-agent`, `ascend-weather-mcp`, `ascend-memory`, `ascend-audio-scribe`, `ascend-web-hunter`, `ascend-ocr`) from their Docker `json-file` log files, through one `filelog` receiver with the `container` parser per container, started by `receiver_creator` from the `docker_observer` extension, and SHALL send them to Loki's OTLP endpoint through the `otlphttp` exporter. Loki SHALL keep `service` (the compose service name) and `source` (`docker`) as stream labels, and the body of each entry SHALL be the original log line. Every container of a service SHALL carry the same `service` label, and its container name SHALL be kept as structured metadata. The collector configuration SHALL document the move to another log backend with commented exporter stanzas.

#### Scenario: Log line reaches Loki within 5 seconds

- **WHEN** any AscendAI service writes a log line to stdout
- **AND** `{service="<that-service>"}` is queried via Grafana's Logs panel within 5 seconds
- **THEN** the line is returned once, with its text unchanged
- **AND** the entry carries the label `source="docker"`

#### Scenario: No Vector service

- **WHEN** `docker compose config --services` is run
- **THEN** the output holds `otel-collector` and `loki`
- **AND** the output holds no `vector`

#### Scenario: Two containers of one service share the service label

- **WHEN** two running containers of the same compose service each write a log line
- **THEN** both lines are returned by `{service="<that-service>"}`
- **AND** their structured metadata holds two different container names

#### Scenario: Collector config documents migration exporters

- **WHEN** `infra/observability/otel-collector/otel-collector-config.yaml` is read
- **THEN** the file contains commented exporter stanzas for `datadog`, `awscloudwatchlogs` and `splunk_hec` showing the migration recipe

### Requirement: Traces ship to Tempo via the OTel collector

`compose.yaml` SHALL define an `otel-collector` service and a `tempo` service. The OTel collector SHALL accept OTLP receivers on gRPC `:4317` and HTTP `:4318`, batch and memory-limit-process spans, and export to Tempo via OTLP. ascend-agent and ascend-weather-mcp SHALL be configured with `management.otlp.tracing.endpoint=http://otel-collector:4318/v1/traces` and `management.tracing.sampling.probability=1.0` so Spring AI's auto-emitted spans land in Tempo. That is the Spring Boot 3.5.14 property name, which `upgrade-spring-boot-4` later renames in its D12, and the services SHALL NOT rely on `OTEL_EXPORTER_OTLP_ENDPOINT`. Python services SHALL be configured equivalently through their own OpenTelemetry FastAPI instrumentation, which exports OTLP gRPC to `http://otel-collector:4317` from `OTEL_EXPORTER_OTLP_ENDPOINT`.

#### Scenario: A single chat turn produces a queryable trace

- **WHEN** ascend-agent serves one `POST /api/v1/ai/prompt` request
- **AND** Tempo is queried via Grafana's Tempo datasource within 10 seconds
- **THEN** a trace with `service.name=ascend-agent` exists for that request
- **AND** the trace contains at least one Spring AI auto-emitted LLM-call span

### Requirement: Grafana runs in docker-compose with provisioned datasources and six dashboards

`compose.yaml` SHALL define a `grafana` service exposed on host port `7078` (container port `3000`) with anonymous Viewer access enabled by default. Grafana SHALL be provisioned at startup with three datasources (`Prometheus`, `Loki`, `Tempo`) and six checked-in dashboards (`Platform Overview`, `AI Pipeline`, `Infrastructure`, `Token Cost`, `RAG Quality`, `Cache Hit Rate`).

#### Scenario: Grafana is reachable after stack startup

- **WHEN** `docker compose up -d` completes and 30 seconds elapse
- **AND** `GET http://localhost:7078/api/health` is invoked
- **THEN** the response status is 200

#### Scenario: All three datasources are provisioned

- **WHEN** Grafana has finished startup
- **AND** `GET http://localhost:7078/api/datasources` is invoked
- **THEN** the response includes datasources named `Prometheus`, `Loki`, `Tempo` of the corresponding types
- **AND** `Prometheus` is marked as the default datasource

#### Scenario: All six dashboards are provisioned

- **WHEN** Grafana has finished startup
- **THEN** the dashboards `Platform Overview`, `AI Pipeline`, `Infrastructure`, `Token Cost`, `RAG Quality`, `Cache Hit Rate` are loadable via the Grafana UI without any manual import

### Requirement: Observability stack is always-on (no opt-out profile)

The `prometheus`, `grafana`, `loki`, `otel-collector`, `tempo`, `postgres-exporter`, `redis-exporter` and `container-metrics-exporter` services in `compose.yaml` SHALL run by default with no `profiles:` attribute, whatever `COMPOSE_PROFILES` holds. Monitoring is core and SHALL NOT be a switchable deployment module. There SHALL NOT be a `--profile no-observability` opt-out: observability is part of the always-on happy path. Every service SHALL export its traces to the collector whenever its OTLP endpoint is set, and `compose.yaml` SHALL set it for every service.

#### Scenario: Default install includes all observability containers

- **WHEN** `docker compose up -d` is run with no profile flags
- **THEN** all eight observability containers are running

#### Scenario: Observability runs with no switchable module

- **WHEN** `docker compose up -d` is run with `COMPOSE_PROFILES` empty
- **THEN** all eight observability containers are running
- **AND** after one chat turn a trace of it reaches Tempo

#### Scenario: No opt-out profile exists

- **WHEN** `docker compose --profile no-observability up -d` is run
- **THEN** Docker Compose's default behaviour applies (the unknown profile name is silently ignored)
- **AND** all eight observability containers still start (because none of them have a `profiles:` attribute restricting them)

### Requirement: Retention is bounded and configurable in .env

Traces and logs SHALL be kept at least 3 months by default (owner decision 65.21 of 2026-10-04). The `loki` service SHALL set `limits_config.retention_period` from `LOKI_RETENTION_PERIOD` (default `2160h`) and the `tempo` service SHALL set `compactor.compaction.block_retention` from `TEMPO_BLOCK_RETENTION` (default `2160h`), both started with `-config.expand-env=true`. The `prometheus` service SHALL pass `--storage.tsdb.retention.time` from `PROMETHEUS_RETENTION_TIME` (default `72h`). All three variables SHALL be listed with their defaults in the configuration reference (owner rule 98 of 2026-10-08), and the root `.env.example` SHALL hold no line for them.

#### Scenario: Default retention

- **WHEN** the stack starts with none of the three variables set
- **THEN** Loki's effective `retention_period` and Tempo's effective `block_retention` are `2160h`
- **AND** the Prometheus command line includes `--storage.tsdb.retention.time=72h`

#### Scenario: Retention changed in .env

- **WHEN** `.env` sets `LOKI_RETENTION_PERIOD=720h`, `TEMPO_BLOCK_RETENTION=720h` and `PROMETHEUS_RETENTION_TIME=168h` and the stack is recreated
- **THEN** Loki and Tempo report `720h` in their effective configuration (`/config` endpoint of each)
- **AND** the Prometheus command line includes `--storage.tsdb.retention.time=168h`

### Requirement: Six dashboards cover platform, AI pipeline, infrastructure, cost, quality, cache

Six Grafana dashboards SHALL be checked into `infra/observability/grafana/dashboards/` and provisioned at startup.

| Dashboard | Required panels |
|---|---|
| Platform Overview | request rate per service, error rate per service, p95 latency per service, JVM heap (Java services), Python process memory (Python services) |
| AI Pipeline | tokens per minute by model, provider mix (pie / bar), RAG hit-rate (above_threshold / total), memory parse-failure rate, MCP tool call rate by tool |
| Infrastructure | Qdrant collection sizes, Redis ops/sec and memory, Postgres connection count |
| Token Cost (L1) | Per-provider $/day computed via `gen_ai_client_token_usage_total` multiplied by the price series `token_price_usd_per_1k` that Prometheus records from `infra/observability/grafana/dashboards/pricing.yaml`. The dashboard holds no rate of its own |
| RAG Quality (L2) | Heatmap of `rag_top_score_bucket` over time; time-series of retrieval miss-rate; bar chart of ingestion-events-per-hour by source type; embedded Loki logs panel |
| Cache Hit Rate (L3) | `rate(prompt_cache_tokens_read_total[5m])` divided by the input series of `gen_ai_client_token_usage_total` (`gen_ai_token_type="input"`) per provider; absolute saved-token panel; 0%-flatline annotation per provider |

#### Scenario: Cache Hit Rate dashboard renders after representative traffic

- **WHEN** the stack has been running for 5 minutes and at least 4 chat prompts have been sent (2 against `provider=openai`, 2 against `provider=anthropic`)
- **AND** the `Cache Hit Rate` dashboard is opened
- **THEN** the per-provider cache-hit-rate panel reports a non-zero ratio for both `openai` and `anthropic` rows
- **AND** the absolute-saved-tokens panel reports a non-zero count

#### Scenario: Token Cost dashboard reflects pricing.yaml updates

- **WHEN** an operator edits `infra/observability/grafana/dashboards/pricing.yaml` to change a provider's `input_per_1k` rate
- **AND** Prometheus is restarted (`docker compose restart prometheus`)
- **THEN** the Token Cost dashboard's $/day panel for that provider reflects the new rate
- **AND** no other dashboard is affected

#### Scenario: Platform Overview renders non-empty data after stack startup

- **WHEN** the stack has been running for 1 minute and any prompt request has been served
- **AND** the `Platform Overview` dashboard is opened
- **THEN** every panel reports at least one data point

### Requirement: Pricing rates committed in version control

The per-provider $/1k-token pricing rates consumed by the L1 Token Cost dashboard SHALL be committed to `infra/observability/grafana/dashboards/pricing.yaml`. The file SHALL hold a top-level `providers:` map keyed by provider name, each entry with the numeric fields `input_per_1k` and `output_per_1k`. Updates SHALL go through git review. The file SHALL be the only place a rate is written (owner answer 89.13 of 2026-10-08): when the `prometheus` container starts it SHALL record each rate as the series `token_price_usd_per_1k` with the labels `gen_ai_system` and `gen_ai_token_type`, and no dashboard and no committed rule file SHALL hold a copy of a rate.

#### Scenario: Pricing file shape

- **WHEN** `infra/observability/grafana/dashboards/pricing.yaml` is read
- **THEN** it parses as a YAML map with a `providers` map
- **AND** at minimum `providers` contains entries for `anthropic`, `openai`, `gemini`, `minimax`, `lmstudio`
- **AND** every entry has numeric `input_per_1k` and `output_per_1k` fields

#### Scenario: Prometheus records every rate from the file

- **WHEN** the `prometheus` container has started
- **AND** `token_price_usd_per_1k` is queried on `http://localhost:7077/api/v1/query`
- **THEN** there is one series per provider of `pricing.yaml` and per token type `input` and `output`
- **AND** each value equals the matching rate of `pricing.yaml`

#### Scenario: No dashboard holds a rate

- **WHEN** `infra/observability/grafana/dashboards/token-cost.json` is read
- **THEN** none of its queries holds a numeric rate
- **AND** every cost query multiplies by `token_price_usd_per_1k`

#### Scenario: A broken price file stops Prometheus

- **WHEN** `pricing.yaml` has a provider without `output_per_1k`
- **AND** the `prometheus` container starts
- **THEN** the container exits with a non-zero code instead of serving a cost from a missing rate

### Requirement: Operational values of the observability stack are settings

Every value of the observability containers and of the tracing wiring that has a default and that an operator might need to change SHALL be read from an environment variable that `compose.yaml` passes as `${VAR:-default}` on the service that reads it, with the same default in the configuration file or the code (owner rule 98 of 2026-10-08): the scrape and evaluation intervals, the cluster label, the Qdrant target and the published port of Prometheus, the published port, root address, Loki line limit and dashboard reload interval of Grafana, the retention and cache values of Loki, the block, search and log values of Tempo, the memory and batch values of the OpenTelemetry collector, the OTLP endpoint and sampling probability of the Java services, the OTLP endpoint of the Python services and the data store addresses of the Redis and Postgres exporters. A secret SHALL have no default. Each setting SHALL have its row in the configuration reference.

#### Scenario: Defaults hold with nothing set

- **WHEN** the stack starts with none of these variables set
- **THEN** `GET http://localhost:7077/api/v1/status/config` shows `scrape_interval: 15s` and the external label `cluster: ascend-ai-local`
- **AND** Grafana answers on host port `7078`

#### Scenario: A changed value reaches the container

- **WHEN** `.env` sets `PROMETHEUS_SCRAPE_INTERVAL=30s` and the `prometheus` service is recreated
- **THEN** `GET http://localhost:7077/api/v1/status/config` shows `scrape_interval: 30s`

### Requirement: The monitoring stack runs the latest stable release of each program

The `prometheus`, `grafana`, `loki`, `tempo` and `otel-collector` services of `compose.yaml` SHALL run the latest stable release of their program at the time they are pinned, each image pinned by version tag and digest (owner rule 105.2 of 2026-10-09), with every configuration change the program's upgrade guide requires for that version. The dependency charts of the Helm chart of `plan-scaled-deployment` follow the same rule, so Compose and the chart run the same programs.

#### Scenario: Every monitoring image is pinned by version and digest

- **WHEN** `compose.yaml` is read
- **THEN** each of the five services names its image as `<name>:<version>@sha256:<digest>`
- **AND** each version is the latest stable release of that program recorded in the task that pinned it

#### Scenario: The upgraded stack works end to end

- **WHEN** the five services start on their new versions
- **THEN** every active Prometheus target reports `up`, Loki and Tempo answer `/ready` with 200, and the six dashboards and three datasources load as the anonymous Viewer
- **AND** a log line reaches Loki and a trace reaches Tempo

### Requirement: Documentation cross-links the observability stack

`docs/OBSERVABILITY.md` SHALL exist and describe (a) the metrics inventory, (b) how to access Prometheus, Grafana, Loki, Tempo, (c) how to add a new custom metric in either Java or Python, (d) how to add a span attribute, (e) the cardinality discipline rules, (f) the recipe to send logs to another backend by adding an exporter to the collector's `logs` pipeline, (g) how to update `pricing.yaml` for the L1 dashboard, which needs `docker compose restart prometheus`. The root `README.md` Documentation section SHALL link to it.

#### Scenario: Observability doc exists and is linked

- **WHEN** the repository is checked out
- **THEN** `docs/OBSERVABILITY.md` exists
- **AND** the root `README.md` contains a markdown link whose target is `docs/OBSERVABILITY.md`
