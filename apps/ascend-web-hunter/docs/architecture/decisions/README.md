# ascend-web-hunter — Architecture Decision Records

| ID | Decision | Status |
| :--- | :--- | :--- |
| [ADR-001](ADR-001-multi-tier-extraction-strategy.md) | Multi-tier extraction strategy: six strategies in fixed escalation order. | Accepted |
| [ADR-002](ADR-002-cloudflare-cookie-persistence-redis.md) | Cloudflare cookie persistence in Redis with 2-hour TTL and in-process fallback. | Accepted |
| [ADR-003](ADR-003-novnc-ngrok-captcha-intervention.md) | NoVNC + Ngrok for human CAPTCHA and login-wall intervention; dynamic URL from Ngrok API. | Accepted |
| [ADR-004](ADR-004-searxng-meta-search-backend.md) | SearXNG as the sole meta-search backend; HTML scraping over JSON API. | Accepted |
| [ADR-005](ADR-005-strategy-budget-and-singleton-chromium.md) | READ_TOTAL_BUDGET=90s strategy chain deadline, singleton Chromium in lifespan, escalation recursion guard. | Accepted |
| [ADR-006](ADR-006-proxy-seam-and-fingerprint.md) | Outbound proxy seam and browser fingerprint rotation. | Accepted |
| [ADR-007](ADR-007-structured-output-and-readability-fallback.md) | Structured article output (`output_format=structured`) and readability-lxml fallback for thin extractions. | Accepted |
| [ADR-008](ADR-008-blocklist-vendored-not-fetched.md) | Blocklist vendored into the image, loaded from disk only, refreshed solely via `POST /api/v1/blocklist/refresh`. | Accepted |
| [ADR-009](ADR-009-recall-pass-for-thin-precision-extractions.md) | A trafilatura recall pass when the precision pass is shorter than `CONTENT_RECALL_FALLBACK_RATIO` (0.75) of the page's plain text, longer result wins. | Accepted |

For monorepo-level decisions see [`../../../../../docs/architecture/decisions/`](../../../../../docs/architecture/decisions/).
