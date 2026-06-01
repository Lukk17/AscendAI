# 11. Risks and Technical Debt

---

### Risks

| Risk | Likelihood | Impact | Mitigation |
| :--- | :--- | :--- | :--- |
| **Cloudflare challenge signature drift** | High | Medium | `challenge_dictionary.json` contains WAF signatures and login title patterns that Cloudflare can change without notice. A stale dictionary causes `ChallengeDetector.is_blocked` to miss new challenge types, sending blocked content through to `ContentValidator`. The word-count and error-keyword checks in `ContentValidator` provide a second layer, but they are not guaranteed to catch all Cloudflare challenge pages. Regular dictionary maintenance is required. |
| **NoVNC background task accumulation** | Medium | Medium | `_active_monitor_tasks` holds strong references to background `asyncio.Task` objects. Each task holds a live Chromium context for up to `NOVNC_TIMEOUT_SECONDS` (600 s). A burst of CAPTCHAs on different domains simultaneously creates multiple Chromium processes. No cap on concurrent tasks exists. |
| **Redis single point of failure** | Medium | Low | If Redis is unreachable, `CookieManager` falls back to an in-process dict. Cross-instance cookie sharing is lost silently. A Redis outage during a high-volume crawl causes repeated FlareSolverr or NoVNC triggers for the same domains. |
| **SearXNG HTML DOM changes** | Medium | Medium | `SearxngClient._parse_html_results` selects `article.result` elements from SearXNG's default theme. A SearXNG upgrade that changes this structure silently returns zero results with no exception raised. No test covers a live SearXNG DOM fixture. |
| **`curl_cffi` impersonation fingerprint expiry** | Medium | Medium | `impersonate="chrome120"` in strategies 1 and 2 mimics a specific Chrome version's TLS fingerprint. Sites updated to detect Chrome120 fingerprints, or sites that check for very recent Chrome versions, will challenge or block requests from these strategies more frequently as Chrome120 ages. Bumping the impersonation version requires testing. |

---

### Technical debt

| Item | File | Priority |
| :--- | :--- | :--- |
| No `/ready` endpoint separate from `/health` | `src/main.py:56-58` | Low — blocklist loads synchronously in the lifespan before yield, so `/health` effectively implies readiness. A formal `/ready` endpoint would allow orchestrators to make this explicit. |
| `SearxngClient` instantiated at module load | `src/api/rest/rest_endpoints.py:15`, `src/api/mcp/mcp_server.py:10` | Low — a bad `SEARXNG_BASE_URL` produces no startup error. The first query fails with a connection error at runtime. Lazy validation would catch misconfiguration earlier. |
| `WebReader` and `URLValidator` instantiated at module load | `src/api/rest/rest_endpoints.py:16`, `src/api/mcp/mcp_server.py:11` | Low — means blocklist rules are loaded twice (once in lifespan, once at module import). Refactoring to dependency injection would eliminate the duplicate load. |
| No retry or backoff on SearXNG failures | `src/search/search_client.py` | Medium — a transient SearXNG 429 or 503 propagates immediately as a 503 to the caller with no retry. A single retry with short backoff would handle ephemeral SearXNG rate limits. |
| No cap on concurrent NoVNC tasks | `src/reader/strategies/novnc_strategy.py:94-96` | Medium — see Risks above. A semaphore limiting concurrent Chromium contexts would prevent memory exhaustion under concurrent CAPTCHA triggers. |
| `challenge_dictionary.json` has no versioning or automatic update | `src/reader/cloudflare/challenge_dictionary.json` | Medium — the dictionary is a static asset. Cloudflare signature changes require a manual file update and image rebuild. |
