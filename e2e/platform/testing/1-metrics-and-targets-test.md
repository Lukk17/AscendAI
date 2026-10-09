# Metrics and targets: e2e test

## What this verifies

- Every scrape job of `infra/observability/prometheus/prometheus.yaml` reports `health` `up` in Prometheus.
- The metric names the services serve without any model call are present: `jvm_memory_used_bytes`, `http_server_requests_seconds_count` and `python_info`.
- Grafana serves the three provisioned datasources `Prometheus`, `Loki` and `Tempo`.
- Grafana search lists the six dashboards of task 13: `Platform Overview`, `AI Pipeline`, `Infrastructure`, `L1 - Token Cost`, `L2 - RAG Quality` and `L3 - Cache Hit Rate`.
- An anonymous `POST /api/dashboards/db` is refused with 401 or 403, never 200.

## Prerequisites

Bruno CLI installed, the always-on stack running, Prometheus ready, Grafana healthy.

```bash
bru --version
```

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7077/-/ready
```

The second command prints `200`.

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7078/api/health
```

The third command prints `200`.

## Reset state

None. This test writes no persisted state.

## Run

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "platform/observability/prometheus-targets.yml" --env ascend-local --env-var "expectedJobs=ascend-agent,ascend-weather-mcp,ascend-memory,ascend-audio-scribe,ascend-web-hunter,ascend-ocr,container-metrics-exporter,qdrant,redis,postgres"
```

The `expectedJobs` value holds every scrape job of `infra/observability/prometheus/prometheus.yaml`, because every service runs while this change lands.

```bash
bru run "platform/observability/metric-names.yml" --env ascend-local
```

```bash
bru run "platform/observability/grafana-datasources.yml" --env ascend-local
```

```bash
bru run "platform/observability/grafana-dashboards.yml" --env ascend-local
```

```bash
bru run "platform/observability/grafana-anonymous-write.yml" --env ascend-local
```

## Expected

- Each Bruno request answers HTTP 200, except `grafana-anonymous-write.yml` which answers 401 or 403 and never 200.
- Every name of the `expectedJobs` list has at least one active Prometheus target, and every such target reports `health` `up`.
- The `__name__` values hold `jvm_memory_used_bytes`, `http_server_requests_seconds_count` and `python_info`.
- The datasource list holds `Prometheus`, `Loki` and `Tempo`.
- The dashboard search holds all six dashboard titles of task 13.

## Fixtures

None.
