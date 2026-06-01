# AscendWebSearch — Diagrams

---

### C4 Container diagram

```mermaid
graph TB
    accTitle: AscendWebSearch C4 Container Diagram
    accDescr: Shows AscendWebSearch's position in the AscendAI platform, its callers, and its downstream service dependencies.

    Agent["AscendAgent<br/>(Spring Boot, Java 21)<br/>:9917"]
    Human["Human operator<br/>(browser / VNC client)"]

    subgraph "AscendWebSearch service — :7021"
        REST["REST surface<br/>GET /api/v1/web/search<br/>POST /api/v2/web/read"]
        MCP["MCP surface<br/>POST /mcp<br/>(web_search, web_read tools)"]
        WR["WebReader<br/>(strategy orchestrator)"]
        Guard["SSRF guard<br/>(is_safe_external_url)"]
        Validator["ContentValidator"]
        subgraph "Strategy chain"
            S1["1-beautifulsoup<br/>(curl_cffi + BS4)"]
            S2["2-trafilatura<br/>(curl_cffi + trafilatura)"]
            S3["3-flaresolverr<br/>(FlareSolverr proxy)"]
            S4["4-playwright_stealth<br/>(Chromium + stealth)"]
            S5["5-crawlee_adaptive<br/>(AdaptivePlaywrightCrawler)"]
            S6["6-novnc<br/>(human intervention)"]
        end
        CookieMgr["CookieManager<br/>(domain session store)"]
        SearxClient["SearxngClient"]
    end

    subgraph "External services (ascend-scrapper network)"
        SearXNG["SearXNG<br/>(:9020)"]
        FlareSolverr["FlareSolverr<br/>(:8191)"]
        Ngrok["Ngrok tunnel"]
    end

    Redis["Redis<br/>(:6379)"]
    TargetSite["Target websites<br/>(public internet)"]

    Agent -->|"MCP tools/call"| MCP
    Agent -->|"GET/POST REST"| REST
    REST --> Guard
    MCP --> Guard
    Guard --> WR
    WR --> S1
    WR --> S2
    WR --> S3
    WR --> S4
    WR --> S5
    WR --> S6
    WR --> Validator
    REST --> SearxClient
    MCP --> SearxClient
    SearxClient -->|"GET /search?format=html"| SearXNG
    S3 -->|"POST {cmd:request.get}"| FlareSolverr
    S1 -->|"HTTP GET"| TargetSite
    S2 -->|"HTTP GET"| TargetSite
    S4 -->|"Chromium navigate"| TargetSite
    S5 -->|"Chromium navigate"| TargetSite
    S1 --> CookieMgr
    S2 --> CookieMgr
    S3 --> CookieMgr
    S6 --> CookieMgr
    CookieMgr -->|"SETEX / GET"| Redis
    S6 -->|"428 + VNC URL"| Human
    Ngrok -->|"tunnel"| Human
```

AscendWebSearch has no database. The only persistent state is session cookies in Redis, which expire after
2 hours. See [ADR-002](../decisions/ADR-002-cloudflare-cookie-persistence-redis.md).

---

### Extraction strategy escalation

This sequence shows the happy path where strategy 1 succeeds, and a comparison path where strategy 1 detects a
Cloudflare block and the chain escalates all the way to NoVNC.

```mermaid
sequenceDiagram
    accTitle: AscendWebSearch extraction strategy escalation
    accDescr: Shows strategy escalation from the fast BeautifulSoup path through to the human NoVNC intervention.

    participant Agent as AscendAgent :9917
    participant MCP as web_read (mcp_server.py)
    participant Guard as is_safe_external_url
    participant WR as WebReader
    participant S1 as 1-beautifulsoup
    participant S2 as 2-trafilatura
    participant S3 as 3-flaresolverr
    participant S4 as 4-playwright_stealth
    participant S5 as 5-crawlee_adaptive
    participant S6 as 6-novnc
    participant CV as ContentValidator
    participant Redis as Redis :6379
    participant Ngrok as Ngrok API

    Agent->>MCP: tools/call web_read(url="https://target.com/article")
    MCP->>Guard: is_safe_external_url("https://target.com/article")
    Guard-->>MCP: True (public IP)
    MCP->>WR: read(url)

    note over WR,CV: Happy path — strategy 1 succeeds

    WR->>S1: extract(url)
    S1->>Redis: get_session_data("target.com") → None
    S1->>S1: curl_cffi GET, impersonate=chrome120
    S1-->>WR: plain text (no challenge detected)
    WR->>CV: validate(text) → True
    WR-->>MCP: {content, status="success", mode="1-beautifulsoup"}
    MCP-->>Agent: JSON-RPC result

    note over WR,CV: Escalation path — Cloudflare block detected at strategy 1

    WR->>S1: extract(url) — second request to a CF-protected page
    S1->>S1: ChallengeDetector.is_blocked(200, html) → True
    S1-->>WR: raises ChallengeDetectedException
    WR->>S6: short-circuit to NoVNC (ChallengeDetectedException)
    S6->>Ngrok: GET PUBLIC_VNC_URL/api/tunnels
    Ngrok-->>S6: {tunnels:[{public_url:"https://abc.ngrok.io"}]}
    S6->>S6: spawn _monitor_for_cookies task (background)
    S6-->>WR: raises HumanInterventionRequiredException(vnc_url)
    WR-->>Agent: 428 {status:"human_intervention_required", vnc_url:"https://abc.ngrok.io/vnc.html?autoconnect=true"}
```

When strategy 1 or 2 return empty string without raising (not a detected block, just no content), the chain
continues to strategy 3 (FlareSolverr) and then strategies 4, 5, 6. `ChallengeDetectedException` is a hard
short-circuit that skips directly to strategy 6; ordinary strategy failures (empty string returned) proceed
sequentially. See [ADR-001](../decisions/ADR-001-multi-tier-extraction-strategy.md).
