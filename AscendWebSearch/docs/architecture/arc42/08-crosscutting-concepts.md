# 8. Crosscutting Concepts

---

### Logging

Logging is configured in `src/config/logging_config.py`. The module uses `colorlog` for development-friendly
coloured output and integrates with the Uvicorn logger. All strategy modules log at `INFO` when a strategy
starts (`--- Strategy N STARTED ---`) and at `WARNING` when a strategy fails or detects a challenge. The startup
banner (`src/config/startup_banner.py`) emits key config values at startup so operators can verify the runtime
configuration from container logs without inspecting env vars separately.

---

### SSRF guard

Two distinct SSRF surfaces exist and both are guarded.

`is_safe_external_url` (`src/validator/url_validator.py:28`) is called by both the REST `POST /api/v2/web/read`
endpoint and the `web_read` MCP tool before any URL is passed to `WebReader`. It resolves the hostname with
`socket.getaddrinfo` and rejects loopback, private, link-local, multicast, reserved, and unspecified addresses.
Non-HTTP/HTTPS schemes are also rejected.

The SearXNG client issues its own outbound requests, but the query is operator-configured text from the caller.
SearXNG runs inside the trusted docker-compose network; its responses are parsed, not fetched by the service.

---

### Content validation

`ContentValidator` (`src/validator/content_validator.py`) applies four checks in order:

1. Empty-string guard.
2. Error-keyword scan (list in `settings.ERROR_KEYWORDS`: "Access Denied", "403 Forbidden", "Captcha", etc.).
3. Minimum word count (`VALIDATION_MIN_WORDS`, default 10).
4. Quality metrics: Flesch reading ease (`MIN_FLESCH_SCORE`, default 20.0) and type-token ratio
   (`MIN_TTR`, default 0.1) via `textstat`. Errors in `textstat` are caught and logged; the content is accepted
   if the metrics calculation fails.

A strategy result is only accepted by `WebReader` if `ContentValidator.validate` returns `True`.

---

### Adblock blocklist filtering

`BlocklistLoader` fetches the Fanboy Annoyance list at startup and returns an `AdblockRules` instance. This is
passed to `PlaywrightStrategy` and `CrawleeStrategy` as a `URLValidator` whose `route_handler` aborts any request
matching the blocklist rules. This reduces noise in extracted content by blocking ads, trackers, and annoyance
scripts before they execute in the browser.

---

### Challenge detection

`ChallengeDetector` (`src/reader/cloudflare/challenge_detector.py`) loads a `challenge_dictionary.json`
sidecar that contains WAF script signatures, strict HTML phrases, and login title patterns. Detection checks:

- HTTP status codes 403, 429, 503 with empty body.
- Presence of known WAF script signatures or strict phrases in short HTML responses (< 50 KB).
- `Ray ID: \w+` regex match.
- `cf-turnstile` or `cf_clearance` string presence.
- Login title patterns matched against `<title>` content.
- URL-level login redirect indicators (`?login`, `continue=`, `signin`).

`ChallengeDetectedException` short-circuits the strategy loop to `NoVNCStrategy`. This avoids waiting for all
remaining strategies to time out when a WAF block is conclusively detected.

---

### User-agent rotation

`WebReader._load_user_agents` reads a JSON array from `src/assets/user_agents.json` at construction time.
`_get_random_user_agent` selects a random entry per request. Strategies that use direct HTTP clients
(`BeautifulSoupStrategy`, `TrafilaturaStrategy`) inject this random User-Agent unless a saved session for the
domain already specifies which User-Agent was used to acquire the clearance cookie (mixing User-Agents with a
`cf_clearance` cookie causes Cloudflare challenges to replay).

---

### Compat patches

`src/config/compat.py:apply_compatibility_patches()` is called at the very top of `src/main.py` before any
heavy imports (specifically before `crawlee`). This handles any Python stdlib compatibility shims needed by
the Crawlee library on the runtime Python version or platform. The call must precede all other imports to avoid
import-time side effects from `crawlee` setting up its event loop policy before the patch runs.
