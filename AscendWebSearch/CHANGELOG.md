# Changelog

All notable changes to the AscendWebSearch project will be documented in this file.

## [0.1.0]

- **Refactored:** Unified scraping strategies into a cohesive Orchestrator loop.
- **Refactored:** Enforced identical `ContentValidator` rule boundaries (with default of 10 words) across `read` and `read_with_links` HTTP flows.
- **Added:** Global HTTP 428 Precondition Required exception mapping natively into FastAPI.
- **Improved:** Re-architected NoVNC tracking to utilize an unconditional, persistent Redis-backed 5-second polling loop to prevent heuristic misfires.

## [0.0.2]

- **Added:** Complete network stack including Playwright `headless=False` browser execution rendering inside Docker via `fluxbox` and `Xvfb`.
- **Added:** `NoVNC` tunnel integration allowing live human intervention for captchas and login walls directly inside the containerized browser.
- **Added:** `FlareSolverr` integration proxy for bypassing Cloudflare bot protections heuristically.
- **Added:** Global `ChallengeDetector` utilizing dictionary string mapping against `<title>` tags for bot-wall identification.

## [0.0.1]

- **Initial Release:** Simple HTML web scraping API wrapper built on `BeautifulSoup` and `Trafilatura`.
- **Note:** Excluded the heavy network infrastructure (VNC, FlareSolverr) and fallback loops found in later system versions.
