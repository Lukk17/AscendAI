## 1. Session store: capture, model, and profiles

- [x] 1.1 Extend `CookieManager` to store a normalized session blob (cookies + per-origin localStorage) and add `get_storage_state(url, profile)` returning a Playwright-shaped `storage_state` dict.
- [x] 1.2 Split stored records into `auth` (long TTL, sliding) and `waf` (short TTL); add configurable TTL settings; merge both on read.
- [x] 1.3 Re-key the store to `session:{domain}:{profile}` with `profile` defaulting to `"default"`.
- [x] 1.4 Make the Redis-unreachable fallback observable (log "configured, in-memory fallback", not "connected"); keep in-memory as supported local default.
- [x] 1.5 Capture via `context.storage_state()` in the NoVNC monitor and Playwright tier instead of `context.cookies()`.

## 2. Replay session into every fetch tier

- [x] 2.1 curl_cffi: load and inject auth+WAF cookies for the target domain/profile.
- [x] 2.2 FlareSolverr: inject saved cookies via the request `cookies` array; persist returned cookies unconditionally (remove the `cf_clearance` gate).
- [x] 2.3 Playwright: create the context with `storage_state` from the store when present.
- [x] 2.4 Crawlee: pass `storage_state` via `browser_context_options` when present.

## 3. Session lifecycle and API

- [x] 3.1 Add a `SessionManager` with establish (proactive NoVNC), status, and validate/refresh (optional per-domain probe + logged-in marker).
- [x] 3.2 Invoke validation before an authenticated read; slide auth TTL on success; return a `session_expired` outcome on failure instead of serving anonymous content as success.
- [x] 3.3 Add REST + MCP session endpoints/tools: establish login, query status.
- [x] 3.4 Add optional `profile`, starting `tier`, and `output_format` fields to the read request (REST + MCP), threaded through the orchestrator.

## 4. Anti-bot evasion

- [x] 4.1 Introduce a coherent `Fingerprint` value object (UA + locale + timezone + geolocation + viewport) and feed it to every browser tier; remove the mismatched locale/timezone/geo combinations.
- [x] 4.2 Evaluate and (if adopted) switch the stealth layer to a stronger option (e.g. `patchright`).
- [x] 4.3 Add an optional, off-by-default `ProxyProvider` seam wired into all four fetch tiers via config.

## 5. Extraction quality

- [x] 5.1 Switch extractors to trafilatura metadata extraction; map title/author/date/site-name into a structured response gated by `output_format=structured` (default response shape unchanged).
- [x] 5.2 Add a `readability-lxml` fallback scored against trafilatura by length/density; add the dependency.
- [x] 5.3 Wire the existing `SCROLL_*` settings into the Playwright tier for lazy-load/infinite-scroll, bounded by iteration count and wall-clock budget.

## 6. Fetch-correctness bug fixes

- [x] 6.1 Propagate the human-intervention 428 on the `include_links` path (add the missing re-raise before the broad except in `_execute_html_strategy`).
- [x] 6.2 Disable blind redirect following; re-validate each redirect hop with the SSRF guard; pin the validated IP to the connection (resolver/connector) across tiers; validate before FlareSolverr/Crawlee dispatch.
- [x] 6.3 Stop skipping challenge/login detection above 50 000 bytes; move the threshold to a named setting and scan a bounded prefix instead of failing open.
- [x] 6.4 Make `ContentValidator` fail closed when the quality assessment errors.
- [x] 6.5 Honour `PLAYWRIGHT_HEADLESS` in the Crawlee tier (remove hardcoded headed launch).
- [x] 6.6 Gitignore `ascend-web-hunter/src/storage/`, `git rm -r --cached` it, configure Crawlee with an out-of-tree storage dir and `purge_on_start=True`.

## 7. Caching and observability

- [x] 7.1 Add read-result cache-aside keyed by URL + heavy_mode + include_links + profile + output_format, with a configurable TTL.
- [x] 7.2 Add a cardinality-capped registrable-domain label to the strategy outcome metrics.
- [x] 7.3 Wrap FlareSolverr and SearXNG calls in a circuit breaker; surface breaker state in `/ready`.

## 8. Config, docs, and tests

- [x] 8.1 Add all new settings to `Settings` (auth/WAF TTLs, profiles default, proxy, scroll already-present, cache TTL, breaker thresholds, detection-size threshold) and document them.
- [x] 8.2 Write ADRs for the per-profile session model and the storage_state reuse strategy; note SSRF residual risk for out-of-process tiers.
- [x] 8.3 Add/extend unit tests for session capture/replay per tier, auth/WAF TTL split, SSRF redirect/rebind rejection, fail-closed validation, and structured output; keep coverage gate green.
- [ ] 8.4 Confirm the `add-web-search-scraping-e2e` tier tests exercise the authenticated path once this lands.
