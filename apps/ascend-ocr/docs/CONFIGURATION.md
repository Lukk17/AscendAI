# ascend-ocr Configuration

*Every runtime setting binds from the environment (or a local `.env` file) into the typed `Settings` class at
[../src/config/config.py](../src/config/config.py). Defaults are safe for a single-instance local run.*

---

### Service

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| API_HOST                          | `0.0.0.0`                                     | Uvicorn bind address.                                                                    |
| API_PORT                          | `7022`                                        | Uvicorn port.                                                                            |
| LOG_LEVEL                         | `INFO`                                        | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`.                                         |
| LOG_FORMAT                        | `json`                                        | `json` for production log sinks, `color` for local terminal output.                      |
| OCR_REQUEST_TIMEOUT               | `120.0`                                       | Seconds. Absolute ceiling on one request; the effective budget is `min(pages * OCR_PAGE_TIMEOUT_SECONDS, OCR_REQUEST_TIMEOUT)`. |

---

### Request budgets, memory bounds, and worker recovery

See [ADR-005](architecture/decisions/ADR-005-fixed-pdf-render-resolution.md) and
[ADR-006](architecture/decisions/ADR-006-detector-input-bound.md) for the full derivation. Two values, `OCR_MAX_INFERENCE_PIXELS`
and `OCR_DETECTOR_MAX_SIDE`, are one decision expressed as two settings — deploy them together.

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| OCR_WORKER_COUNT                  | `1`                                           | Inference worker processes, and admission-gate permits — both read from this one setting. One call's peak is already most of the container's memory ceiling, so this is a memory constraint, not a throughput knob: `service_peak_MiB ~= per_call_peak_MiB * OCR_WORKER_COUNT`. |
| OCR_PAGE_TIMEOUT_SECONDS          | `120.0`                                       | Per-page allowance the worker checks between pages (`predict_iter()`, not `predict()`). The docker-compose service sets `150`, beside `OCR_REQUEST_TIMEOUT=300`. |
| OCR_DISPATCH_MARGIN_SECONDS       | `5.0`                                         | Headroom the worker's own budget subtracts, so it gives up slightly before the parent.   |
| OCR_MAX_INFERENCE_PIXELS          | `2500000`                                     | Pixel ceiling on one inference, checked from the file header before decode. Refused with `FILE_TOO_LARGE`, naming the measured count and the ceiling. |
| OCR_DETECTOR_MAX_SIDE             | `1536`                                        | Bounds text detection's longest input side (`text_det_limit_type="max"`), independent of the page's own resolution. Set to an empty value to restore the library's unbounded default. The owner's measured choice against 960 and 1280 — see ADR-006. |
| OCR_POOL_REBUILD_MAX_CONSECUTIVE  | `3`                                           | Consecutive failed pool rebuilds before the service stops trying and stays not-ready. Resets on the first request that completes. |
| OCR_SCRATCH_DIR                   | `<system temp>/ascend-ocr-scratch`            | Directory for the worker's temporary upload copy. Swept of anything older than `OCR_REQUEST_TIMEOUT + OCR_DISPATCH_MARGIN_SECONDS` by every fresh worker and at service startup. |

Two further values are derived properties, not settings — they recompute from the inputs above and cannot be set
from the environment: `OCR_MAX_PAGES = floor(OCR_REQUEST_TIMEOUT / OCR_PAGE_TIMEOUT_SECONDS)` refuses a document with
more pages before any inference starts, and `OCR_RECLAMATION_GRACE_SECONDS = OCR_PAGE_TIMEOUT_SECONDS +
OCR_DISPATCH_MARGIN_SECONDS` is how long a worker may run past its own expired budget before it is replaced.

---

### OCR engine

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| DEFAULT_LANGUAGE                  | `en`                                          | Engine warmed during lifespan. Pattern `[a-z]{2,6}`.                                     |
| SUPPORTED_LANGUAGES               | `en,pl,de,fr,es,it,pt,nl,ru,ch,japan,korean`  | Allowlist enforced by `OcrService._get_engine`.                                          |
| ENGINE_CACHE_MAX_SIZE             | `2`                                           | LRU eviction kicks in past this language count. Matches the two languages (`en`, `pl`) the Dockerfile pre-caches; raising it keeps more languages resident but is not counted for in the container's memory ceiling (see 07-deployment-view.md). |
| MAX_FILE_SIZE_MB                  | `50`                                          | Caps REST upload and MCP download.                                                       |

---

### MCP transport

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| MCP_FILE_URI_ROOT                 | unset                                         | When set, `file://` is enabled and jailed to this directory via `realpath`. See [ADR-001](architecture/decisions/ADR-001-mcp-file-transport-uri-only.md). |
| MCP_ALLOWED_HOSTS                 | empty                                         | Hostnames that bypass the SSRF private-IP guard. The docker-compose default is `host.docker.internal,localhost,127.0.0.1`. |
| MCP_DOWNLOAD_TIMEOUT_SECONDS      | `30.0`                                        | Total aiohttp timeout for the URI fetch.                                                 |

---

### Rate limiting

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| RATE_LIMIT_DEFAULT                | `60/minute`                                   | slowapi default applied to every endpoint.                                               |
| RATE_LIMIT_OCR                    | `20/minute`                                   | Stricter cap on `POST /v1/ocr`.                                                          |

---

### OpenTelemetry

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| OTEL_ENABLED                      | `false`                                       | When `true`, FastAPI + aiohttp auto-instrumentation plus three manual spans are wired up. |
| OTEL_EXPORTER_OTLP_ENDPOINT       | `http://otel-collector:4317`                  | gRPC OTLP collector address.                                                             |

---

### Local override file

The `Settings` class reads a `.env` file in the project root if present. Example for a local run that enables
`file://` access and points at a non-default upload directory:

```dotenv
LOG_FORMAT=color
LOG_LEVEL=DEBUG
MCP_FILE_URI_ROOT=/tmp/ascend-ocr-uploads
MCP_ALLOWED_HOSTS=host.docker.internal,localhost,127.0.0.1
```

The repo's [.gitignore](../../../.gitignore) excludes `.env`. Commit a sanitised `.env.example` if a profile needs sharing.
