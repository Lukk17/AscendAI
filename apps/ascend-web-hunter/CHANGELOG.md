# Changelog: ascend-web-hunter

All notable changes to the ascend-web-hunter project are documented in this file. The
format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project
adheres to [Semantic Versioning](https://semver.org/). Newest entry on top; the topmost
`## [x.y.z]` version is the current one. The release workflow reads it for the image tag
and to guard against re-publishing an already-released version, so keep it at the top and
bump it before every release. The `version` in `pyproject.toml` is a cosmetic label the
release workflow does not read; if the two ever disagree, this file wins for release
purposes.

## [0.0.5]

### Fixed
- End-to-end spec 6 stripped script blocks with a sed flag GNU sed does not have. The Unix form
  uses perl now.
- End-to-end spec 8 reset Redis only, so the in-process read cache spec 3 fills survived into the
  call under test, and its docker cp path did not resolve from the Bruno collection root. The
  reset primes the clear endpoint first, and the path is relative to the collection root.
- End-to-end spec 10 named the default-profile session key while the request sends the
  e2e-establish profile, which the service forwards, so its reset and cleanup never touched the
  key the run created. The spec, its template and the request comment now name the e2e-establish
  key.
- The MCP specs and templates described the session id as a UUID. The value is a 32 character
  hexadecimal id without hyphens, and the wording now says so.
- The PowerShell form of the MCP specs' JSON-body curl.exe blocks failed on pwsh 7.6.5 with a
  nested brace error and HTTP 400. Those blocks pass the body single-quoted now.
- End-to-end specs 8 and 10 still said both mutate the default-profile key. They name the real
  keys now, and state that spec 8's before-and-after scan of session:* is why the two must not run
  together.
- End-to-end spec 1 claimed each rejection returns in under 200 milliseconds. Bruno measured 325
  to 362 milliseconds on 2026-09-10, so the spec states that range and keeps the 2 second gate.
- The MCP tools/list, MCP web_search, read and session-clear Bruno requests asserted less than
  their specs: an envelope with any result or error, any object with a status key, and a clear
  without its cache count. They assert the tool schemas spec 4 lists, the 1 to 3 result entries
  with title, http(s) url and content spec 5 lists, the url, success status, content length and
  canary phrase spec 3 lists, and the four session-clear fields spec 8 lists.
- End-to-end spec 8's own Concurrency section said it was safe to run in parallel with everything
  else in the suite, contradicting that same section's test 10 conflict and the suite README's
  test 3 conflict. It now names both.
- The version in pyproject.toml, AGENTS.md and the constraints document lagged this changelog at
  0.0.3. All three say 0.0.5.

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
