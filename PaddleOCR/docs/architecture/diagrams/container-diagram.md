# PaddleOCR — Diagrams

---

### C4 Container diagram

```mermaid
graph TB
    accTitle: PaddleOCR C4 Container Diagram
    accDescr: Shows PaddleOCR's position in the AscendAI platform, its callers, and its downstream dependencies.

    Agent["AscendAgent<br/>(Spring Boot, Java 21)<br/>:9917"]
    MinIO["MinIO<br/>(S3-compatible object store)<br/>:9000 internal / :9070 host"]

    subgraph "PaddleOCR service — :7022"
        REST["REST surface<br/>POST /v1/ocr<br/>(multipart upload)"]
        MCP["MCP surface<br/>POST /mcp<br/>(ocr_process tool)"]
        OCRSvc["OcrService<br/>(LRU engine cache)"]
        Guard["SSRF guard<br/>+ file:// jail"]
    end

    subgraph "Sibling MCP services"
        AudioScribe["AudioScribe<br/>:7017"]
        WeatherMCP["WeatherMCP<br/>:9998"]
        WebSearch["AscendWebSearch<br/>:7021"]
    end

    Agent -->|"MCP tools/call"| MCP
    Agent -->|"REST multipart"| REST
    REST --> OCRSvc
    MCP --> Guard
    Guard -->|"HTTP GET (allowlisted)"| MinIO
    Guard --> OCRSvc
    Agent -->|"MCP"| AudioScribe
    Agent -->|"MCP"| WeatherMCP
    Agent -->|"MCP"| WebSearch
```

PaddleOCR has no database. Model weights are baked into the container image at build time (`Dockerfile:23`). The only
outbound network call is the MCP tool's URI fetch, which is gated by the SSRF guard.

---

### MCP runtime happy path

```mermaid
sequenceDiagram
    accTitle: MCP ocr_process happy path via MinIO
    accDescr: Shows the full call chain from AscendAgent through the SSRF guard, MinIO download, and OCR engine.

    participant Agent as AscendAgent :9917
    participant MCP as ocr_process (mcp_server.py)
    participant Guard as _validate_host
    participant MinIO as MinIO :9000
    participant Thread as Thread pool (asyncio.to_thread)
    participant Engine as PaddleOCR engine (OcrService)

    Agent->>MCP: tools/call ocr_process(file_uri="http://minio:9000/bucket/img.png", lang="en")
    MCP->>Guard: hostname="minio"
    Guard->>Guard: "minio" in MCP_ALLOWED_HOSTS → skip IP check
    MCP->>MinIO: GET http://minio:9000/bucket/img.png (allow_redirects=False)
    MinIO-->>MCP: 200 image bytes (streamed in 64 KB chunks, size checked)
    MCP->>Thread: asyncio.to_thread(ocr_service.process_file, bytes, "img.png", "en")
    Thread->>Engine: _get_engine("en") → LRU hit (warm since lifespan)
    Engine->>Engine: write tempfile → engine.predict → delete tempfile
    Engine-->>Thread: OcrJsonResponse(schema_version="1", pages=[...])
    Thread-->>MCP: OcrJsonResponse
    MCP-->>Agent: JSON-RPC result {content:[{type:"text",text:"{...}"}]}
```

If `minio` is not in `MCP_ALLOWED_HOSTS`, `_validate_host` resolves `minio` to a private RFC1918 address and raises
`UnsafeUriError`, returning `{"code":"UNSAFE_URI","detail":"URI is not permitted"}` to the agent. See
[ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md).
