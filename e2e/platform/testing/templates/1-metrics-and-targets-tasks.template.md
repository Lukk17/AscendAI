# Metrics and targets: run tasks template

Spec: [../1-metrics-and-targets-test.md](../1-metrics-and-targets-test.md)

Copy this file to `../runs/<UTC-timestamp>_1-metrics-and-targets-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] Prometheus `/-/ready` prints `200`
- [ ] Grafana `/api/health` prints `200`

### Reset state

- [ ] None required

### Run

- [ ] `bru run "platform/observability/prometheus-targets.yml" --env ascend-local --env-var "expectedJobs=..."` passes
- [ ] `bru run "platform/observability/metric-names.yml" --env ascend-local` passes
- [ ] `bru run "platform/observability/grafana-datasources.yml" --env ascend-local` passes
- [ ] `bru run "platform/observability/grafana-dashboards.yml" --env ascend-local` passes
- [ ] `bru run "platform/observability/grafana-anonymous-write.yml" --env ascend-local` passes

### Expected

- [ ] All requests answer HTTP 200, except the anonymous write which answers 401 or 403 and never 200
- [ ] Every expected job has at least one active target and every such target reports `health` `up`
- [ ] The `__name__` values hold `jvm_memory_used_bytes`, `http_server_requests_seconds_count` and `python_info`
- [ ] The datasource list holds `Prometheus`, `Loki` and `Tempo`
- [ ] The dashboard search holds all six dashboard titles of task 13

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
