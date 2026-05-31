# PaddleOCR Configuration

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
| OCR_REQUEST_TIMEOUT               | `120.0`                                       | Seconds. Applied via `asyncio.wait_for` around every engine call.                        |

---

### OCR engine

| Variable                          | Default                                       | Purpose                                                                                  |
| :-------------------------------- | :-------------------------------------------- | :--------------------------------------------------------------------------------------- |
| DEFAULT_LANGUAGE                  | `en`                                          | Engine warmed during lifespan. Pattern `[a-z]{2,5}`.                                     |
| SUPPORTED_LANGUAGES               | `en,pl,de,fr,es,it,pt,nl,ru,ch,ja,ko`         | Allowlist enforced by `OcrService._get_engine`.                                          |
| ENGINE_CACHE_MAX_SIZE             | `8`                                           | LRU eviction kicks in past this language count.                                          |
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
MCP_FILE_URI_ROOT=/tmp/paddle-ocr-uploads
MCP_ALLOWED_HOSTS=host.docker.internal,localhost,127.0.0.1
```

The repo's [.gitignore](../.gitignore) excludes `.env`. Commit a sanitised `.env.example` if a profile needs sharing.
