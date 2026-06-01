# API examples

REST and MCP request shapes against a running AscendWebSearch instance. Swagger UI at
[http://localhost:7021/docs](http://localhost:7021/docs) is the authoritative reference; this doc is the
copy-paste cheat sheet.

Each interactive command is shown twice when bash and PowerShell differ. When the underlying tool is the
same (`docker`, `pip`, `playwright`, `python`), one block covers both shells.

---

### Health and readiness

Liveness.

Bash:

```bash
curl http://localhost:7021/health
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/health
```

Readiness (dependency probes).

Bash:

```bash
curl http://localhost:7021/ready
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/ready
```

Prometheus metrics.

Bash:

```bash
curl http://localhost:7021/metrics
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/metrics
```

---

### Web search (REST)

`GET /api/v1/web/search`.

Bash:

```bash
curl "http://localhost:7021/api/v1/web/search?query=AscendAI&limit=3"
```

PowerShell:

```powershell
Invoke-RestMethod -Uri "http://localhost:7021/api/v1/web/search?query=AscendAI&limit=3"
```

Response is a JSON array of `{title, url, content}` objects.

---

### Web read (REST)

`POST /api/v2/web/read`. The v2 POST endpoint protects complex URL parameters (`&`, `?continue=`, embedded
query strings) from being mangled by the HTTP router.

Plain extraction.

Bash:

```bash
curl -X POST http://localhost:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"https://example.com"}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/api/v2/web/read -Method Post -ContentType "application/json" -Body '{"url":"https://example.com"}'
```

Extraction with link annotation (returns `content` with inline `[N]` markers plus a numbered link map).

Bash:

```bash
curl -X POST http://localhost:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"https://example.com","include_links":true,"link_filter":"/job-offer/"}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/api/v2/web/read -Method Post -ContentType "application/json" -Body '{"url":"https://example.com","include_links":true,"link_filter":"/job-offer/"}'
```

Heavy mode (skip cheap tiers, jump straight to Playwright + Crawlee + NoVNC).

Bash:

```bash
curl -X POST http://localhost:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"https://example.com","heavy_mode":true}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/api/v2/web/read -Method Post -ContentType "application/json" -Body '{"url":"https://example.com","heavy_mode":true}'
```

---

### MCP tools over HTTP

The MCP server accepts JSON-RPC `tools/call` requests on `/mcp`.

`web_search`.

Bash:

```bash
curl -X POST http://localhost:7021/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"web_search","arguments":{"query":"AscendAI","limit":1}},"id":1}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/mcp -Method Post -ContentType "application/json" -Body '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"web_search","arguments":{"query":"AscendAI","limit":1}},"id":1}'
```

`web_read`.

Bash:

```bash
curl -X POST http://localhost:7021/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"web_read","arguments":{"url":"https://example.com"}},"id":2}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/mcp -Method Post -ContentType "application/json" -Body '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"web_read","arguments":{"url":"https://example.com"}},"id":2}'
```

---

### Response shapes

Successful extraction:

```json
{
  "url": "https://example.com",
  "content": "Page text...",
  "status": "success",
  "mode": "1-beautifulsoup"
}
```

All tiers failed:

```json
{
  "url": "https://example.com",
  "content": "",
  "status": "error",
  "reason": "all_tiers_failed",
  "error": "All extraction methods failed for https://example.com"
}
```

Wall-clock budget hit before any tier resolved:

```json
{
  "reason": "budget_exhausted"
}
```

Human intervention required (HTTP 428 on REST, structured result on MCP):

```json
{
  "status": "human_intervention_required",
  "intervention_type": "captcha",
  "vnc_url": "https://abc123.ngrok.app/vnc.html?autoconnect=true",
  "message": "Manual Captcha resolution required. Please visit: https://abc123.ngrok.app/vnc.html?autoconnect=true"
}
```

Agents should surface the `vnc_url` to the user, wait for them to confirm the challenge is solved, then re-call
`web_read` with the same URL. The cached Redis session lets the second call succeed without re-triggering
NoVNC.
