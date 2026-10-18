# AscendAI Configuration Reference

Runtime settings that vary per deployment, read from the environment by `compose.yaml`
(each as `VAR=${VAR:-default}`) and the service configuration files. The defaults
below match the compose lines. `fix-linux-docker-host-access` (build group 1)
extends this file with its inventory rows; settings added by other changes carry
their own change name in Added by. Each section below covers one service or container
in the order the compose files list them; the four services with their own reference
link to it instead of repeating rows.

---

### docling-serve

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `docling-serve` | `DOCLING_SERVE_HOST_PORT` | `5001` | The host port of `docling-serve` | `fix-linux-docker-host-access` |
| `docling-serve` | `DOCLING_SERVE_ENABLE_UI` | `1` | Fixed in `compose.yaml`. Enables the Docling Serve UI. | `existing` |
| `docling-serve` | `DOCLING_SERVE_OCR_ENGINE` | `easyocr` | Fixed in `compose.yaml`. The OCR engine Docling Serve uses. | `existing` |
| `docling-serve` | `UVICORN_WORKERS` | `2` | Fixed in `compose.yaml`. Uvicorn worker count. | `existing` |

---

### unstructured-api

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `unstructured-api` | `UNSTRUCTURED_API_HOST_PORT` | `9080` | The host port of `unstructured-api` | `fix-linux-docker-host-access` |

---

### ascend-ocr

The settings of `ascend-ocr` are listed in its own reference, [apps/ascend-ocr/docs/CONFIGURATION.md](../apps/ascend-ocr/docs/CONFIGURATION.md).

---

### ascend-agent

The settings of `ascend-agent` are listed in its own reference, [apps/ascend-agent/docs/CONFIGURATION.md](../apps/ascend-agent/docs/CONFIGURATION.md).

---

### ascend-memory

The settings of `ascend-memory` are listed in its own reference, [apps/ascend-memory/docs/CONFIGURATION.md](../apps/ascend-memory/docs/CONFIGURATION.md).

---

### ascend-weather-mcp

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `ascend-weather-mcp` | `WEATHER_MCP_HOST_PORT` | `9998` | Published host port | `add-observability` |
| `ascend-weather-mcp` | `MANAGEMENT_OTLP_TRACING_ENDPOINT` | `http://otel-collector:4318/v1/traces` | OTLP trace export endpoint | `add-observability` |
| `ascend-weather-mcp` | `MANAGEMENT_TRACING_SAMPLING_PROBABILITY` | `1.0` | Trace sampling probability | `add-observability` |
| `ascend-weather-mcp` | `SPRING_PROFILES_ACTIVE` | `docker` | Fixed in `compose.yaml`. Activates the container-mode overrides. | `existing` |
| `ascend-weather-mcp` | `OTEL_SERVICE_NAME` | `ascend-weather-mcp` | Fixed in `compose.yaml`. Service name carried on every exported span. | `existing` |
| `ascend-weather-mcp` | `OTEL_RESOURCE_ATTRIBUTES` | `service.version=0.0.4` | Fixed in `compose.yaml`. Resource attributes carried on every exported span. | `existing` |

---

### ascend-audio-scribe

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `ascend-audio-scribe` | `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | OTLP trace export endpoint, unset in standalone mode | `add-observability` |
| `ascend-audio-scribe` | `HF_CACHE_ROOT` | `hf-cache` | The source of the `/hf-cache` mount, the Hugging Face model cache, unset means a named volume and a host path means a bind mount. See [Reaching the host from a container](DEPLOYMENT.md#reaching-the-host-from-a-container). | `fix-linux-docker-host-access` |
| `ascend-audio-scribe` | `ASCEND_AUDIO_SCRIBE_MEDIA_ROOT` | `ascend-audio-scribe-media` | The source of the `/audio` mount, unset means a named volume and a host path means a bind mount. See [Reaching the host from a container](DEPLOYMENT.md#reaching-the-host-from-a-container). | `fix-linux-docker-host-access` |
| `ascend-audio-scribe` | `API_PORT` | `7017` | Service port. Compose reads it as `AUDIO_SCRIBE_API_PORT`. | `existing` |
| `ascend-audio-scribe` | `API_HOST` | `0.0.0.0` | Bind address. | `existing` |
| `ascend-audio-scribe` | `LOG_LEVEL` | `INFO` | Log level. | `existing` |
| `ascend-audio-scribe` | `LOG_FORMAT` | `json` | `json` for log sinks, `color` for local terminal output. | `existing` |
| `ascend-audio-scribe` | `OPENAI_API_KEY` | (none, secret in .env) | Required only for the OpenAI transcription backend. | `existing` |
| `ascend-audio-scribe` | `HF_TOKEN` | (none, secret in .env) | Hugging Face Inference API token. Required only for the HF transcription backend. | `existing` |
| `ascend-audio-scribe` | `HF_HOME` | `/hf-cache` | Fixed in `compose.yaml`. The Hugging Face cache directory inside the container. | `existing` |
| `ascend-audio-scribe` | `ALLOWED_PRIVATE_HOSTS` | `host.docker.internal,localhost,127.0.0.1` | Fixed in `compose.yaml`. Hostnames the URI fetch guard may reach at a private address. | `existing` |
| `ascend-audio-scribe` | `MCP_FILE_URI_ROOT` | `/audio` | Fixed in `compose.yaml`. When set, `file://` URIs are jailed to this directory. | `existing` |
| `ascend-audio-scribe` | `MCP_DOWNLOAD_TIMEOUT_SECONDS` | `30.0` | Total wall-clock budget for an MCP HTTP fetch. | `existing` |
| `ascend-audio-scribe` | `OTEL_SERVICE_NAME` | `ascend-audio-scribe` | Fixed in `compose.yaml`. Service name carried on every exported span. | `existing` |
| `ascend-audio-scribe` | `OTEL_RESOURCE_ATTRIBUTES` | `service.version=0.9.4` | Fixed in `compose.yaml`. Resource attributes carried on every exported span. | `existing` |
| `ascend-audio-scribe` | `API_TIMEOUT_SECONDS` | `120` | Upstream HTTP client timeout. | `existing` |
| `ascend-audio-scribe` | `SUPPORTED_AUDIO_EXTENSIONS` | `wav, mp3, flac, m4a, mp4, mpeg, mpga, oga, ogg, webm` | Audio file extensions accepted on upload and URI download. | `existing` |
| `ascend-audio-scribe` | `TEMP_FILE_SUFFIX_DEFAULT` | (empty) | Default temp-file suffix. | `existing` |
| `ascend-audio-scribe` | `TRANSCRIPTION_LANGUAGE` | `en` | Default ISO 639-1 language code. | `existing` |
| `ascend-audio-scribe` | `DEFAULT_MODEL_LOCAL` | `Systran/faster-whisper-large-v3` | Default local transcription model. | `existing` |
| `ascend-audio-scribe` | `CHUNK_LENGTH_MINUTES` | `15` | Chunk length in minutes for long local transcriptions. | `existing` |
| `ascend-audio-scribe` | `TEMPERATURE` | `0.0, 0.2, 0.4, 0.6, 0.8, 1.0` | Fallback temperatures tried by the local backend. | `existing` |
| `ascend-audio-scribe` | `VAD_PARAMETERS` | `min_silence_duration_ms 1000, threshold 0.4` | Voice activity detection parameters of the local backend. | `existing` |
| `ascend-audio-scribe` | `VAD_FILTER` | `true` | Whether the local backend filters non-speech with voice activity detection. | `existing` |
| `ascend-audio-scribe` | `CONDITION_ON_PREVIOUS_TEXT` | `true` | Whether the local backend conditions each segment on the previous text. | `existing` |
| `ascend-audio-scribe` | `BEST_OF` | `5` | Candidate count of the local backend decoder. | `existing` |
| `ascend-audio-scribe` | `BEAM_SIZE` | `10` | Beam size of the local backend decoder. | `existing` |
| `ascend-audio-scribe` | `DEFAULT_MODEL_OPENAI` | `whisper-1` | Default OpenAI transcription model. | `existing` |
| `ascend-audio-scribe` | `OPENAI_API_LIMIT_BYTES` | `23592960` | Per-request byte limit of the OpenAI backend before chunking (22.5 MiB). | `existing` |
| `ascend-audio-scribe` | `TARGET_CHUNK_SIZE_BYTES` | `20971520` | Target chunk size in bytes for OpenAI uploads (20 MiB). | `existing` |
| `ascend-audio-scribe` | `DEFAULT_MODEL_HF` | `openai/whisper-large-v3` | Default Hugging Face transcription model. | `existing` |
| `ascend-audio-scribe` | `HF_CHUNK_LENGTH_SECONDS` | `20` | Chunk length in seconds for Hugging Face uploads. | `existing` |
| `ascend-audio-scribe` | `FFMPEG_PATH` | `ffmpeg` | Absolute or PATH-resolvable ffmpeg binary. | `existing` |
| `ascend-audio-scribe` | `FFPROBE_PATH` | `ffprobe` | Absolute or PATH-resolvable ffprobe binary. | `existing` |
| `ascend-audio-scribe` | `FFMPEG_TIMEOUT_SECONDS` | `180` | Per-invocation ffmpeg timeout. | `existing` |
| `ascend-audio-scribe` | `DOWNLOAD_FILE_TTL_SECONDS` | `300` | Transcript download time to live. | `existing` |
| `ascend-audio-scribe` | `DOWNLOAD_CLEANUP_INTERVAL_SECONDS` | `75` | Background cleanup sweep interval for transcript downloads. | `existing` |
| `ascend-audio-scribe` | `MAX_UPLOAD_BYTES` | `5368709120` | Max multipart upload size (5 GiB). | `existing` |
| `ascend-audio-scribe` | `MAX_DOWNLOAD_BYTES` | `5368709120` | Max HTTP download size for MCP audio URIs (5 GiB). | `existing` |
| `ascend-audio-scribe` | `MAX_ZIP_UNCOMPRESSED_BYTES` | `5368709120` | Max cumulative uncompressed size for an Audacity zip (5 GiB). | `existing` |
| `ascend-audio-scribe` | `UPLOAD_BUFFER_BYTES` | `65536` | Read/write buffer size for streamed input and output (64 KiB). | `existing` |
| `ascend-audio-scribe` | `LANGUAGE_PATTERN` | `^[a-zA-Z]{2,8}(?:-[a-zA-Z0-9]{1,8})?$` | Allowed shape for language codes. | `existing` |
| `ascend-audio-scribe` | `PROVIDER_PATTERN` | `^[a-z][a-z0-9-]{0,32}$` | Allowed shape for the HF provider name. | `existing` |
| `ascend-audio-scribe` | `MODEL_PATTERN` | `^[A-Za-z0-9._/\-]{1,128}$` | Allowed shape for model identifiers. | `existing` |

---

### container-metrics-exporter

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `container-metrics-exporter` | `DOCKER_SOCKET_GID` | `0` | The group id of `/var/run/docker.sock` on the Docker host that `group_add` gives the exporter user, 0 for Docker Desktop, on Docker Engine for Linux the number `stat -c %g /var/run/docker.sock` prints. See [Reaching the host from a container](DEPLOYMENT.md#reaching-the-host-from-a-container). | `fix-linux-docker-host-access` |
| `container-metrics-exporter` | `DOCKER_SOCKET` | `/var/run/docker.sock` | The Docker Engine socket the exporter reads container stats from. | `existing` |
| `container-metrics-exporter` | `EXPORTER_PORT` | `8080` | The port the exporter serves `/metrics` on. | `existing` |

---

### prometheus

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `prometheus` | `PROMETHEUS_SCRAPE_INTERVAL` | `15s` | Global scrape interval, rendered into `prometheus.yaml` at container start | `add-observability` |
| `prometheus` | `PROMETHEUS_EVALUATION_INTERVAL` | `15s` | Global rule evaluation interval, rendered into `prometheus.yaml` at container start | `add-observability` |
| `prometheus` | `OBSERVABILITY_CLUSTER_LABEL` | `ascend-ai-local` | External `cluster` label, rendered into `prometheus.yaml` at container start | `add-observability` |
| `prometheus` | `PROMETHEUS_QDRANT_TARGET` | `host.docker.internal:6333` | Qdrant scrape target, rendered into `prometheus.yaml` at container start | `add-observability` |
| `prometheus` | `PROMETHEUS_HOST_PORT` | `7077` | Published host port for the Prometheus UI and API | `add-observability` |
| `prometheus` | `PROMETHEUS_RETENTION_TIME` | `72h` | Metrics retention window (`--storage.tsdb.retention.time`) | `add-observability` |

---

### grafana

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `grafana` | `GRAFANA_HOST_PORT` | `7078` | Published host port for the Grafana UI | `add-observability` |
| `grafana` | `GF_SERVER_ROOT_URL` | `http://localhost:7078` | Grafana's own root URL setting | `add-observability` |
| `grafana` | `PROMETHEUS_SCRAPE_INTERVAL` | `15s` | Same setting as Prometheus, read by the `timeInterval` of the `Prometheus` datasource | `add-observability` |
| `grafana` | `GRAFANA_LOKI_MAX_LINES` | `1000` | `maxLines` of the `Loki` datasource | `add-observability` |
| `grafana` | `GRAFANA_DASHBOARDS_UPDATE_INTERVAL_SECONDS` | `30` | `updateIntervalSeconds` of the dashboard file provider | `add-observability` |
| `grafana` | `GF_AUTH_ANONYMOUS_ENABLED` | `true` | Fixed in `compose.yaml`. Enables anonymous Grafana access. | `existing` |
| `grafana` | `GF_AUTH_ANONYMOUS_ORG_ROLE` | `Viewer` | Fixed in `compose.yaml`. The role anonymous Grafana users get. | `existing` |
| `grafana` | `GF_AUTH_DISABLE_LOGIN_FORM` | `false` | Fixed in `compose.yaml`. Keeps the Grafana login form enabled. | `existing` |

---

### loki

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `loki` | `LOKI_RETENTION_PERIOD` | `2160h` | Log retention window | `add-observability` |
| `loki` | `LOKI_RETENTION_DELETE_DELAY` | `2h` | Delay before deleted log data is dropped | `add-observability` |
| `loki` | `LOKI_RESULTS_CACHE_MAX_SIZE_MB` | `100` | Embedded results-cache size for range queries | `add-observability` |

---

### otel-collector

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `otel-collector` | `COLLECTOR_MEMORY_CHECK_INTERVAL` | `1s` | Memory limiter check interval | `add-observability` |
| `otel-collector` | `COLLECTOR_MEMORY_LIMIT_MIB` | `256` | Memory limiter ceiling in MiB | `add-observability` |
| `otel-collector` | `COLLECTOR_MEMORY_SPIKE_LIMIT_MIB` | `64` | Memory limiter spike allowance in MiB | `add-observability` |
| `otel-collector` | `COLLECTOR_BATCH_TIMEOUT` | `1s` | Batch processor send timeout | `add-observability` |
| `otel-collector` | `COLLECTOR_BATCH_SIZE` | `1024` | Batch processor send size | `add-observability` |

---

### tempo

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `tempo` | `TEMPO_BLOCK_RETENTION` | `2160h` | Trace block retention window (backend scheduler and backend worker compaction) | `add-observability` |
| `tempo` | `TEMPO_LOG_LEVEL` | `info` | Tempo server log level | `add-observability` |
| `tempo` | `TEMPO_MAX_BLOCK_DURATION` | `5m` | Longest time span kept in one live-store block | `add-observability` |
| `tempo` | `TEMPO_SEARCH_DURATION_SLO` | `5s` | Search duration objective reported by the frontend | `add-observability` |
| `tempo` | `TEMPO_SEARCH_THROUGHPUT_BYTES_SLO` | `1073741824` | Search throughput objective in bytes | `add-observability` |
| `tempo` | `TEMPO_TRACE_BY_ID_DURATION_SLO` | `5s` | Trace-by-ID duration objective reported by the frontend | `add-observability` |
| `tempo` | `OBSERVABILITY_CLUSTER_LABEL` | `ascend-ai-local` | Same setting as Prometheus, external `cluster` label of generated metrics | `add-observability` |

---

### redis-exporter

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `redis-exporter` | `REDIS_ADDR` | `redis://host.docker.internal:6379` | Redis address the exporter scrapes | `add-observability` |

---

### postgres-exporter

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `postgres-exporter` | `DATA_SOURCE_URI` | `host.docker.internal:5432/ascend_ai?sslmode=disable` | Postgres address the exporter scrapes, credentials come from `DATA_SOURCE_USER` and `DATA_SOURCE_PASS` | `add-observability` |
| `postgres-exporter` | `DATA_SOURCE_USER` | (none, secret in .env) | Postgres user the exporter connects with. | `existing` |
| `postgres-exporter` | `DATA_SOURCE_PASS` | (none, secret in .env) | Postgres password the exporter connects with. | `existing` |

---

### searxng

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `searxng` | `SEARXNG_HOST_PORT` | `9020` | The loopback host port of SearXNG, and a native run of ascend-web-hunter with a changed value also sets `SEARXNG_BASE_URL` to the new address | `fix-linux-docker-host-access` |
| `searxng` | `SEARXNG_SECRET` | (none, secret in .env) | SearxNG's session-signing key. Mandatory: the stack refuses to start without it. | `existing` |

---

### flaresolverr

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `flaresolverr` | `FLARESOLVERR_HOST_PORT` | `8191` | The loopback host port of FlareSolverr, and a native run with a changed value also sets `FLARESOLVERR_URL` | `fix-linux-docker-host-access` |
| `flaresolverr` | `LOG_LEVEL` | `info` | Fixed in `compose.ascend-web-hunter.yaml`. FlareSolverr log level. | `existing` |
| `flaresolverr` | `LOG_HTML` | `false` | Fixed in `compose.ascend-web-hunter.yaml`. HTML log output toggle. | `existing` |
| `flaresolverr` | `CAPTCHA_SOLVER` | `none` | Fixed in `compose.ascend-web-hunter.yaml`. CAPTCHA solver selection. | `existing` |
| `flaresolverr` | `TZ` | `UTC` | Fixed in `compose.ascend-web-hunter.yaml`. Container timezone. | `existing` |

---

### redis

No setting.

---

### ascend-web-hunter

The settings of `ascend-web-hunter` are listed in its own reference, [apps/ascend-web-hunter/docs/configuration.md](../apps/ascend-web-hunter/docs/configuration.md), with the standalone bundle's configuration table in [apps/ascend-web-hunter/deploy-standalone/README.md](../apps/ascend-web-hunter/deploy-standalone/README.md#configuration).

---

### ngrok-ascend-web-hunter

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| `ngrok-ascend-web-hunter` | `NGROK_AUTHTOKEN` | (none, secret in .env) | Ngrok auth token for the NoVNC CAPTCHA-intervention tunnel. Required only when running with the ngrok profile. | `existing` |

---

### Compose project

| Service | Variable | Default | What it does | Added by |
| :------ | :------- | :------ | :----------- | :------- |
| Compose project | `COMPOSE_PROFILES` | (unset, the profiled `redis` service stays off) | Compose profiles to enable. Set to `redis` to start the bundled `redis` service of `compose.ascend-web-hunter.yaml`. | `existing` |

---

### Rule for later changes

Every change that adds or changes a setting adds or changes its row in the same commit as the setting. When the service has its own reference, the row goes there and its description ends with "Added by `<change>`.". Otherwise the row goes in this file with the change's name in Added by. Never in both.
