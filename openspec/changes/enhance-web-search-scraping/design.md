## Context

AscendWebSearch runs a fixed escalation chain in `WebReader` (`src/reader/web_reader.py`): `1-beautifulsoup` and `2-trafilatura` over the shared `curl_cffi_fetcher`, then `3-flaresolverr`, `4-playwright_stealth`, `5-crawlee_adaptive`, and `6-novnc`. Session state lives in a `CookieManager` singleton keyed `session_cookies:{registrable_domain}` holding `{cookies, user_agent}` with a flat 7200s TTL, backed by Redis when `REDIS_URL` is reachable and an in-process dict otherwise. NoVNC's background monitor harvests `context.cookies()` every few seconds and saves them. Only `curl_cffi_fetcher` reads the session back; the browser tiers do not. The service is single-user and local; there is no auth layer and (per decision) none is being added.

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

**D1 — Session replay into every tier via a normalized session blob.** `CookieManager` grows a `get_storage_state(url, profile)` that returns a Playwright-shaped `storage_state` dict (cookies + origins/localStorage). Each tier injects it: Playwright/Crawlee via `new_context(storage_state=...)`, curl_cffi via a cookie header, FlareSolverr via its request `cookies` array. The NoVNC monitor and Playwright tier persist via `context.storage_state()` (not just `cookies()`), so localStorage-bound auth artifacts survive. FlareSolverr persists returned cookies unconditionally (the `cf_clearance` gate is removed).

**D2 — Auth vs WAF cookie split with independent TTLs.** A stored session separates two record sets: `auth` (long TTL, default 14 days, sliding on successful authenticated read) and `waf` (short TTL, default 30 min). Both are merged on injection. TTLs are configurable. This stops a valid login being discarded every 2 hours while still letting WAF clearance expire quickly.

**D3 — Single-user named profiles.** The session key becomes `session:{domain}:{profile}` with `profile` defaulting to `"default"`. `profile` is a free-form label supplied per request (e.g. `work`, `personal`) so one local user can hold several accounts per site. No identity/auth is implied or enforced; cross-caller isolation is explicitly a non-goal because the service is single-user.

**D4 — Session lifecycle is a first-class capability, not a 428 side effect.** A `SessionManager` exposes establish (open NoVNC for a domain/profile on demand), status (`active|expired|none` + auth-TTL remaining + last-validated), and validate/refresh (a per-domain optional probe + logged-in marker) invoked before an authenticated read so a silently-downgraded anonymous page is reported as `session_expired` rather than returned as success.

**D5 — Storage backend stays pluggable; in-memory is first-class for local.** No Redis is added to the scrapper stack. The silent Redis-unreachable fallback is kept but made observable (logged as "configured, using in-memory fallback", not a misleading "connected"). Encryption-at-rest applies only when a Redis backend is configured; for the in-memory local default it is a no-op.

**D6 — SSRF defense moves to the transport layer.** The edge `is_safe_external_url` check is retained, but fetch tiers disable automatic redirect following and re-validate each redirect `Location`, and pin the validated IP through to connect time (custom resolver/connector) to close the DNS-rebinding TOCTOU. FlareSolverr/Crawlee, which fetch outside our process, are validated before dispatch and noted as residual-risk in an ADR.

**D7 — Anti-bot evasion via a coherent `Fingerprint` value object.** UA + locale + timezone + geolocation + viewport are chosen as one internally consistent set and fed to every browser tier (replacing today's mismatched `en-US`/`UTC` vs `America/New_York`/SF-coords combinations). Stealth library upgrade (evaluate `patchright`) and an optional `ProxyProvider` outbound port (off by default, env-configured) round out evasion. No throttling.

**D8 — Structured extraction is additive.** Extractors switch to `trafilatura.extract(..., output_format="json", with_metadata=True)` mapped into structured fields, with a `readability-lxml` fallback scored against trafilatura by content length/density. The existing flat `{content, status, mode}` response stays the default; structured output is opt-in via `output_format` to avoid breaking existing callers.

**D9 — Caching and circuit breakers reuse existing infrastructure.** Read results cache-aside keyed by `url + heavy_mode + include_links + profile + output_format`; metrics counters gain a cardinality-capped registrable-domain label; FlareSolverr/SearXNG calls are wrapped in a lightweight breaker whose state feeds `/ready`.

## Risks / Trade-offs

- **ToS / account-ban risk:** authenticated LinkedIn scraping violates LinkedIn ToS and risks the account. Accepted by the owner for personal/own-account local use; evasion quality (D7) reduces but does not remove the risk.
- **storage_state vs persistent profiles:** `storage_state` reuse is lighter but some sites bind sessions to Service-Worker/IndexedDB/device state a snapshot misses. We start with `storage_state` (D1) and leave a persistent `launch_persistent_context` profile as a documented follow-up if specific sites still force re-auth.
- **In-memory store loses sessions on restart (D5):** accepted for local, rarely-restarted use; a restart simply requires one re-login.
- **Breadth of the change:** large surface across all tiers and the orchestrator. Mitigated by per-tier tasks, fail-closed validation surfacing regressions early, and the paired e2e tier tests (`add-web-search-scraping-e2e`).
- **Disabling redirects (D6)** may break sites that rely on benign redirects; mitigated by re-validating and re-following safe hops rather than dropping them.
