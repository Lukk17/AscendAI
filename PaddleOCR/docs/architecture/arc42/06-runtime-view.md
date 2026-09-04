# 6. Runtime View

---

### Cold start sequence

```mermaid
sequenceDiagram
    participant Docker as Docker / orchestrator
    participant Uvicorn as Uvicorn process
    participant Lifespan as FastAPI lifespan
    participant Pool as OCR worker process
    participant MCPLife as MCP lifespan

    Docker->>Uvicorn: container start
    Uvicorn->>Lifespan: startup
    Lifespan->>Pool: start_worker_pool() — spawn + block on initializer
    Pool->>Pool: warm_up_engine("en") — PaddleOCR(lang="en"), 5–15 s CPU
    Pool->>Pool: observe ENGINE_WARMUP_DURATION_SECONDS (PROMETHEUS_MULTIPROC_DIR)
    Pool-->>Lifespan: initializer done (or BrokenProcessPool, logged, not re-raised)
    Lifespan->>MCPLife: enter mcp_lifespan
    MCPLife->>MCPLife: open aiohttp.ClientSession
    Lifespan->>Lifespan: log_startup_banner()
    Lifespan-->>Uvicorn: yield (service ready)
    Docker->>Uvicorn: GET /ready
    Uvicorn->>Uvicorn: is_engine_warm("en") — read the worker's metric file
    Uvicorn-->>Docker: 200 {"status":"ready","engine_warm":true}
```

The Docker `HEALTHCHECK` targets `/health`, which returns 200 immediately after the process starts. The readiness
probe at `/ready` only returns `ready` once the OCR worker process has recorded a successful warm-up. During the
warm-up window, and if the worker's pool initializer fails outright, `/ready` returns
`{"status":"not-ready","engine_warm":false}` rather than crashing the container. See
[ADR-004](../decisions/ADR-004-liveness-readiness-split.md).

---

### REST happy path

```mermaid
sequenceDiagram
    participant Client
    participant REST as POST /v1/ocr
    participant Pool as OCR worker process
    participant OcrSvc as OcrService

    Client->>REST: multipart upload (file, lang=pl)
    REST->>REST: validate content_type, size
    REST->>Pool: loop.run_in_executor(get_process_pool(), _execute_ocr, bytes, filename, "pl")
    Pool->>OcrSvc: _get_engine("pl") — LRU lookup or new PaddleOCR
    OcrSvc->>OcrSvc: write tempfile, engine.predict, delete tempfile
    OcrSvc-->>Pool: OcrJsonResponse
    Pool-->>REST: OcrJsonResponse
    REST-->>Client: 200 OcrJsonResponse (schema_version="1")
```

---

### MCP happy path via the S3-compatible object store

```mermaid
sequenceDiagram
    participant Agent as AscendAgent
    participant MCP as ocr_process tool
    participant Guard as SSRF guard
    participant ObjectStore as Object store :9070 (host.docker.internal)
    participant Pool as OCR worker process
    participant OcrSvc as OcrService

    Agent->>MCP: tools/call ocr_process(file_uri="http://host.docker.internal:9070/e2e-fixtures/img.png", lang="en")
    MCP->>Guard: _validate_host("host.docker.internal")
    Guard->>Guard: "host.docker.internal" in MCP_ALLOWED_HOSTS → allow
    MCP->>ObjectStore: GET http://host.docker.internal:9070/e2e-fixtures/img.png (allow_redirects=False)
    ObjectStore-->>MCP: 200 image bytes (streamed, size checked)
    MCP->>Pool: loop.run_in_executor(get_process_pool(), run_ocr_in_worker, bytes, "img.png", "en")
    Pool->>OcrSvc: _get_engine("en") — cache hit (warm)
    OcrSvc->>OcrSvc: engine.predict
    OcrSvc-->>Pool: OcrJsonResponse
    Pool-->>MCP: OcrJsonResponse
    MCP-->>Agent: {"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"{...}"}]}}
```

The `host.docker.internal` hostname resolves to a private address inside the docker-compose network. Without
`MCP_ALLOWED_HOSTS=host.docker.internal`, the SSRF guard would reject it. See
[ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md).

---

### Error catalog mapping

| Exception raised | HTTP status (REST) | MCP JSON-RPC | Code string |
| :--- | :--- | :--- | :--- |
| `OcrProcessingError` | 422 | tool error frame | `OCR_FAILED` |
| `FileSizeExceededError` | 400 | tool error frame | `FILE_TOO_LARGE` |
| `UnsupportedFileTypeError` | 400 | tool error frame | `UNSUPPORTED_FILE_TYPE` |
| `UnsafeUriError` | 400 | tool error frame | `UNSAFE_URI` |
| `DownloadFailedError` | 502 | tool error frame | `DOWNLOAD_FAILED` |
| `Exception` (unhandled) | 500 | tool error frame | `INTERNAL_ERROR` |

All handlers are registered in `src/api/exception_handlers.py:38-44`. The `detail` field carries a generic phrase;
the original exception message is logged at WARNING or ERROR but never returned to the client.
