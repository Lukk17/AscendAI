# 6. Runtime View

---

### Cold start sequence

```mermaid
sequenceDiagram
    participant Docker as Docker / orchestrator
    participant Uvicorn as Uvicorn process
    participant Lifespan as FastAPI lifespan
    participant Blocklist as BlocklistLoader
    participant MCP as MCP lifespan

    Docker->>Uvicorn: container start
    Uvicorn->>Lifespan: startup
    Lifespan->>Blocklist: load_rules() — fetch Fanboy Annoyance list
    Blocklist-->>Lifespan: AdblockRules loaded
    Lifespan->>MCP: enter mcp_asgi_app lifespan
    Lifespan->>Lifespan: log_startup_banner()
    Lifespan-->>Uvicorn: yield (service ready)
    Docker->>Uvicorn: GET /health
    Uvicorn-->>Docker: 200 {"status":"ok"}
```

The blocklist load is a hard failure: if `BlocklistLoader.load_rules()` raises, the lifespan raises
`RuntimeError` and Uvicorn exits (`src/main.py:37-39`). There is no `/ready` endpoint separate from `/health`;
liveness is the only probe.

---

### Search happy path

```mermaid
sequenceDiagram
    participant Agent as AscendAgent :9917
    participant MCP as web_search tool
    participant Searxng as SearXNG :9020

    Agent->>MCP: tools/call web_search(query="Python async patterns", limit=5)
    MCP->>MCP: validate query length (≤ 500 chars)
    MCP->>Searxng: GET /search?q=Python+async+patterns&format=html
    Searxng-->>MCP: 200 HTML (article.result elements)
    MCP->>MCP: _parse_html_results(html, limit=5)
    MCP-->>Agent: JSON-RPC result [{title, url, content}, ...]
```

---

### Extraction escalation — BeautifulSoup hit

```mermaid
sequenceDiagram
    participant Agent as AscendAgent :9917
    participant MCP as web_read tool
    participant Guard as is_safe_external_url
    participant WR as WebReader
    participant BS as BeautifulSoupStrategy
    participant CV as ContentValidator
    participant Redis as Redis :6379

    Agent->>MCP: tools/call web_read(url="https://example.com/article")
    MCP->>Guard: is_safe_external_url("https://example.com/article")
    Guard-->>MCP: True
    MCP->>WR: read(url)
    WR->>BS: extract(url)
    BS->>Redis: get_session_data("example.com") → None
    BS->>BS: curl_cffi GET, impersonate=chrome120
    BS-->>WR: plain text
    WR->>CV: validate(text)
    CV-->>WR: True
    WR-->>MCP: {content, status="success", mode="1-beautifulsoup"}
    MCP-->>Agent: JSON-RPC result
```

---

### Extraction escalation — Cloudflare block → FlareSolverr

```mermaid
sequenceDiagram
    participant WR as WebReader
    participant BS as BeautifulSoupStrategy
    participant TR as TrafilaturaStrategy
    participant FS as FlareSolverrStrategy
    participant FlareSolverr as FlareSolverr :8191
    participant Redis as Redis :6379
    participant CV as ContentValidator

    WR->>BS: extract(url)
    BS->>BS: ChallengeDetector.is_blocked → raises ChallengeDetectedException
    BS-->>WR: ChallengeDetectedException propagates
    WR->>WR: short-circuit to 6-novnc
    note over WR: ChallengeDetectedException skips straight to NoVNC,<br/>not to FlareSolverr. FlareSolverr runs only when<br/>BeautifulSoup returns empty without raising.
    WR->>TR: extract(url)
    TR-->>WR: "" (empty — blocked but no exception)
    WR->>FS: extract(url)
    FS->>FlareSolverr: POST {cmd:"request.get", url:...}
    FlareSolverr-->>FS: {status:"ok", solution:{response:html, cookies:[...]}}
    FS->>Redis: save_session_data(url, {cf_clearance:...}, user_agent)
    FS-->>WR: extracted text
    WR->>CV: validate(text) → True
    WR-->>caller: {content, status="success", mode="3-flaresolverr"}
```

---

### NoVNC trigger

```mermaid
sequenceDiagram
    participant WR as WebReader
    participant NoVNC as NoVNCStrategy
    participant Ngrok as Ngrok API
    participant Handler as 428 exception handler
    participant Agent as AscendAgent

    WR->>NoVNC: extract(url)
    NoVNC->>Ngrok: GET PUBLIC_VNC_URL/api/tunnels
    Ngrok-->>NoVNC: {tunnels:[{public_url:"https://abc.ngrok.io"}]}
    NoVNC->>NoVNC: spawn _monitor_for_cookies task (background)
    NoVNC-->>WR: raises HumanInterventionRequiredException(vnc_url)
    WR-->>Handler: exception propagates
    Handler-->>Agent: 428 {status:"human_intervention_required", vnc_url:"https://abc.ngrok.io/vnc.html?autoconnect=true"}
```

---

### Error catalog

| Condition | HTTP status | Response |
| :--- | :--- | :--- |
| `HumanInterventionRequiredException` | 428 | `{status, intervention_type, vnc_url, message}` |
| `httpx.HTTPError` (external service) | 503 | `{detail, error}` |
| All other unhandled exceptions | 500 | `{detail: "Internal Server Error"}` |
| SSRF guard rejects URL | 400 | `{detail: "URL resolves to a private ... address"}` |
| Empty or short query | 400 | `{detail: "query must not be empty"}` |
