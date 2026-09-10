# 9. Architecture Decisions

---

### ADR index

| ADR | Title | Status | Key trade-off |
| :--- | :--- | :--- | :--- |
| [ADR-001](../decisions/ADR-001-multi-tier-extraction-strategy.md) | Multi-tier extraction: six strategies in fixed escalation order | Accepted | Sequential cost paid per-failure; no per-domain config |
| [ADR-002](../decisions/ADR-002-cloudflare-cookie-persistence-redis.md) | Cloudflare cookie persistence in Redis | Accepted | Redis soft dependency; apex normalisation fails for second-level TLDs |
| [ADR-003](../decisions/ADR-003-novnc-ngrok-captcha-intervention.md) | NoVNC + Ngrok for human CAPTCHA intervention | Accepted | Background task holds Chromium open for up to 10 minutes |
| [ADR-004](../decisions/ADR-004-searxng-meta-search-backend.md) | SearXNG as the meta-search backend | Accepted | HTML parsing is brittle against SearXNG theme changes |
| [ADR-005](../decisions/ADR-005-strategy-budget-and-singleton-chromium.md) | READ_TOTAL_BUDGET strategy chain deadline, singleton Chromium | Accepted | A slow tier can still consume most of the 90s budget before the deadline check runs |
| [ADR-006](../decisions/ADR-006-proxy-seam-and-fingerprint.md) | Outbound proxy seam and browser fingerprint rotation | Accepted | Proxy is off by default; no automatic proxy health checking |
| [ADR-007](../decisions/ADR-007-structured-output-and-readability-fallback.md) | Structured output and readability-lxml fallback | Accepted | readability-lxml fallback adds latency on genuinely empty pages |
| [ADR-008](../decisions/ADR-008-blocklist-vendored-not-fetched.md) | Blocklist vendored into the image, refreshed only on operator request | Accepted | Vendored file goes stale silently until someone calls refresh or rebuilds the image |
| [ADR-009](../decisions/ADR-009-recall-pass-for-thin-precision-extractions.md) | Recall pass when the precision extraction is thin against the page | Accepted | A length ratio cannot tell dropped content from sidebars, so some news articles pay a second pass for no gain |

---

### Decisions not (yet) recorded as ADRs

| Decision | Where it lives | Why not an ADR yet |
| :--- | :--- | :--- |
| `curl_cffi` with `impersonate="chrome120"` for HTTP strategies | `beautifulsoup_strategy.py:42`, `trafilatura_strategy.py:40` | Chosen as the best available Chrome impersonation at time of implementation; no alternative was formally evaluated. |
| `playwright-stealth` applied to every `PlaywrightStrategy` context | `playwright_strategy.py:88` | Standard hardening for Playwright; no alternative fingerprint-masking library was evaluated. |
| `headless=False` for Playwright and Crawlee | `playwright_strategy.py:29`, `crawlee_strategy.py:30` | Required by the Playwright base image which provides Xvfb; headless Chromium is detectable by advanced WAFs. Decision predates formal ADR process. |
| `asyncio.to_thread` not used for browser strategies | all browser strategies | Browser strategies are already async-native (Playwright, Crawlee are async APIs). OCR offload via `to_thread` is not needed here. |
