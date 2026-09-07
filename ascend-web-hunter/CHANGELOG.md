# Changelog

All notable changes to the ascend-web-hunter project will be documented in this file.

## [0.0.3]

- **Refactored:** Unified scraping strategies into a cohesive Orchestrator loop.
- **Refactored:** Enforced identical `ContentValidator` rule boundaries (with default of 10 words) across `read` and `read_with_links` HTTP flows.
- **Added:** Global HTTP 428 Precondition Required exception mapping natively into FastAPI.
- **Improved:** Re-architected NoVNC tracking to utilize an unconditional, persistent Redis-backed 5-second polling loop to prevent heuristic misfires.
- **Added:** VNC authentication. `VNC_PASSWORD` is turned into an encrypted x11vnc password file by a new container entrypoint; unset falls back to the previous open desktop with a warning at boot.
- **Added:** `deploy-standalone/` bundle for running this stack on a host of its own, with pinned images, its own `.env.example` and SearXNG overlay, and no build context.
- **Changed:** SearXNG `secret_key` moved out of the committed settings overlay and into the `SEARXNG_SECRET` environment variable. The previously committed value is public and compromised.
- **Added:** Healthchecks on SearXNG and FlareSolverr with `condition: service_healthy` gating, so the service no longer starts against a cold upstream and opens its circuit breaker.
- **Added:** Resource limits and bounded container logs across the scrapper stack.
- **Changed:** SearXNG upgraded to `2026.8.14`, FlareSolverr to `v3.5.0`.

Note on numbering: this entry was drafted as `[0.1.0]` while the manifest carried a version that never matched any published image. It is renumbered to `0.0.3` so that the changelog, the manifest and the registry tags all agree. Images `v0.0.1` and `v0.0.2` correspond to the two entries below.

## [0.0.2]

- **Added:** Complete network stack including Playwright `headless=False` browser execution rendering inside Docker via `fluxbox` and `Xvfb`.
- **Added:** `NoVNC` tunnel integration allowing live human intervention for captchas and login walls directly inside the containerized browser.
- **Added:** `FlareSolverr` integration proxy for bypassing Cloudflare bot protections heuristically.
- **Added:** Global `ChallengeDetector` utilizing dictionary string mapping against `<title>` tags for bot-wall identification.

## [0.0.1]

- **Initial Release:** Simple HTML web scraping API wrapper built on `BeautifulSoup` and `Trafilatura`.
- **Note:** Excluded the heavy network infrastructure (VNC, FlareSolverr) and fallback loops found in later system versions.
