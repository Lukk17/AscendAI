# 9. Architecture Decisions

---

### ADR index

| ADR | Title | Status | Key trade-off |
| :--- | :--- | :--- | :--- |
| [ADR-001](../decisions/ADR-001-multi-tier-extraction-strategy.md) | Multi-tier extraction: six strategies in fixed escalation order | Accepted | Sequential cost paid per-failure; no per-domain config |
| [ADR-002](../decisions/ADR-002-cloudflare-cookie-persistence-redis.md) | Cloudflare cookie persistence in Redis | Accepted | Redis soft dependency; apex normalisation fails for second-level TLDs |
| [ADR-003](../decisions/ADR-003-novnc-ngrok-captcha-intervention.md) | NoVNC + Ngrok for human CAPTCHA intervention | Accepted | Background task holds Chromium open for up to 10 minutes |
| [ADR-004](../decisions/ADR-004-searxng-meta-search-backend.md) | SearXNG as the meta-search backend | Accepted | HTML parsing is brittle against SearXNG theme changes |

---

### Decisions not (yet) recorded as ADRs

| Decision | Where it lives | Why not an ADR yet |
| :--- | :--- | :--- |
| `curl_cffi` with `impersonate="chrome120"` for HTTP strategies | `beautifulsoup_strategy.py:42`, `trafilatura_strategy.py:40` | Chosen as the best available Chrome impersonation at time of implementation; no alternative was formally evaluated. |
| `playwright-stealth` applied to every `PlaywrightStrategy` context | `playwright_strategy.py:88` | Standard hardening for Playwright; no alternative fingerprint-masking library was evaluated. |
| `headless=False` for Playwright and Crawlee | `playwright_strategy.py:29`, `crawlee_strategy.py:30` | Required by the Playwright base image which provides Xvfb; headless Chromium is detectable by advanced WAFs. Decision predates formal ADR process. |
| `asyncio.to_thread` not used for browser strategies | all browser strategies | Browser strategies are already async-native (Playwright, Crawlee are async APIs). OCR offload via `to_thread` is not needed here. |
| Hard failure on blocklist load failure | `src/main.py:37-39` | Discussed in code comments; not an ADR because the alternative (skip blocklist) was rejected as producing unreliable content. |
