## Context

ascend-web-hunter runs a fixed escalation chain in `WebReader` (`src/reader/web_reader.py`): `1-beautifulsoup` and `2-trafilatura` over the shared `curl_cffi_fetcher`, then `3-flaresolverr`, `4-playwright_stealth`, `5-crawlee_adaptive`, and `6-novnc`. Session state lives in a `CookieManager` singleton keyed `session_cookies:{registrable_domain}` holding `{cookies, user_agent}` with a flat 7200s TTL, backed by Redis when `REDIS_URL` is reachable and an in-process dict otherwise. NoVNC's background monitor harvests `context.cookies()` every few seconds and saves them. Only `curl_cffi_fetcher` reads the session back; the browser tiers do not. The service is single-user and local; there is no auth layer and (per decision) none is being added.

## Goals / Non-Goals

**Goals:**
- Make authenticated scraping of JS-heavy login-walled sites (LinkedIn the canonical case) work durably: log in once via NoVNC, then reuse that session headlessly across requests.
- Fix the correctness/security defects in the fetch path found during investigation.
- Raise extraction quality and add caching + per-domain observability, and improve evasion of target-site anti-bot.

**Non-Goals:**
- PDF/document extraction (out — handled by Docling elsewhere).
- A dedicated Redis for the scrapper stack; the in-memory store is supported for local use.
- Request rate-limiting / self-throttling (a deployment-stack concern).
- Multi-tenant authentication or per-end-user identity. "Profiles" are local, user-supplied labels, not authenticated principals.

## Decisions

**D1 — Session replay into every tier via a normalized session blob.** `CookieManager` grows a `get_storage_state(url, profile)` that returns a Playwright-shaped `storage_state` dict (cookies + origins/localStorage) and a `get_flat_cookies(url, profile)` for the two tiers that speak name/value pairs. Each tier injects it: Playwright and Crawlee via `storage_state` in their context options, curl_cffi via the request cookie jar, FlareSolverr via its request `cookies` array. As built, capture happens in two places: the NoVNC monitor persists `context.storage_state()` so localStorage-bound auth artifacts survive, and the FlareSolverr tier persists the flat cookie set it returns, unconditionally, with the `cf_clearance` gate removed. The Playwright tier replays a stored session but does not write one back.

**D1a — Routing is producer-aware (added after the first landing, ADR-010).** The original rule was that the mere existence of a stored session sent a read straight to the browser tiers. Measurement on 2026-09-10 showed that this hands a FlareSolverr-earned Cloudflare clearance to Playwright, whose fingerprint did not solve the challenge, so the second read of a site came back slower and worse than the cold first read (defect A61). `CookieManager` now records which tier produced a session, and `_select_strategies` routes a FlareSolverr-produced session back through FlareSolverr first and a browser-produced session to the browser tiers.

**D2 — Auth vs WAF cookie split with independent TTLs.** A stored session separates two record sets: `auth` (long TTL, default 14 days, sliding on successful authenticated read) and `waf` (short TTL, default 30 min). Both are merged on injection. TTLs are configurable. This stops a valid login being discarded every 2 hours while still letting WAF clearance expire quickly.

**D3 — Single-user named profiles.** The session key becomes `session:{domain}:{profile}` with `profile` defaulting to `"default"`. `profile` is a free-form label supplied per request (e.g. `work`, `personal`) so one local user can hold several accounts per site. No identity/auth is implied or enforced; cross-caller isolation is explicitly a non-goal because the service is single-user.

**D4 — Session lifecycle is a first-class capability, not a 428 side effect.** A `SessionManager` exposes establish (open NoVNC for a domain/profile on demand), status (`active|expired|none` plus auth-TTL remaining and last-validated), clear (delete a poisoned session and purge that domain's cached reads), and validate. As built, validate is a TTL plus stored-cookie check that slides the auth TTL on success, not a per-domain network probe with a logged-in marker, and the read path does not call it, so there is no `session_expired` read outcome. What actually stops a logged-out page being returned as an authenticated success is D6's detection work, which scans a bounded prefix of every response for challenge and login signatures, plus the pre-emptive login-redirect URL check that forces the NoVNC tier. A probe-based validate and a `session_expired` outcome remain open follow-ups.

**D5 — Storage backend stays pluggable; in-memory is first-class for local.** No Redis is added to the scrapper stack. The silent Redis-unreachable fallback is kept but made observable (logged as "configured, using in-memory fallback", not a misleading "connected"). Encryption-at-rest applies only when a Redis backend is configured; for the in-memory local default it is a no-op.

**D6 — SSRF defense moves to the transport layer.** The edge `is_safe_external_url` check is retained, and the curl_cffi tier disables automatic redirect following, re-validating each redirect `Location` before following it, up to ten hops. `validate_redirect_chain` re-checks a response history hop by hop. FlareSolverr and Crawlee, which fetch outside our process, are validated before dispatch and noted as residual risk. Pinning the validated IP through to connect time was designed but not built: no custom resolver or connector shipped, so the DNS-rebinding window is narrowed by re-validation rather than closed, and closing it stays an open follow-up.

**D7 — Anti-bot evasion via a coherent `Fingerprint` value object.** UA, locale, timezone, geolocation and viewport are chosen as one internally consistent set and fed to every browser tier, replacing the mismatched `en-US`/`UTC` against `America/New_York`/SF-coords combinations. `patchright` was evaluated as a stealth-layer replacement and not adopted (ADR-006), so `playwright-stealth` 2.0.3 stays, applied per page. An optional `ProxyProvider` outbound port (off by default, env-configured) is wired into all four fetch tiers. No throttling.

**D8 — Structured extraction is additive.** Extractors switch to `trafilatura.extract(..., output_format="json", with_metadata=True)` mapped into structured fields, with a `readability-lxml` fallback scored against trafilatura by content length and density. The existing flat `{content, status, mode}` response stays the default. As built, `output_format` threads through `WebReader.read`, `read_with_links` and the cache key, but neither the REST nor the MCP read operation exposes the field, so the structured path is reachable only from inside the service. Surfacing it on the API is an open follow-up.

**D9 — Caching and circuit breakers.** Read results are cached aside, keyed by `url + heavy_mode + include_links + profile + output_format`. There was no existing cache layer to reuse, so this is a new in-process dict on `WebReader` with a monotonic-clock TTL (`READ_CACHE_TTL_SECONDS`, default 300 s) and a `clear_cache_for_domain` purge that the session-clear endpoint calls. It is per-process and dies with the container, which is acceptable for a local single-instance deployment. Metrics counters gain a cardinality-capped registrable-domain label. FlareSolverr and SearXNG calls are wrapped in a lightweight breaker whose state feeds `/ready`.

## Risks / Trade-offs

- **ToS / account-ban risk:** authenticated LinkedIn scraping violates LinkedIn ToS and risks the account. Accepted by the owner for personal/own-account local use; evasion quality (D7) reduces but does not remove the risk.
- **storage_state vs persistent profiles:** `storage_state` reuse is lighter but some sites bind sessions to Service-Worker/IndexedDB/device state a snapshot misses. We start with `storage_state` (D1) and leave a persistent `launch_persistent_context` profile as a documented follow-up if specific sites still force re-auth.
- **In-memory store loses sessions on restart (D5):** accepted for local, rarely-restarted use; a restart simply requires one re-login.
- **Breadth of the change:** large surface across all tiers and the orchestrator. Mitigated by per-tier tasks, fail-closed validation surfacing regressions early, and the paired e2e tier tests (`add-web-search-scraping-e2e`), which have since run green: the 2026-09-18 sweep passed all eleven automated specs, spec 7 Part 2 proving the capture-and-replay path end to end.
- **Disabling redirects (D6)** may break sites that rely on benign redirects. Mitigated by re-validating and re-following safe hops rather than dropping them.

## Follow-ups left open at landing

Three pieces of this design were specified and not built. They are named here so the gap stays visible rather than implied:

- No IP pinning at connect time (D6). Re-validation narrows the DNS-rebinding window instead of closing it.
- `SessionManager.validate()` is a TTL and cookie-presence check, not a network probe, and the read path never calls it, so there is no `session_expired` read outcome (D4).
- `output_format=structured` is orchestrator-only and unreachable from REST or MCP (D8), as is any starting-`tier` override.
