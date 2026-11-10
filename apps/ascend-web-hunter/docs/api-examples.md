# API examples

REST and MCP request shapes against a running ascend-web-hunter instance. Swagger UI at
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

Structured output. Adds `title`, `author`, `date` and `sitename` next to `content`. Defaults to `text`, and is
rejected with HTTP 400 when combined with `include_links`, because the annotated-links response carries the flat
shape plus a link map.

Bash:

```bash
curl -X POST http://localhost:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"https://example.com","output_format":"structured"}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/api/v2/web/read -Method Post -ContentType "application/json" -Body '{"url":"https://example.com","output_format":"structured"}'
```

Starting tier. Names where the escalation chain starts: `1-beautifulsoup`, `2-trafilatura`,
`4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive` or `6-novnc`, the same strings a read
returns in `mode`. Escalation continues through the tiers after it. An unknown value is rejected with HTTP 400
(`validation` problem body).

Bash:

```bash
curl -X POST http://localhost:7021/api/v2/web/read -H "Content-Type: application/json" -d '{"url":"https://example.com","tier":"4-playwright_stealth"}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/api/v2/web/read -Method Post -ContentType "application/json" -Body '{"url":"https://example.com","tier":"4-playwright_stealth"}'
```

An expired session. When a stored login for the target domain and profile no longer validates, the read stops
before any tier runs and answers HTTP 200 with this body. Call `POST /api/v2/web/session/establish` for the same
url and profile, complete the login, then read again.

```json
{
  "url": "https://example.com/feed",
  "content": "",
  "status": "session_expired",
  "profile": "work",
  "message": "Stored session for example.com (profile=work) is no longer valid. Re-establish it with the session establish operation, then read again."
}
```

---

### Session clear (REST)

`POST /api/v2/web/session/clear`. Deletes the stored session for a `url` + optional `profile`, plus any
in-process cached read results for that domain. Idempotent: always returns HTTP 200, whether or not a session
existed. Use this to recover from a poisoned session (stale cookies, a captcha solve that went wrong) without
restarting the service.

Bash:

```bash
curl -X POST http://localhost:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://example.com"}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/api/v2/web/session/clear -Method Post -ContentType "application/json" -Body '{"url":"https://example.com"}'
```

With a named profile (multi-account sites):

Bash:

```bash
curl -X POST http://localhost:7021/api/v2/web/session/clear -H "Content-Type: application/json" -d '{"url":"https://example.com","profile":"work"}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/api/v2/web/session/clear -Method Post -ContentType "application/json" -Body '{"url":"https://example.com","profile":"work"}'
```

Response:

```json
{
  "status": "cleared",
  "url": "https://example.com/",
  "existed": true,
  "cleared_cache_entries": 0
}
```

`existed` is `false` when no session was stored for that `url` + `profile`. The call still returns HTTP 200.

---

### Session status (REST)

`POST /api/v2/web/session/status`. Reports whether a saved login exists for a `url` + optional `profile`. A saved
login counts while it holds a cookie, or a localStorage entry the site set on its own origin (a site that keeps its
login only in browser storage sets no cookie). Analytics and consent keys and other sites' origins do not count.
`last_window` tells how the last intervention window for that site and profile ended, or is `null` when none ended
within `SESSION_AUTH_TTL_SECONDS`. Its `outcome` is one of `resolved`, `already_authenticated`, `timeout`,
`rejected`, `browser_closed`, `cancelled` or `unsafe_uri`.

Bash:

```bash
curl -X POST http://localhost:7021/api/v2/web/session/status -H "Content-Type: application/json" -d '{"url":"https://example.com","profile":"work"}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/api/v2/web/session/status -Method Post -ContentType "application/json" -Body '{"url":"https://example.com","profile":"work"}'
```

Response:

```json
{
  "url": "https://example.com/",
  "status": "active",
  "auth_ttl_remaining_seconds": 86312.4,
  "last_validated": 1762480000.5,
  "profile": "work",
  "last_window": {
    "flow_id": "9f2c41ab77de",
    "intervention_type": "login",
    "outcome": "already_authenticated",
    "finished_at": 1762480012.1
  }
}
```

The `session_status` MCP tool answers the same fields.

---

### Close an intervention window (REST)

`DELETE /api/v2/session/interventions/{flow_id}`. Closes one open NoVNC window, frees its slot at once and saves
nothing from it. The flow ends with the outcome `cancelled`, which `last_window` of the session status then shows.
A window owned by another container is closed by that container within one `NOVNC_COOKIE_SYNC_POLL_SECONDS`, and it
leaves the listing at once. Answers HTTP 204 with no body, or HTTP 404 with code `flow_not_found` when no open window
has that `flow_id`. Take the `flow_id` from `GET /api/v2/session/interventions` or from a 428 answer.

Bash:

```bash
curl -i -X DELETE http://localhost:7021/api/v2/session/interventions/9f2c41ab77de
```

PowerShell:

```powershell
Invoke-WebRequest -Uri http://localhost:7021/api/v2/session/interventions/9f2c41ab77de -Method Delete
```

Unknown or already finished flow:

```json
{
  "type": "https://ascend.ai/errors/flow-not-found",
  "title": "Not Found",
  "status": 404,
  "detail": "No open intervention window has flow_id 9f2c41ab77de.",
  "instance": "/api/v2/session/interventions/9f2c41ab77de",
  "code": "flow_not_found",
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736"
}
```

The `session_cancel_intervention` MCP tool takes `flow_id`, answers `{"status": "cancelled", "flow_id": "..."}`,
and fails with a tool error starting `flow_not_found: ` for an unknown flow.

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

`session_clear`. Same contract as the REST endpoint above: idempotent, always succeeds, `existed` tells the
caller whether a session was actually removed.

Bash:

```bash
curl -X POST http://localhost:7021/mcp -H "Content-Type: application/json" -d '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"session_clear","arguments":{"url":"https://example.com"}},"id":3}'
```

PowerShell:

```powershell
Invoke-RestMethod -Uri http://localhost:7021/mcp -Method Post -ContentType "application/json" -Body '{"jsonrpc":"2.0","method":"tools/call","params":{"name":"session_clear","arguments":{"url":"https://example.com"}},"id":3}'
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

A document address refused for its size (above `DOCUMENT_MAX_BYTES`). No HTML tier and no human tier runs:

```json
{
  "url": "https://example.com/big.pdf",
  "content": "",
  "status": "error",
  "reason": "routing_error",
  "route": "pdf",
  "routing_error": "file_too_large"
}
```

Human intervention required (HTTP 428 problem body on REST, structured result on MCP):

```json
{
  "type": "https://ascend.ai/errors/human-intervention-required",
  "title": "Precondition Required",
  "status": 428,
  "code": "human_intervention_required",
  "detail": "Manual Captcha resolution required. Please visit: https://abc123.ngrok.app/vnc.html?autoconnect=true&v=0.0.15",
  "instance": "/api/v2/web/read",
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
  "intervention_type": "captcha",
  "vnc_url": "https://abc123.ngrok.app/vnc.html?autoconnect=true&v=0.0.15"
}
```

Agents should surface the `vnc_url` to the user, wait for them to confirm the challenge is solved, then re-call
`web_read` with the same URL. The cached Redis session lets the second call succeed without re-triggering
NoVNC.
