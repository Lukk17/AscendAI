## Why

ascend-web-hunter escalates a read across four extraction tiers (curl_cffi → FlareSolverr → Playwright → Crawlee, with NoVNC for human login/CAPTCHA), but it cannot reliably scrape login-walled sites such as LinkedIn — the headline pain point. A four-lens investigation (debugger, code review, security audit, architecture) found the login itself works (the NoVNC monitor correctly captures the full cookie jar, including httpOnly auth cookies like `li_at`), but the captured session is **never replayed into the browser tiers**: `PlaywrightStrategy` and `CrawleeStrategy` open a fresh anonymous context with no `storage_state` and no cookies, and only the `curl_cffi` tier reads cookies back — yet `curl_cffi` cannot render LinkedIn's JavaScript app. So the tier that holds the session cannot render the page, and the tier that can render the page never receives the session. Compounding factors: a flat 7200s (2h) TTL discards a login that is valid for months; FlareSolverr only persists cookies when a Cloudflare `cf_clearance` cookie is present, discarding non-Cloudflare auth cookies; and the store is keyed by domain only.

The same investigation surfaced real defects to fix while we are in this code (a swallowed human-intervention signal on the links path, an SSRF guard that only runs at the edge and is bypassed by redirects/DNS-rebinding, challenge detection silently skipped on pages over 50 KB, a content validator that fails open, and committed Crawlee runtime state leaking scraped URLs into git), plus opportunities to make extraction genuinely best-in-class (structured output, readability fallback, the scroll/pagination settings that exist in config but are never wired up, coherent anti-bot evasion, result caching, and per-domain observability).

This is a single, deliberately broad change because the session work, the bug fixes, and the quality work all touch the same fetch tiers and orchestrator and are most safely done together.

## What Changes

- **Authenticated session replay (the anchor):** every fetch tier that can carry a session — curl_cffi (headers), FlareSolverr (its `cookies` payload field), Playwright and Crawlee (`storage_state` / `add_cookies`) — SHALL load and inject the stored session before fetching. The NoVNC monitor SHALL persist the full Playwright `storage_state` (cookies **and** localStorage), not just `context.cookies()`. FlareSolverr SHALL persist the returned cookies unconditionally (drop the `cf_clearance` gate). Stored sessions SHALL separate long-lived auth cookies from short-lived WAF cookies with independent TTLs (auth default measured in days, configurable), support optional named profiles (e.g. two LinkedIn accounts) for a single local user, and be validated/refreshed before an authenticated read rather than silently serving anonymous content.
- **Session API:** a proactive "establish a login for site X (optionally profile Y)" operation that opens the NoVNC flow on demand, a session-status query, and per-request `profile`, starting-`tier`, and `output_format` overrides on the read endpoints (REST + MCP).
- **Anti-bot evasion (defeating target sites, not self-throttling):** coherent browser fingerprints (the current locale/timezone/geolocation combinations are internally inconsistent — a detection tell), a stronger stealth posture, and an optional, off-by-default proxy seam to defeat IP-based blocks. **No request rate-limiting or self-throttling is added** — this service runs locally; rate-limiting is a deployment-stack concern.
- **Extraction quality:** structured output (title, author, date, sitename via trafilatura metadata) alongside the text blob, a readability-lxml fallback when the primary extractor yields thin content, and wiring the existing-but-unused `SCROLL_*` settings into the Playwright tier for infinite-scroll / lazy-loaded pages.
- **Bug fixes (folded in):** propagate the human-intervention 428 on the `include_links` path; re-validate the SSRF guard on every redirect hop and pin the resolved IP across fetch tiers; stop skipping challenge/login detection on pages over 50 KB; make the content validator fail closed (escalate) instead of accepting junk; honour `PLAYWRIGHT_HEADLESS` in the Crawlee tier; and stop committing Crawlee runtime state (gitignore `src/storage/`, purge on start, relocate out of the source tree).
- **Caching & observability:** cache successful read results in the existing cache layer keyed by URL + mode; add a registrable-domain label (cardinality-capped) to the per-tier metrics so success rate is visible per site; and add circuit breakers around FlareSolverr / SearXNG so a down dependency fails fast instead of consuming the timeout.

Out of scope (explicit): PDF/document handling (the service scrapes web pages; documents are handled elsewhere by Docling), a dedicated Redis in the scrapper stack (the in-memory session store is acceptable for a rarely-restarted local deployment; Redis stays optional), per-request rate-limiting, and any multi-tenant authentication layer.

## Capabilities

### New Capabilities
- `web-search-authenticated-sessions`: capture full session state, replay it into every fetch tier, split auth vs WAF cookies with independent TTLs, named single-user profiles, session validation/refresh, and the proactive login + session-status + per-request override API.
- `web-search-antibot-evasion`: coherent browser fingerprints, hardened stealth, and an optional off-by-default proxy seam to defeat target-site anti-bot — with no self-throttling.
- `web-search-extraction-quality`: structured article output, readability fallback, and scroll/pagination handling for dynamic pages.
- `web-search-fetch-correctness`: SSRF redirect/DNS-rebind re-validation across all tiers, full challenge/login detection regardless of page size, fail-closed content validation, human-intervention propagation on the links path, and Crawlee runtime-state hygiene.
- `web-search-caching-observability`: read-result caching, per-domain success metrics, and circuit breakers on external dependencies.

### Modified Capabilities
<!-- None: ascend-web-hunter has no existing capability specs under openspec/specs/. -->

## Impact

- **Code:** `src/reader/web_reader.py` (orchestrator), all of `src/reader/strategies/*`, `src/reader/cloudflare/{cookie_manager,challenge_detector}.py`, `src/runtime/browser_pool.py`, `src/validator/{url_validator,content_validator}.py`, `src/search/search_client.py`, `src/api/rest/rest_endpoints.py`, `src/api/mcp/mcp_server.py`, `src/config/config.py`, `src/observability/metrics.py`.
- **API:** new session endpoints + MCP tools; new optional read fields (`profile`, `tier`, `output_format`); structured-output response shape (additive, version-gated if the envelope changes).
- **Repo hygiene:** `.gitignore` gains `ascend-web-hunter/src/storage/`; that directory is untracked and purged.
- **Config:** new settings for auth/WAF TTLs, profiles, proxy, scroll, cache TTL, circuit-breaker thresholds. No new mandatory external dependency (Redis stays optional; in-memory fallback documented as supported for local use).
- **Dependencies:** adds `readability-lxml` (and optionally a stealth library such as `patchright`); proxy support is configuration-only.
- **Docs/ADRs:** ADRs for the per-profile session model and the storage_state/persistent-session reuse strategy; the e2e tier tests from `add-web-search-scraping-e2e` exercise the authenticated path once landed.
