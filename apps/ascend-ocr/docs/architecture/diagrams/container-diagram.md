# ascend-ocr - Diagrams

---

### C4 Container diagram

```mermaid
graph TB
    accTitle: ascend-ocr C4 Container Diagram
    accDescr: Shows ascend-ocr's position in the AscendAI platform, its callers, and its downstream dependencies.

    Agent["ascend-agent<br/>(Spring Boot, Java 21)<br/>:9917"]
    ObjectStore["S3-compatible object store<br/>:9070 (host.docker.internal)"]
    Bucket["ocr-results bucket<br/>{job_id}.md"]

    subgraph "ascend-ocr service - :7022"
        REST["REST surface<br/>POST /v1/ocr/jobs<br/>+ status, list, delete"]
        MCP["MCP surface<br/>POST /mcp<br/>(four job tools)"]
        JobSvc["JobService<br/>(one layer, both surfaces)"]
        Runner["JobRunner<br/>(queue, single consumer)"]
        Store["JobStore<br/>(records on disk)"]
        OCRSvc["OcrService<br/>(LRU engine cache)"]
        Guard["SSRF guard<br/>+ file:// jail"]
    end

    subgraph "Sibling MCP services"
        AudioScribe["ascend-audio-scribe<br/>:7017"]
        WeatherMCP["WeatherMCP<br/>:9998"]
        WebHunter["ascend-web-hunter<br/>:7021"]
    end

    Agent -->|"MCP tools/call"| MCP
    Agent -->|"REST submit, then poll"| REST
    REST --> JobSvc
    MCP --> Guard
    Guard -->|"HTTP GET (allowlisted)"| ObjectStore
    Guard --> JobSvc
    JobSvc --> Store
    JobSvc --> Runner
    Runner --> OCRSvc
    Runner -->|"PUT Markdown"| Bucket
    Agent -->|"GET by bucket and key"| Bucket
    Agent -->|"MCP"| AudioScribe
    Agent -->|"MCP"| WeatherMCP
    Agent -->|"MCP"| WebHunter
```

ascend-ocr has no database: job records are files under `OCR_JOBS_DIR` and the recognised text goes to the
`ocr-results` bucket. Model weights are baked into the container image at build time. Two outbound network calls
exist: the MCP tool's URI fetch, gated by the SSRF guard, and the result store's own reads and writes. The object
store is an external prerequisite, not a compose service; locally it is provided by a self-hosted S3-compatible
emulator. See [ADR-008](../decisions/ADR-008-every-request-is-a-job.md) and
[ADR-009](../decisions/ADR-009-results-in-object-storage.md).

---

### MCP runtime happy path

```mermaid
sequenceDiagram
    accTitle: MCP ocr_submit happy path via the S3-compatible object store
    accDescr: Shows the full call chain from ascend-agent through the SSRF guard, the object-store download, the queue, the OCR engine, and the result bucket.

    participant Agent as ascend-agent :9917
    participant MCP as ocr_submit (mcp_server.py)
    participant Guard as _validate_host
    participant ObjectStore as Object store :9070 (host.docker.internal)
    participant Runner as JobRunner
    participant Pool as OCR worker process (ProcessPoolExecutor)
    participant Engine as PaddleOCR engine (OcrService)

    Agent->>MCP: tools/call ocr_submit(file_uri="http://host.docker.internal:9070/bucket/img.png", lang="en")
    MCP->>Guard: hostname="host.docker.internal"
    Guard->>Guard: "host.docker.internal" in MCP_ALLOWED_HOSTS → skip IP check
    MCP->>ObjectStore: GET http://host.docker.internal:9070/bucket/img.png (allow_redirects=False)
    ObjectStore-->>MCP: 200 image bytes (streamed in 64 KB chunks, size checked)
    MCP->>Runner: JobService.submit → record written, job queued
    MCP-->>Agent: JSON-RPC result {job_id, state:"waiting", poll_after_seconds}
    Runner->>Pool: run_in_executor(get_process_pool(), run_ocr_in_worker, bytes, ..., job_id)
    Pool->>Engine: _get_engine("en") → LRU hit (warm since lifespan)
    Engine->>Engine: write tempfile → predict_iter page by page → delete tempfile
    Engine-->>Pool: OcrJsonResponse(schema_version="1", pages=[...])
    Pool-->>Runner: OcrJsonResponse
    Runner->>ObjectStore: PUT ocr-results/{job_id}.md
    Agent->>MCP: tools/call ocr_job_status(job_id) → state:"succeeded", result:{bucket, key, url}
    Agent->>ObjectStore: GET ocr-results/{job_id}.md
```

If `host.docker.internal` is not in `MCP_ALLOWED_HOSTS`, `_validate_host` resolves it to a private RFC1918 address and
raises `UnsafeUriError`, returning `{"code":"UNSAFE_URI","detail":"URI is not permitted"}` to the agent. See
[ADR-001](../decisions/ADR-001-mcp-file-transport-uri-only.md).
