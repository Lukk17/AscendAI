# Configuration

Every settings field is bound through [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
against environment variables and `.env`. The source of truth is
[src/config/config.py](../src/config/config.py); this table is for quick lookup.

---

### API and server

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `API_PORT` | `7021` | Service port. Compose passes `WEB_HUNTER_API_PORT` |
| `WEB_HUNTER_HOST_PORT` | `7021` | Host port of the service. Added by `add-ascend-python-common`. |
| `API_HOST` | `0.0.0.0` | Bind address (deliberately broad for the container case) |
| `LOG_LEVEL` | `INFO` | `DEBUG | INFO | WARNING | ERROR | CRITICAL` |
| `LOG_FORMAT` | `json` | `json` for log sinks, `color` for a local terminal |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | unset | OTLP trace export endpoint, export whenever it is set. Added by `add-observability`. |
| `OTEL_SDK_DISABLED` | `false` | OpenTelemetry's standard switch, `true` turns the SDK off. Added by `add-ascend-python-common`. |
| `RATE_LIMIT_DEFAULT` | `1200/minute` | Flood-protection rate limit for REST routes and MCP tools; `/health`, `/ready`, `/metrics` and `tools/list` are never limited. Compose passes `WEB_HUNTER_RATE_LIMIT_DEFAULT` |
| `ALLOWED_PRIVATE_HOSTS` | empty | Hosts the URI fetch guard may reach even at a private address. Leave empty, only an e2e sweep sets it. The development compose file fills it from `WEB_HUNTER_ALLOWED_PRIVATE_HOSTS`. |
| `MCP_ALLOWED_HOST_HEADERS` | `ascend-web-hunter,localhost,127.0.0.1` | Host names the `/mcp` endpoint accepts in the `Host` header (inbound). Compose passes `WEB_HUNTER_MCP_ALLOWED_HOST_HEADERS`. `ALLOWED_PRIVATE_HOSTS` above is outbound. Added by `add-python-runtime-upgrades`. |
| `READINESS_PROBE_TIMEOUT_SECONDS` | `3` | Seconds each readiness probe may take. Added by `add-ascend-python-common`. |
| `STARTUP_PROBE_TIMEOUT_SECONDS` | `2` | Seconds each startup banner check may take. Added by `add-ascend-python-common`. |
| `SECURITY_HSTS_MAX_AGE_SECONDS` | `63072000` | Max age of the strict-transport-security header. Added by `add-ascend-python-common`. |
| `FETCH_MAX_REDIRECT_HOPS` | `10` | Redirect hops the URI fetch guard follows. Compose passes `WEB_HUNTER_FETCH_MAX_REDIRECT_HOPS`. Added by `add-ascend-python-common`. |
| `OTEL_SERVICE_NAME` | `ascend-web-hunter` | Service name carried on every exported span. Fixed in `compose.ascend-web-hunter.yaml`. |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.version=0.0.7` | Resource attributes carried on every exported span. Fixed in `compose.ascend-web-hunter.yaml`. |

---

### SearXNG (meta-search)

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `SEARXNG_BASE_URL` | `http://localhost:9020` | SearXNG host; Docker network sees `http://searxng:8080` |
| `SEARXNG_USER_AGENT` | `ascend-web-hunter/1.0` | Forwarded to SearXNG |
| `SEARXNG_X_REAL_IP` | `127.0.0.1` | `X-Real-IP` sent upstream |
| `SEARXNG_X_FORWARDED_FOR` | `127.0.0.1` | `X-Forwarded-For` sent upstream |

---

### Blocklist and content validation

The blocklist is loaded from disk at startup and never downloaded automatically. `BLOCKLIST_PATH` points at the
file vendored into the repository and the container image (`src/assets/fanboy-annoyance.txt`); a missing or
corrupt file there is a packaging defect and the service refuses to start. `BLOCKLIST_URL` is only reached by
`POST /api/v1/blocklist/refresh`, an explicit operator action - see
[the architecture decision record](architecture/decisions/ADR-008-blocklist-vendored-not-fetched.md).

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `BLOCKLIST_URL` | `https://secure.fanboy.co.nz/fanboy-annoyance.txt` | Source `POST /api/v1/blocklist/refresh` downloads from |
| `BLOCKLIST_PATH` | `src/assets/fanboy-annoyance.txt` | Path to the vendored blocklist file; also where a refresh writes |
| `BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS` | `60.0` | Minimum seconds between accepted refresh attempts; a call inside the window gets 429 |
| `VALIDATION_MIN_WORDS` | `10` | Minimum word count for a tier's output to count as success |
| `MIN_FLESCH_SCORE` | `20.0` | Combined-with-lexicon-count quality threshold |
| `MIN_TTR` | `0.1` | Repetitive-text guard (Type-Token Ratio) |
| `ERROR_KEYWORDS` | `["Access Denied","403 Forbidden",...]` | Phrases that mark extraction as failed |

---

### Strategy chain

The read ladder climbs `1-beautifulsoup`, `2-trafilatura`, `3-flaresolverr` (only while
`FLARESOLVERR_ENABLED` is true), `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` (only while
`CAMOUFOX_ENABLED` is true), `5-crawlee_adaptive` and `6-novnc`, in that order. A caller may start the
chain at any tier with the `tier` field. A domain that succeeded at a tier before restarts at the
remembered tier for `TIER_MEMORY_TTL_SECONDS`.

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `READ_TOTAL_BUDGET` | `90.0` | Wall-clock cap (seconds) across tiers 1-5. NoVNC exempt. |
| `EXTRACT_TIMEOUT` | `30.0` | Per-tier extraction timeout |
| `SEARCH_TIMEOUT` | `10.0` | SearXNG request timeout |
| `DEFAULT_TIMEOUT` | `30.0` | Generic HTTP timeout |
| `DYNAMIC_CONTENT_WAIT` | `2000` | Playwright post-load settle (milliseconds) |
| `SCROLL_ITERATIONS` | `5` | Scroll steps for infinite-scroll pages |
| `SCROLL_STEP_PX` | `1500` | Pixels per scroll step |
| `NETWORKIDLE_POLL_MS` | `1000` | Page-quiet poll interval in milliseconds for browser tiers. Added by `enhance-web-search-tier-ladder`. |
| `SCROLL_PAUSE_MS` | `200` | Pause in milliseconds between two scroll steps. Added by `enhance-web-search-tier-ladder`. |
| `MAX_REQUESTS_PER_CRAWL` | `5` | Crawlee request cap |
| `BREAKER_FAILURE_THRESHOLD` | `3` | Consecutive failures before a circuit breaker opens |
| `BREAKER_RECOVERY_TIMEOUT_SECONDS` | `60.0` | Seconds after which an open breaker moves to half-open and allows one probe |
| `DOMAIN_METRIC_CARDINALITY_CAP` | `50` | Maximum distinct registrable-domain label values tracked in `STRATEGY_ATTEMPTS_TOTAL`; further domains bucket under `other` |
| `CRAWLEE_STORAGE_DIR` | `.crawlee_storage` | Out-of-tree directory for Crawlee request queues and key-value stores |
| `CRAWLEE_MEMORY_MBYTES` | unset | Explicit memory budget in MB for Crawlee's autoscaler; when unset Crawlee infers a budget from total system memory |
| `PROXY_URL` | empty | Optional outbound proxy URL for all fetch tiers |
| `READ_CACHE_TTL_SECONDS` | `300` | TTL in seconds for the read-result cache-aside entries |

---

### Extraction

Extraction has no settings. Trafilatura and readability-lxml both run on every page and the higher
scoring ensemble result wins, with ties going to trafilatura. Changed by
`enhance-web-search-extraction-and-tiers`.

---

### Browser and CAPTCHA infrastructure

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `PLAYWRIGHT_HEADLESS` | `false` | Set `true` in CI or any container without an X server |
| `FLARESOLVERR_URL` | `http://localhost:8191/v1` | FlareSolverr Cloudflare-bypass endpoint |
| `FLARESOLVERR_ENABLED` | `false` | Route reads through the 3-flaresolverr tier. Added by `enhance-web-search-tier-ladder`. |
| `CAMOUFOX_ENABLED` | `true` | Route reads through the 4b-camoufox tier. Added by `enhance-web-search-tier-ladder`. |
| `SELENIUM_BROWSER_CDP_URL` | `ws://localhost:4444/playwright` | CDP URL for remote browser (legacy naming) |
| `SELENIUM_BROWSER_VNC_URL` | `http://localhost:7900` | Local NoVNC fallback |
| `PUBLIC_VNC_URL` | `http://localhost:7900` | Public NoVNC URL; `http://ngrok:4040/api/tunnels` for dynamic Ngrok |
| `NOVNC_TIMEOUT_SECONDS` | `600` | NoVNC monitor task lifetime (cookie capture window) |
| `CHALLENGE_CLEAR_WAIT_SECONDS` | `12.0` | How long the headful Playwright tier waits for a Cloudflare challenge to auto-clear before escalating to NoVNC |
| `CHALLENGE_DETECTION_MAX_BYTES` | `50000` | Prefix length scanned by the challenge detector |
| `CHALLENGE_WALL_MAX_BYTES` | `50000` | Max page size for a weak challenge marker |
| `CHALLENGE_SCORE_THRESHOLD` | `100` | Score at or above which a page is a wall. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_RICH_CONTENT_WORDS` | `150` | Extracted words at or above which the rich-content guard fires. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_FORM_DOMINANCE_RATIO` | `0.6` | Share of visible text inside forms at or above which form dominance fires. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_MIN_WORDS_PER_KB` | `2.0` | Extracted words per kilobyte of HTML under which thin text fires. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_THIN_LINK_COUNT` | `5` | Fewer anchors with href than this fires few links. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_RICH_LINK_COUNT` | `20` | At least this many anchors with href fires the many-links guard. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_SHAPE_MAX_BYTES` | `500000` | Bounds the extraction the shape family uses. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_DEFINITIVE_HEADER` | `200` | Weight of the definitive_header signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE` | `80` | Weight of the interstitial_structure signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_VENDOR_SCRIPT` | `60` | Weight of the vendor_script signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_VENDOR_PRESENCE` | `30` | Weight of the vendor_presence signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_STATUS_EMPTY_BODY` | `200` | Weight of the status_empty_body signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_STATUS_SMALL_BODY` | `50` | Weight of the status_small_body signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_STATUS_LARGE_BODY` | `20` | Weight of the status_large_body signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_CAPTCHA_INPUT` | `50` | Weight of the captcha_input signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_CAPTCHA_ELEMENT` | `40` | Weight of the captcha_element signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_FORM_DOMINANCE` | `40` | Weight of the form_dominance signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY` | `40` | Weight of the script_only_body signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_THIN_TEXT` | `20` | Weight of the thin_text signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_FEW_LINKS` | `20` | Weight of the few_links signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_NO_ARTICLE` | `20` | Weight of the no_article signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_RICH_CONTENT` | `-60` | Weight of the rich_content guard signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_MANY_LINKS` | `-20` | Weight of the many_links guard signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_PHRASE_TITLE` | `60` | Weight of the phrase_title signal. Added by `detect-challenge-walls-in-any-language`. |
| `CHALLENGE_WEIGHT_PHRASE_BODY` | `30` | Weight of the phrase_body signal. Added by `detect-challenge-walls-in-any-language`. |
| `NOVNC_COOKIE_SYNC_POLL_SECONDS` | `5.0` | Poll interval in seconds for the NoVNC cookie-sync background monitor |
| `NOVNC_MAX_CONCURRENT_FLOWS` | `4` | Maximum concurrent intervention windows per container: a per container memory constraint as much as a display one. Added by `open-several-novnc-windows-at-once`. |
| `NOVNC_DISPLAY_SIZE` | `1920x1080` | Size of the shared Xvfb display as `<width>x<height>`, read by Xvfb and the service from the same variable; the Dockerfile also sets it for a container started without compose. Added by `open-several-novnc-windows-at-once`. |
| `NOVNC_WINDOW_WIDTH_PX` | `1280` | Width in pixels of each intervention window, wide enough for a reCAPTCHA image grid. Added by `open-several-novnc-windows-at-once`. |
| `NOVNC_WINDOW_HEIGHT_PX` | `800` | Height in pixels of each intervention window; leaves 280 px of the 1080 display for the cascade and browser chrome. Added by `open-several-novnc-windows-at-once`. |
| `NOVNC_WINDOW_CASCADE_OFFSET_PX` | `48` | Cascade step in pixels between intervention windows, wider than a fluxbox title bar. Added by `open-several-novnc-windows-at-once`. |
| `NOVNC_FLOW_LEASE_GRACE_SECONDS` | `30.0` | Teardown grace added on top of `NOVNC_TIMEOUT_SECONDS` before a held flow is reclaimed. Added by `open-several-novnc-windows-at-once`. |
| `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS` | `30.0` | Interval in seconds between lease-sweeper runs, one lease grace period. Added by `open-several-novnc-windows-at-once`. |
| `NOVNC_FLOW_CANCEL_GRACE_SECONDS` | `10.0` | Bounds reclamation and shutdown. Added by `open-several-novnc-windows-at-once`. |
| `NOVNC_BUSY_RETRY_AFTER_SECONDS` | `30` | Short actionable poll interval answered in the 409 `Retry-After` header, not the flow timeout. Added by `open-several-novnc-windows-at-once`. |
| `NOVNC_PUBLIC_URL` | unset | One base address shared by every container, the address of the web-hunter edge proxy of `scale-web-hunter-across-containers` with no path, from which each container builds `<NOVNC_PUBLIC_URL>/novnc/<hostname>/vnc.html` for its own flows. No NoVNC port is published by any container. Unset keeps `PUBLIC_VNC_URL` and the one Ngrok tunnel. Added by `open-several-novnc-windows-at-once`. |

---

### Container-only variables

These are read by the image itself, not by `config.py`, so they have no entry in
[src/config/config.py](../src/config/config.py) and only apply when the service runs in a container.

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `VNC_PASSWORD` | unset | Password for the NoVNC desktop. `docker-entrypoint.sh` turns it into an encrypted x11vnc password file at boot. Unset means x11vnc runs with `-nopw` and the container logs a warning. The VNC protocol truncates the value to 8 characters. |

Two further variables belong to sibling containers in the scrapper compose stack rather than to this service, and both
are mandatory there. `SEARXNG_SECRET` is SearXNG's session-signing key, which is why the settings overlay carries no
`secret_key` entry, and `NGROK_AUTHTOKEN` authenticates the NoVNC tunnel.

---

### Persistence

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `REDIS_URL` | `redis://127.0.0.1:6379/0` | Redis for clearance-cookie persistence. Shared storage for the rate limit windows, one budget per caller under the key prefix `ascend-web-hunter` |
| `SESSION_AUTH_TTL_SECONDS` | `1209600` | Sliding TTL for auth cookies (long-lived, 14 days) |
| `SESSION_WAF_TTL_SECONDS` | `1800` | TTL for WAF-clearance cookies (short-lived, 30 minutes) |
| `SESSION_DEFAULT_PROFILE` | `default` | Profile label used when no profile is specified per-request |
| `TIER_MEMORY_TTL_SECONDS` | `86400` | TTL in seconds for the per-domain tier memory. Added by `enhance-web-search-tier-ladder`. |
| `USER_AGENTS_PATH` | `src/assets/user_agents.json` | Rotated UA pool for cheap tiers |
| `FILE_ENCODING` | `utf-8` | Default file encoding |

---

### Structured extraction, recipes and document routing

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `EXTRACTION_SCHEMA_MAX_BYTES` | `16384` | Maximum size in bytes of the caller-supplied extraction schema. Added by `enhance-web-search-extraction-and-tiers`. |
| `EXTRACTION_LLM_BASE_URL` | empty | Base URL of the OpenAI-compatible endpoint schema extraction calls. Empty turns the schema format off. Added by `enhance-web-search-extraction-and-tiers`. |
| `EXTRACTION_LLM_MODEL` | empty | Model name sent to the extraction endpoint. Added by `enhance-web-search-extraction-and-tiers`. |
| `EXTRACTION_LLM_API_KEY` | empty | API key for the extraction endpoint, read from the repository `.env` file only. Added by `enhance-web-search-extraction-and-tiers`. |
| `EXTRACTION_LLM_MAX_INPUT_CHARS` | `60000` | Page text characters sent to the extraction endpoint before the cap cuts them. Added by `enhance-web-search-extraction-and-tiers`. |
| `EXTRACTION_LLM_TIMEOUT_SECONDS` | `60` | Timeout in seconds for one extraction model call. Added by `enhance-web-search-extraction-and-tiers`. |
| `RECIPE_TTL_SECONDS` | `604800` | TTL in seconds for a stored extraction recipe. Added by `enhance-web-search-extraction-and-tiers`. |
| `RECIPE_SELECTOR_MAX_CHARS` | `512` | Maximum characters of one stored CSS selector. Added by `enhance-web-search-extraction-and-tiers`. |
| `DOCUMENT_MAX_BYTES` | `52428800` | Maximum bytes fetched for one routed PDF, image or audio file. Added by `enhance-web-search-extraction-and-tiers`. |
| `DOCLING_SERVE_URL` | `http://docling-serve:5001` | Base URL of the docling-serve document conversion service. Empty turns the PDF route off. Added by `enhance-web-search-extraction-and-tiers`. |
| `ASCEND_OCR_URL` | `http://ascend-ocr:7022` | Base URL of the ascend-ocr service. Empty turns the image route off. Added by `enhance-web-search-extraction-and-tiers`. |
| `OCR_ROUTE_TIMEOUT_SECONDS` | `300` | Timeout in seconds polling one ascend-ocr job. Added by `enhance-web-search-extraction-and-tiers`. |
| `AUDIO_SCRIBE_URL` | `http://ascend-audio-scribe:7017` | Base URL of the ascend-audio-scribe service. Empty turns the audio route off. Added by `enhance-web-search-extraction-and-tiers`. |
| `READ_CACHE_PURGE_RECONNECT_SECONDS` | `5` | Wait in seconds between two connection attempts of the read cache purge subscriber. Added by `enhance-web-search-extraction-and-tiers`. |

---

### Crawl jobs at scale

`POST /api/v1/crawl/jobs` answers HTTP 202 with a `job_id`, state `waiting` and a `poll_after_seconds`
hint; `GET /api/v1/crawl/jobs/{job_id}` and `GET /api/v1/crawl/jobs` read status and list,
`DELETE /api/v1/crawl/jobs/{job_id}` cancels. The MCP tools `crawl_submit`, `crawl_job_status`,
`crawl_list_jobs` and `crawl_cancel_job` carry the same fields. Every job belongs to one tenant from
REST `X-Ascend-Tenant` (or `default` with no header); a job of another tenant answers 404
`job_not_found`, and a tenant outside `[a-z0-9-]{1,64}` is refused with 400 `invalid_tenant`.

SSRF rules: every seed is checked at submission with the same guard single reads use, and a seed with
a scheme other than `http` or `https`, with userinfo, or resolving to a non-public address is refused
with HTTP 400 `unsafe_uri` and no job is created. Every discovered link, redirect hop, robots.txt
fetch and sitemap fetch goes through the same guard and connect-time pinning; a link that fails is
dropped and counted as `skipped_unsafe`.

Honest scale: the ceiling is the hundreds-of-thousands-of-pages class per job across several
workers. Several ascend-web-hunter containers share one crawl through Redis Lua scripts, with a
per-domain concurrency cap and crawl delay that hold for all instances together. See
[ADR-019](architecture/decisions/ADR-019-crawl-jobs.md).

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `CRAWL_MAX_SEEDS` | `20` | Most seeds in one crawl request. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_MAX_PATTERNS` | `50` | Most include patterns and most exclude patterns in one crawl request. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_MAX_DEPTH` | `5` | Largest `max_depth` a crawl request may ask for. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_DEFAULT_DEPTH` | `2` | `max_depth` when the request has none, refused at startup above `CRAWL_MAX_DEPTH`. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_MAX_PAGES` | `10000` | Largest `page_budget` a crawl request may ask for. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_DEFAULT_PAGE_BUDGET` | `100` | `page_budget` when the request has none, refused at startup above `CRAWL_MAX_PAGES`. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_ROBOTS_OPT_OUT_DOMAINS` | empty | Seed domains for which `respect_robots` false is accepted. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_RESULT_S3_BUCKET` | `web-hunter-crawls` | Bucket of the crawl results. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_RESULT_S3_PREFIX` | `crawl-results/` | Key prefix of the crawl results after the tenant prefix. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_JOB_RETENTION_SECONDS` | `604800` | Lifetime of job records, results, frontier keys and recrawl state. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_DOMAIN_CONCURRENCY` | `2` | Pages of one domain read at once, all instances together. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_DEFAULT_DELAY_SECONDS` | `1` | Least time between two fetches of one domain. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_PROXY_URL` | empty | Customer proxy for crawl fetches only. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_CLAIM_LEASE_SECONDS` | `120` | Lifetime of a page claim. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_CLAIM_MAX_EXPIRIES` | `2` | Claim expiries after which a URL counts as failed. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_WORKER_CONCURRENCY` | `4` | Crawl worker tasks each instance starts. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_WORKER_IDLE_SECONDS` | `1` | Wait of a worker that found nothing to claim. Added by `enhance-web-search-crawl-at-scale`. |
| `CRAWL_POLL_AFTER_SECONDS` | `5` | The `poll_after_seconds` hint of a crawl submission. Added by `enhance-web-search-crawl-at-scale`. |

---

### Object store (shared S3 client)

The object store rows live in a section of their own because `add-file-download`
adds to them later.

| Variable | Default | Purpose |
| :--- | :--- | :--- |
| `OBJECT_STORE_S3_ENDPOINT` | `http://localhost:9070` | Address of the S3-compatible store. Added by `enhance-web-search-crawl-at-scale`. |
| `OBJECT_STORE_S3_ACCESS_KEY` | empty | Access key of the S3-compatible store. Added by `enhance-web-search-crawl-at-scale`. |
| `OBJECT_STORE_S3_SECRET_KEY` | empty | Secret key of the S3-compatible store. Added by `enhance-web-search-crawl-at-scale`. |

---

### Choosing values

- **`READ_TOTAL_BUDGET`**: 90 s is the default; tune up if your typical Playwright sites take more than 30 s
  per render, tune down if a chat assistant is the caller and 30 s already feels broken.
- **`PLAYWRIGHT_HEADLESS`**: `false` is the stealth-friendly posture and matches the Docker base image which
  ships Xvfb. Flip to `true` only when there is no display server (lightweight CI, bare-metal headless host).
- **`PUBLIC_VNC_URL` vs `SELENIUM_BROWSER_VNC_URL`**: the public URL is what gets returned in the 428 body
  for the human; the local URL is the in-cluster fallback when Ngrok cannot be reached. The dynamic Ngrok
  path uses `http://ngrok:4040/api/tunnels` to discover the active public URL at runtime.
- **`READ_TOTAL_BUDGET` and `STRATEGY_DURATION_SECONDS` histogram buckets**: the metrics histogram buckets at
  `[0.1, 0.5, 1, 2, 5, 10, 30, 60, 90, 120, 300, 600]` cover up to NoVNC's full timeout. If you raise the
  budget past 90 s, also widen the histogram buckets so the upper tail is observable.
