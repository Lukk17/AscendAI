# Metrics and targets: e2e test

## What this verifies

- Every scrape job of `infra/observability/prometheus/prometheus.yaml` reports `health` `up` in Prometheus.
- The metric names the services serve without any model call are present: `jvm_memory_used_bytes`, `http_server_requests_seconds_count`, `python_info` and `memory_operations_total`.
- One memory insert for the user `frostyObservabilityTest` through the `openai` provider answers 200, so the memory service serves an `operation="insert", outcome="ok"` series of `memory_operations_total` and not only the failure and wipe series a quiet stack carries.
- Grafana serves the three provisioned datasources `Prometheus`, `Loki` and `Tempo`.
- Grafana search lists the six dashboards of task 13: `Platform Overview`, `AI Pipeline`, `Infrastructure`, `L1 - Token Cost`, `L2 - RAG Quality` and `L3 - Cache Hit Rate`.
- An anonymous `POST /api/dashboards/db` is refused with 401 or 403, never 200.

## Prerequisites

Bruno CLI installed, the always-on stack running, Prometheus ready, Grafana healthy, the memory service healthy, and the memory service able to reach the `openai` embedding provider.

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

```bash
curl -s -o /dev/null -w "%{http_code}" http://localhost:7020/health
```

The fourth command prints `200`.

## Reset state

Remove the memory points an earlier run of this spec left for its own user before starting, so the run is reproducible. The command is idempotent. Run the same wipe in Post-run cleanup.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyObservabilityTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyObservabilityTest"}`.

## Run

```bash
cd docs/api/request/AscendAI
```

```bash
bru run "platform/observability/prometheus-targets.yml" --env ascend-local --env-var "expectedJobs=ascend-agent,ascend-weather-mcp,ascend-memory,ascend-audio-scribe,ascend-web-hunter,ascend-ocr,container-metrics-exporter,qdrant,redis,postgres"
```

The `expectedJobs` value holds every scrape job of `infra/observability/prometheus/prometheus.yaml`, because every service runs while this change lands.

Send the memory canary insert before reading the metric names, because the read proves the memory service serves an insert series of `memory_operations_total`.

```bash
bru run "platform/observability/memory-insert-canary.yml" --env ascend-local
```

Wait 15 seconds so Prometheus scrapes the series the canary created (the scrape interval is 15 seconds per task 1.1).

```bash
sleep 15
```

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

## Post-run cleanup

The canary insert writes semantic-memory points for `frostyObservabilityTest` in the Qdrant collections AscendMemory writes to. Remove them so the run leaves the system exactly as it found it. Run this regardless of whether the Run step passed or failed. The command is idempotent.

```bash
curl -sS -X POST "http://localhost:7020/api/v1/memory/wipe?user_id=frostyObservabilityTest"
```

Expect `{"status":"success","message":"All memories wiped for user frostyObservabilityTest"}`.

## Expected

- Each Bruno request answers HTTP 200, except `grafana-anonymous-write.yml` which answers 401 or 403 and never 200.
- Every name of the `expectedJobs` list has at least one active Prometheus target, and every such target reports `health` `up`.
- The `__name__` values hold `jvm_memory_used_bytes`, `http_server_requests_seconds_count`, `python_info` and `memory_operations_total`.
- The canary insert answers 200 with at least one stored memory carrying an `id`, and the post-run wipe answers `{"status":"success", ...}`.
- The datasource list holds `Prometheus`, `Loki` and `Tempo`.
- The dashboard search holds all six dashboard titles of task 13.

## Fixtures

None.
