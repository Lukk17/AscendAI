# AscendAI Configuration Reference

Runtime settings that vary per deployment, read from the environment by `compose.yaml`
(each as `VAR=${VAR:-default}`) and the service configuration files. The defaults
below match the compose lines. `fix-linux-docker-host-access` (build group 1)
extends this file with its inventory rows; settings added by other changes carry
their own change name in Added by.

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `prometheus` | `PROMETHEUS_SCRAPE_INTERVAL` | `15s` | Global scrape interval, rendered into `prometheus.yaml` at container start | `add-observability` |
| `prometheus` | `PROMETHEUS_EVALUATION_INTERVAL` | `15s` | Global rule evaluation interval, rendered into `prometheus.yaml` at container start | `add-observability` |
| `prometheus` | `OBSERVABILITY_CLUSTER_LABEL` | `ascend-ai-local` | External `cluster` label, rendered into `prometheus.yaml` at container start | `add-observability` |
| `prometheus` | `PROMETHEUS_QDRANT_TARGET` | `host.docker.internal:6333` | Qdrant scrape target, rendered into `prometheus.yaml` at container start | `add-observability` |
| `prometheus` | `PROMETHEUS_HOST_PORT` | `7077` | Published host port for the Prometheus UI and API | `add-observability` |
| `prometheus` | `PROMETHEUS_RETENTION_TIME` | `72h` | Metrics retention window (`--storage.tsdb.retention.time`) | `add-observability` |
| `grafana` | `GRAFANA_HOST_PORT` | `7078` | Published host port for the Grafana UI | `add-observability` |
| `grafana` | `GF_SERVER_ROOT_URL` | `http://localhost:7078` | Grafana's own root URL setting | `add-observability` |
| `grafana` | `PROMETHEUS_SCRAPE_INTERVAL` | `15s` | Same setting as Prometheus, read by the `timeInterval` of the `Prometheus` datasource | `add-observability` |
| `grafana` | `GRAFANA_LOKI_MAX_LINES` | `1000` | `maxLines` of the `Loki` datasource | `add-observability` |
| `grafana` | `GRAFANA_DASHBOARDS_UPDATE_INTERVAL_SECONDS` | `30` | `updateIntervalSeconds` of the dashboard file provider | `add-observability` |
| `loki` | `LOKI_RETENTION_PERIOD` | `2160h` | Log retention window | `add-observability` |
| `loki` | `LOKI_RETENTION_DELETE_DELAY` | `2h` | Delay before deleted log data is dropped | `add-observability` |
| `loki` | `LOKI_RESULTS_CACHE_MAX_SIZE_MB` | `100` | Embedded results-cache size for range queries | `add-observability` |
| `tempo` | `TEMPO_BLOCK_RETENTION` | `2160h` | Trace block retention window (backend scheduler and backend worker compaction) | `add-observability` |
| `tempo` | `TEMPO_LOG_LEVEL` | `info` | Tempo server log level | `add-observability` |
| `tempo` | `TEMPO_MAX_BLOCK_DURATION` | `5m` | Longest time span kept in one live-store block | `add-observability` |
| `tempo` | `TEMPO_SEARCH_DURATION_SLO` | `5s` | Search duration objective reported by the frontend | `add-observability` |
| `tempo` | `TEMPO_SEARCH_THROUGHPUT_BYTES_SLO` | `1073741824` | Search throughput objective in bytes | `add-observability` |
| `tempo` | `TEMPO_TRACE_BY_ID_DURATION_SLO` | `5s` | Trace-by-ID duration objective reported by the frontend | `add-observability` |
| `tempo` | `OBSERVABILITY_CLUSTER_LABEL` | `ascend-ai-local` | Same setting as Prometheus, external `cluster` label of generated metrics | `add-observability` |
| `otel-collector` | `COLLECTOR_MEMORY_CHECK_INTERVAL` | `1s` | Memory limiter check interval | `add-observability` |
| `otel-collector` | `COLLECTOR_MEMORY_LIMIT_MIB` | `256` | Memory limiter ceiling in MiB | `add-observability` |
| `otel-collector` | `COLLECTOR_MEMORY_SPIKE_LIMIT_MIB` | `64` | Memory limiter spike allowance in MiB | `add-observability` |
| `otel-collector` | `COLLECTOR_BATCH_TIMEOUT` | `1s` | Batch processor send timeout | `add-observability` |
| `otel-collector` | `COLLECTOR_BATCH_SIZE` | `1024` | Batch processor send size | `add-observability` |
| `redis-exporter` | `REDIS_ADDR` | `redis://host.docker.internal:6379` | Redis address the exporter scrapes | `add-observability` |
| `postgres-exporter` | `DATA_SOURCE_URI` | `host.docker.internal:5432/ascend_ai?sslmode=disable` | Postgres address the exporter scrapes, credentials come from `DATA_SOURCE_USER` and `DATA_SOURCE_PASS` | `add-observability` |
| `ascend-weather-mcp` | `MANAGEMENT_OTLP_TRACING_ENDPOINT` | `http://otel-collector:4318/v1/traces` | OTLP trace export endpoint | `add-observability` |
| `ascend-weather-mcp` | `MANAGEMENT_TRACING_SAMPLING_PROBABILITY` | `1.0` | Trace sampling probability | `add-observability` |
| `ascend-weather-mcp` | `WEATHER_MCP_HOST_PORT` | `9998` | Published host port | `add-observability` |
| `ascend-audio-scribe` | `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | OTLP trace export endpoint, unset in standalone mode | `add-observability` |
| `ascend-audio-scribe` | `HF_CACHE_ROOT` | `hf-cache` | The source of the `/hf-cache` mount, the Hugging Face model cache, unset means a named volume and a host path means a bind mount | `fix-linux-docker-host-access` |
| `ascend-audio-scribe` | `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT` | `ascend-audio-scribe-media` | The source of the `/audio` mount, unset means a named volume and a host path means a bind mount | `fix-linux-docker-host-access` |
| `container-metrics-exporter` | `DOCKER_SOCKET_GID` | `0` | The group id of `/var/run/docker.sock` on the Docker host that `group_add` gives the exporter user, 0 for Docker Desktop, on Docker Engine for Linux the number `stat -c %g /var/run/docker.sock` prints | `fix-linux-docker-host-access` |
