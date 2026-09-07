# 3. Context and Scope

---

### System context

```mermaid
graph TB
    Agent["AscendAgent<br/>(Spring Boot)<br/>:9917"]
    PaddleOCR["ascend-ocr<br/>(FastMCP, Python)<br/>:7022"]
    ObjectStore["S3-compatible object store<br/>:9070 (host.docker.internal)"]
    WebHunter["ascend-web-hunter<br/>(sibling MCP)<br/>:7021"]

    Agent -->|"MCP tools/call<br/>ocr_process(file_uri, lang)"| PaddleOCR
    Agent -->|"REST multipart<br/>POST /v1/ocr"| PaddleOCR
    PaddleOCR -->|"HTTP GET<br/>file_uri fetch"| ObjectStore
```

---

### External interfaces

| System | Direction | Protocol | Notes |
| :--- | :--- | :--- | :--- |
| AscendAgent | Inbound | MCP (Streamable HTTP) via `POST /mcp` | Primary consumer. Sends `tools/call name="ocr_process"` with a `file_uri` argument pointing to the S3-compatible object store or another HTTP source. |
| AscendAgent | Inbound | HTTP multipart `POST /v1/ocr` | Secondary path for direct upload (e.g. developer tooling, curl, Bruno collection). |
| S3-compatible object store | Outbound | HTTP GET | Used by the MCP path. The `file_uri` in the `ocr_process` call is typically `http://host.docker.internal:9070/<bucket>/<key>`, an external prerequisite reached over the host-published endpoint (locally provided by a self-hosted emulator). The SSRF guard must allowlist `host.docker.internal` via `MCP_ALLOWED_HOSTS`. |
| ascend-web-hunter | None | N/A | Sibling service in the same docker-compose network. No direct dependency. Mentioned as a reference for how the monorepo's Python MCP pattern is applied across services. |

---

### What ascend-ocr does NOT do

- It does not store results. Every response is ephemeral; there is no database.
- It does not call any LLM or AI provider. OCR is fully local, CPU-bound.
- It does not push events. The response is synchronous JSON-RPC or HTTP JSON.
- It does not manage users. There is no authentication at the service boundary; the docker-compose network is the
  trust boundary.
- It does not handle audio, web search, or any capability other than OCR.
