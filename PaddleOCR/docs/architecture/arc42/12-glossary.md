# 12. Glossary

| Term | Definition |
| :--- | :--- |
| **MCP** | Model Context Protocol. An open standard for LLM tool integration. PaddleOCR uses FastMCP to expose the `ocr_process` tool via Streamable HTTP at `POST /mcp`. |
| **FastMCP** | Python library for building MCP servers on top of FastAPI / Starlette. PaddleOCR uses version 3.3.1 (`pyproject.toml`). |
| **ocr_process** | The single MCP tool exposed by PaddleOCR. Accepts `file_uri` (URI string) and `lang` (language code). Returns a serialised `OcrJsonResponse`. |
| **OcrJsonResponse** | The unified response model for both REST and MCP surfaces. Carries `schema_version`, `filename`, `language`, `pages` (list of `OcrPageResult`), and `processing_time_seconds`. Defined in `src/model/ocr_models.py`. |
| **schema_version** | A `Literal["1"]` field on `OcrJsonResponse`. Bumped (with a new tool name or URL prefix) when the response shape changes in a breaking way. See [ADR-003](../decisions/ADR-003-versioning-strategy.md). |
| **SSRF** | Server-Side Request Forgery. An attack where a server is tricked into fetching a URI that reaches internal infrastructure. PaddleOCR's guard is in `src/api/mcp/mcp_server.py:_validate_host`. |
| **SSRF guard** | Two-layer defence: an explicit allowlist (`MCP_ALLOWED_HOSTS`) for trusted internal hostnames, plus a DNS-resolution check that rejects private, loopback, link-local, multicast, and reserved IP addresses. See [ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md). |
| **file:// jail** | When `MCP_FILE_URI_ROOT` is set, `file://` URIs are allowed but constrained to paths inside that directory via `os.path.realpath` comparison. Any path that resolves outside the root is rejected with `UnsafeUriError`. |
| **LRU engine cache** | The `OrderedDict[str, PaddleOCR]` in `OcrService`. Promotes accessed engines to the tail; evicts from the head when size exceeds `ENGINE_CACHE_MAX_SIZE`. |
| **Lifespan** | The FastAPI/Starlette async context manager that runs at startup and shutdown. PaddleOCR uses it for engine warm-up (`warm_up_engine`) and for opening/closing the MCP `aiohttp.ClientSession`. |
| **Liveness probe** | `GET /health`. Returns `{"status":"ok","version":"..."}` as long as the process is alive. Docker's `HEALTHCHECK` should target this. |
| **Readiness probe** | `GET /ready`. Returns `{"status":"ready"|"not-ready","engine_warm":bool}`. Returns `ready` only after the lifespan warm-up completes. Load balancers and Kubernetes `readinessProbe` should target this. |
| **PaddleOCR** | The Python OCR library (`paddleocr==3.6.0`) wrapping PaddlePaddle inference. Instantiated per language; the first call per instance loads model weights. |
| **PaddlePaddle** | The underlying deep learning framework (`paddlepaddle==3.3.1`) that PaddleOCR runs on. CPU-only in the default compose stack; CUDA builds require a separate base image. |
| **MinIO** | S3-compatible object storage used in the monorepo stack. PaddleOCR's MCP tool fetches files from MinIO when `file_uri` is an `http://minio:9000/...` URL. Requires `MCP_ALLOWED_HOSTS=minio` to bypass the SSRF IP block. |
| **Error catalog** | The six stable error code strings (`OCR_FAILED`, `FILE_TOO_LARGE`, `UNSUPPORTED_FILE_TYPE`, `UNSAFE_URI`, `DOWNLOAD_FAILED`, `INTERNAL_ERROR`) shared by REST and MCP surfaces. Defined in `src/api/exception_handlers.py`. See [ADR-002](../decisions/ADR-002-mcp-error-catalog.md). |
| **asyncio.to_thread** | Python stdlib function that runs a synchronous callable in a thread pool and awaits the result. Used to offload CPU-bound `PaddleOCR.predict()` calls without blocking the event loop. |
| **aiofiles** | Async file I/O library used by `_read_jailed_file` in `mcp_server.py` to read `file://` sources without blocking. |
| **aiohttp** | Async HTTP client library. A single `ClientSession` is created in `mcp_lifespan` and reused for all MCP HTTP downloads. |
