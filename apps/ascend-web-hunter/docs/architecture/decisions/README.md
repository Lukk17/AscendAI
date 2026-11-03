# ascend-web-hunter - Architecture Decision Records

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
| [ADR-010](ADR-010-producer-aware-session-replay.md) | Every session record names the tier that produced it; a stored session starts the read at the browser tiers. Amended by ADR-018. | Accepted |
| [ADR-011](ADR-011-caller-selectable-starting-tier.md) | A caller may name the tier the escalation chain starts at; escalation continues from there, and a login-redirect URL still outranks it. | Accepted |
| [ADR-012](ADR-012-connect-time-address-pinning.md) | The in-process fetch connects to the address its own SSRF lookup validated, via CURLOPT_RESOLVE; the browser and out-of-process tiers keep pre-dispatch validation as residual risk. | Accepted |
| [ADR-013](ADR-013-concurrent-human-intervention-windows.md) | Concurrent human-intervention windows on one shared display: per-container slots, Redis flow records, joins, ephemeral CDP ports, cascade layout, owner-named VNC URLs. | Accepted |
| [ADR-014](ADR-014-scored-challenge-detection.md) | Scored challenge verdict over five signal families, catalogue with provenance, fixture corpus as the admission rule. | Accepted |
| [ADR-015](ADR-015-patched-browser-tiers-and-tier-memory.md) | Patched browser tiers (`4a-patchright`, `4b-camoufox`), FlareSolverr off by default, the guarded browser route handler and per-domain tier memory. | Accepted |
| [ADR-016](ADR-016-scored-ensemble-replaces-recall-pass.md) | Scored ensemble of trafilatura and readability-lxml replacing the recall pass; higher score wins, ties to trafilatura. | Accepted |
| [ADR-017](ADR-017-schema-extraction-recipes-and-safety.md) | Schema-guided extraction through a configurable model endpoint with self-healing per-domain selector recipes and model-input safety. | Accepted |
| [ADR-018](ADR-018-flaresolverr-tier-removed.md) | The FlareSolverr tier, its settings, its container and its references are removed; the value `3-flaresolverr` is refused and never reused. | Accepted |
| [ADR-019](ADR-019-crawl-jobs.md) | Polling crawl jobs over a shared Redis frontier: Lua-claimed URLs, per-domain politeness, Floci results with incremental recrawl, several instances sharing one crawl. | Accepted |

For monorepo-level decisions see [`../../../../../docs/architecture/decisions/`](../../../../../docs/architecture/decisions/).
