# Changelog: ascend-web-hunter

All notable changes to the ascend-web-hunter project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/). Newest entry on top; the topmost
`## [x.y.z]` version is the current one. The release workflow reads it for the image tag
and to guard against re-publishing an already-released version, so keep it at the top and
bump it before every release. The `version` in `pyproject.toml` is a cosmetic label the
release workflow does not read; if the two ever disagree, this file wins for release
purposes.

## [0.0.4]

### Fixed
- Establishing a session persisted nothing. An earlier expiry fix had added a condition requiring
  a page to be seen blocked at least once before the monitor would treat it as cleared, and for a
  site that is never challenged, which is exactly the case session establishment exists for, that
  can never become true. The condition is gone, so an ordinary never-challenged page records a
  session again. A genuinely blocked page is still not treated as accepted.
- A session record with an empty cookie jar was reported as a live authenticated session with a
  fortnight of life remaining, because an empty jar carries no expiry and the remaining time fell
  back to the configured ceiling. One such record pushed every later read of that domain onto the
  heavier browser tiers for no benefit. The emptiness check now lives in the single remaining-time
  helper that the status endpoint and the tier chooser both read through.

## [0.0.3]

### Added
- Unified scraping strategies into a cohesive Orchestrator loop.
- Enforced identical `ContentValidator` rule boundaries (with default of 10 words) across `read` and `read_with_links` HTTP flows.
- Global HTTP 428 Precondition Required exception mapping natively into FastAPI.
- Re-architected NoVNC tracking to utilize an unconditional, persistent Redis-backed 5-second polling loop to prevent heuristic misfires.
- VNC authentication. `VNC_PASSWORD` is turned into an encrypted x11vnc password file by a new container entrypoint; unset falls back to the previous open desktop with a warning at boot.
- `deploy-standalone/` bundle for running this stack on a host of its own, with pinned images, its own `.env.example` and SearXNG overlay, and no build context.
- Healthchecks on SearXNG and FlareSolverr with `condition: service_healthy` gating, so the service no longer starts against a cold upstream and opens its circuit breaker.
- Resource limits and bounded container logs across the scrapper stack.

### Changed
- SearXNG `secret_key` moved out of the committed settings overlay and into the `SEARXNG_SECRET` environment variable. The previously committed value is public and compromised.
- SearXNG upgraded to `2026.8.14`, FlareSolverr to `v3.5.0`.

Note on numbering: this entry was drafted as `[0.1.0]` while the manifest carried a version that never matched any published image. It is renumbered to `0.0.3` so that the changelog, the manifest and the registry tags all agree. Images `v0.0.1` and `v0.0.2` correspond to the two entries below.

## [0.0.2]

### Added
- Complete network stack including Playwright `headless=False` browser execution rendering inside Docker via `fluxbox` and `Xvfb`.
- `NoVNC` tunnel integration allowing live human intervention for captchas and login walls directly inside the containerized browser.
- `FlareSolverr` integration proxy for bypassing Cloudflare bot protections heuristically.
- Global `ChallengeDetector` utilizing dictionary string mapping against `<title>` tags for bot-wall identification.

## [0.0.1]

### Added
- Simple HTML web scraping API wrapper built on `BeautifulSoup` and `Trafilatura`.

### Note
- Excluded the heavy network infrastructure (VNC, FlareSolverr) and fallback loops found in later system versions.
