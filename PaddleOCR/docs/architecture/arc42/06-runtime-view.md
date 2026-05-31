# 6. Runtime View

---

### Cold start sequence

```mermaid
sequenceDiagram
    participant Docker as Docker / orchestrator
    participant Uvicorn as Uvicorn process
    participant Lifespan as FastAPI lifespan
    participant OcrSvc as OcrService
    participant MCPLife as MCP lifespan

    Docker->>Uvicorn: container start
    Uvicorn->>Lifespan: startup
    Lifespan->>OcrSvc: warm_up_engine("en")
    OcrSvc->>OcrSvc: PaddleOCR(lang="en") — 5–15 s CPU
    OcrSvc-->>Lifespan: engine cached
    Lifespan->>MCPLife: enter mcp_lifespan
    MCPLife->>MCPLife: open aiohttp.ClientSession
    Lifespan->>Lifespan: log_startup_banner()
    Lifespan-->>Uvicorn: yield (service ready)
    Docker->>Uvicorn: GET /ready
    Uvicorn-->>Docker: 200 {"status":"ready","engine_warm":true}
```

The Docker `HEALTHCHECK` targets `/health`, which returns 200 immediately after the process starts. The readiness
probe at `/ready` only returns `ready` after `warm_up_engine` completes. During the warm-up window, `/ready` returns
`{"status":"not-ready","engine_warm":false}`.

---

### REST happy path

```mermaid
sequenceDiagram
    participant Client
    participant REST as POST /v1/ocr
    participant OcrSvc as OcrService
    participant Thread as Thread pool

    Client->>REST: multipart upload (file, lang=pl)
    REST->>REST: validate content_type, size
    REST->>Thread: asyncio.to_thread(ocr_service.process_file, bytes, filename, "pl")
    Thread->>OcrSvc: _get_engine("pl") — LRU lookup or new PaddleOCR
    OcrSvc->>OcrSvc: write tempfile, engine.predict, delete tempfile
    OcrSvc-->>Thread: OcrJsonResponse
    Thread-->>REST: OcrJsonResponse
    REST-->>Client: 200 OcrJsonResponse (schema_version="1")
```

---

### MCP happy path via MinIO

```mermaid
sequenceDiagram
    participant Agent as AscendAgent
    participant MCP as ocr_process tool
    participant Guard as SSRF guard
    participant MinIO as MinIO :9000
    participant OcrSvc as OcrService
    participant Thread as Thread pool

    Agent->>MCP: tools/call ocr_process(file_uri="http://minio:9000/e2e-fixtures/img.png", lang="en")
    MCP->>Guard: _validate_host("minio")
    Guard->>Guard: "minio" in MCP_ALLOWED_HOSTS → allow
    MCP->>MinIO: GET http://minio:9000/e2e-fixtures/img.png (allow_redirects=False)
    MinIO-->>MCP: 200 image bytes (streamed, size checked)
    MCP->>Thread: asyncio.to_thread(ocr_service.process_file, bytes, "img.png", "en")
    Thread->>OcrSvc: _get_engine("en") — cache hit (warm)
    OcrSvc->>OcrSvc: engine.predict
    OcrSvc-->>Thread: OcrJsonResponse
    Thread-->>MCP: OcrJsonResponse
    MCP-->>Agent: {"jsonrpc":"2.0","result":{"content":[{"type":"text","text":"{...}"}]}}
```

The `minio` hostname resolves to a private RFC1918 address inside the docker-compose network. Without
`MCP_ALLOWED_HOSTS=minio`, the SSRF guard would reject it. See
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
