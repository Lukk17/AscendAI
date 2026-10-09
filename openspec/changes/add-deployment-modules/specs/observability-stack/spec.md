## MODIFIED Requirements

### Requirement: Prometheus runs in docker-compose with checked-in scrape config

`compose.yaml` SHALL define a `prometheus` service that uses a checked-in `infra/observability/prometheus/prometheus.yaml` configuration (`.yaml` extension to match the repo's YAML convention). The Prometheus instance SHALL scrape every AscendAI application service plus the data-layer prerequisites that publish metrics (Qdrant native, Redis via `redis_exporter`, Postgres via `postgres_exporter`). The S3-compatible object store publishes no Prometheus endpoint and is not scraped.

#### Scenario: Prometheus targets are healthy after stack startup

- **WHEN** `docker compose up -d` completes with `COMPOSE_PROFILES` set to the `personal` preset (which holds every switchable module, so every scraped service runs) and 30 seconds elapse
- **AND** `GET http://localhost:7077/api/v1/targets` is invoked
- **THEN** every target with `job` in {`ascend-agent`, `ascend-audio-scribe`, `ascend-web-hunter`, `ascend-memory`, `ascend-ocr`, `ascend-weather-mcp`, `qdrant`, `redis`, `postgres`} reports `health="up"`

#### Scenario: Scrape interval is 15 seconds by default

- **WHEN** the Prometheus configuration is loaded
- **THEN** the global `scrape_interval` is 15s and individual jobs may override it but no override is shorter than 5s

### Requirement: Observability stack is always-on (no opt-out profile)

The `prometheus`, `grafana`, `loki`, `otel-collector`, `tempo`, `postgres-exporter`, `redis-exporter` and `container-metrics-exporter` services in `compose.yaml` SHALL run by default with no `profiles:` attribute, whatever `COMPOSE_PROFILES` holds. Monitoring is core and SHALL NOT be a switchable deployment module. There SHALL NOT be a `--profile no-observability` opt-out: observability is part of the always-on happy path. Every service SHALL export its traces to the collector whenever its OTLP endpoint is set, and `compose.yaml` sets it for every service.

#### Scenario: Default install includes all observability containers

- **WHEN** `docker compose up -d` is run with no profile flags
- **THEN** all eight observability containers are running

#### Scenario: Observability runs with no switchable module

- **WHEN** `docker compose up -d` is run with `COMPOSE_PROFILES` empty (the `core` preset)
- **THEN** all eight observability containers are running
- **AND** after one chat turn a trace of it reaches Tempo

#### Scenario: No opt-out profile exists

- **WHEN** `docker compose --profile no-observability up -d` is run
- **THEN** Docker Compose's default behaviour applies (the unknown profile name is silently ignored)
- **AND** all eight observability containers still start (because none of them have a `profiles:` attribute restricting them)
