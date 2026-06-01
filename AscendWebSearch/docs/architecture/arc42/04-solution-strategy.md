# 4. Solution Strategy

---

### Dual REST and MCP surface

AscendWebSearch exposes the same capabilities via two surfaces mounted on a single FastAPI app. The REST routers
(`src/api/rest/rest_endpoints.py`) handle `GET /api/v1/web/search` and `POST /api/v2/web/read`. The MCP server
(`src/api/mcp/mcp_server.py`) exposes `web_search` and `web_read` tools at `POST /mcp`. Both surfaces call the
same `SearxngClient` and `WebReader` singletons. The MCP ASGI sub-app is mounted at `/` last in `src/main.py:61`
so specific REST routes are matched first.

---

### Ordered extraction strategy chain

`WebReader` (`src/reader/web_reader.py`) owns an ordered dict of six strategies. Each strategy implements
`BaseStrategy.extract(url)` and returns extracted plain text or an empty string on failure. The `WebReader.read`
method iterates the dict in order, validates each result with `ContentValidator`, and returns on the first passing
result. This keeps cheap strategies at the front and expensive ones as fallbacks. See
[ADR-001](../decisions/ADR-001-multi-tier-extraction-strategy.md).

Two overrides exist. `heavy_mode=True` skips strategies 1 and 2 and starts from Playwright. A pre-emptive
`ChallengeDetector.is_login_redirect_url` check skips directly to `NoVNCStrategy` if the URL itself signals a
login redirect before any HTTP request is made.

---

### 428 human-intervention protocol

When no automated strategy can extract content, `NoVNCStrategy` raises `HumanInterventionRequiredException`. The
`human_intervention_exception_handler` (`src/api/exception_handlers.py:35`) converts this to HTTP 428 with a
structured body containing `status`, `intervention_type`, and `vnc_url`. The MCP tool docstring instructs the
agent to display `vnc_url` to the user. This makes human CAPTCHAs a first-class protocol outcome rather than an
opaque failure. See [ADR-003](../decisions/ADR-003-novnc-ngrok-captcha-intervention.md).

---

### SSRF guard on user-supplied URLs

Both `POST /api/v2/web/read` and the `web_read` MCP tool call `is_safe_external_url(url)` from
`src/validator/url_validator.py:28` before passing the URL to `WebReader`. This function resolves the hostname
and rejects private, loopback, link-local, multicast, and reserved IP addresses. Pydantic's `HttpUrl` validates
structure but does not resolve DNS; the explicit guard closes the gap.

---

### Blocklist loading in lifespan

`BlocklistLoader` (`src/config/blocklist_loader.py`) fetches the Fanboy Annoyance adblock list at startup inside
the FastAPI lifespan (`src/main.py:33-39`). If loading fails the lifespan raises `RuntimeError` and the service
refuses to start. This is a hard failure by design: the blocklist is used by `PlaywrightStrategy` and
`CrawleeStrategy` to abort ad and tracker requests, and running without it would produce noisier extracted content.
`URLValidator` wraps the loaded `AdblockRules` and is passed to the two browser strategies as a route filter.
