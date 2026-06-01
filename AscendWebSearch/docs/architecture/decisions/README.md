# AscendWebSearch — Architecture Decision Records

| ID | Decision | Status |
| :--- | :--- | :--- |
| [ADR-001](ADR-001-multi-tier-extraction-strategy.md) | Multi-tier extraction strategy: six strategies in fixed escalation order. | Accepted |
| [ADR-002](ADR-002-cloudflare-cookie-persistence-redis.md) | Cloudflare cookie persistence in Redis with 2-hour TTL and in-process fallback. | Accepted |
| [ADR-003](ADR-003-novnc-ngrok-captcha-intervention.md) | NoVNC + Ngrok for human CAPTCHA and login-wall intervention; dynamic URL from Ngrok API. | Accepted |
| [ADR-004](ADR-004-searxng-meta-search-backend.md) | SearXNG as the sole meta-search backend; HTML scraping over JSON API. | Accepted |
| [ADR-005](ADR-005-strategy-budget-and-singleton-chromium.md) | READ_TOTAL_BUDGET=90s strategy chain deadline, singleton Chromium in lifespan, escalation recursion guard. | Accepted |

For monorepo-level decisions see [`../../../../docs/architecture/decisions/`](../../../../docs/architecture/decisions/).
