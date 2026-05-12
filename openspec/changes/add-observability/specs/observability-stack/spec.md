## ADDED Requirements

### Requirement: Prometheus runs in docker-compose with checked-in scrape config

`docker-compose.yaml` SHALL define a `prometheus` service that uses a checked-in `observability/prometheus/prometheus.yml` configuration. The Prometheus instance SHALL scrape every AscendAI application service plus the data-layer prerequisites that natively expose metrics (Qdrant, MinIO).

#### Scenario: Prometheus targets are healthy after stack startup

- **WHEN** `docker compose up -d` completes and 30 seconds elapse
- **AND** `GET http://localhost:9090/api/v1/targets` is invoked
- **THEN** every target with `job` ∈ {`ascend-agent`, `audio-scribe`, `ascend-web-search`, `ascend-memory`, `paddle-ocr`, `weather-mcp`} reports `health="up"`

#### Scenario: Scrape interval is 15 seconds by default

- **WHEN** the Prometheus configuration is loaded
- **THEN** the global `scrape_interval` is 15s and individual jobs may override it but no override is shorter than 5s

### Requirement: Grafana runs in docker-compose with provisioned datasource and dashboards

`docker-compose.yaml` SHALL define a `grafana` service exposed on host port `3030` with anonymous Viewer access enabled by default. Grafana SHALL be provisioned at startup with the Prometheus datasource and the three checked-in dashboards.

#### Scenario: Grafana is reachable after stack startup

- **WHEN** `docker compose up -d` completes and 30 seconds elapse
- **AND** `GET http://localhost:3030/api/health` is invoked
- **THEN** the response status is 200

#### Scenario: Prometheus datasource is provisioned

- **WHEN** Grafana has finished startup
- **AND** `GET http://localhost:3030/api/datasources` is invoked
- **THEN** the response includes a datasource named `Prometheus` of type `prometheus` pointing at `http://prometheus:9090`

#### Scenario: Three dashboards are provisioned

- **WHEN** Grafana has finished startup
- **THEN** the dashboards `Platform Overview`, `AI Pipeline`, and `Infrastructure` are loadable via the Grafana UI without any manual import

### Requirement: Observability stack is opt-out via Docker Compose profile

The `prometheus` and `grafana` services SHALL be assigned a profile such that running `docker compose --profile no-observability up -d` starts the application stack without these two services. The default `docker compose up -d` SHALL include both services.

#### Scenario: Default install includes observability

- **WHEN** `docker compose up -d` is run with no profile flags
- **THEN** the `prometheus` and `grafana` containers are running

#### Scenario: Opt-out profile excludes observability

- **WHEN** `docker compose --profile no-observability up -d` is run
- **THEN** neither `prometheus` nor `grafana` containers are running

### Requirement: Prometheus retention is bounded for local development

The `prometheus` service in `docker-compose.yaml` SHALL pass `--storage.tsdb.retention.time=72h` to the Prometheus binary so that local-dev disk usage is capped.

#### Scenario: Retention flag is set

- **WHEN** the Prometheus container is started
- **AND** the container's command line is inspected
- **THEN** it includes `--storage.tsdb.retention.time=72h`

### Requirement: Three dashboards cover platform, AI pipeline, infrastructure

Three Grafana dashboards SHALL be checked into `observability/grafana/dashboards/` and provisioned at startup.

| Dashboard | Required panels |
|---|---|
| Platform Overview | request rate per service, error rate per service, p95 latency per service, JVM heap (Java services), Python process memory (Python services) |
| AI Pipeline | tokens per minute by model, provider mix (pie / bar), RAG hit-rate (above_threshold / total), memory parse-failure rate, MCP tool call rate by tool |
| Infrastructure | Qdrant collection sizes, Redis ops/sec and memory, Postgres connection count, MinIO bucket sizes |

#### Scenario: Platform Overview renders non-empty data after stack startup

- **WHEN** the stack has been running for 1 minute and any prompt request has been served
- **AND** the `Platform Overview` dashboard is opened
- **THEN** every panel reports at least one data point

### Requirement: Documentation cross-links the observability stack

`docs/OBSERVABILITY.md` SHALL exist and describe (a) the metrics inventory, (b) how to access Prometheus and Grafana, (c) how to add a new custom metric in either Java or Python, (d) the cardinality discipline rules. The root `README.md` Documentation section SHALL link to it.

#### Scenario: Observability doc exists and is linked

- **WHEN** the repository is checked out
- **THEN** `docs/OBSERVABILITY.md` exists
- **AND** the root `README.md` contains a markdown link whose target is `docs/OBSERVABILITY.md`
