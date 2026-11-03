## Why

ascend-web-hunter escalates a read through six public tiers, named in ADR-011: `1-beautifulsoup`, `2-trafilatura`,
`3-flaresolverr`, `4-playwright_stealth`, `5-crawlee_adaptive` and `6-novnc`. The only browser tiers are vanilla
Playwright with stealth patches and Crawlee, and both are detected by hardened anti-bot vendors. FlareSolverr sits in
the middle of the ladder as a separate container whose only job is to clear a Cloudflare challenge, it is barely
maintained, and its success rate keeps falling. The service also forgets what worked: every read of a hard domain
climbs the whole ladder again.

This change was split out of `enhance-web-search-extraction-and-tiers` on 2026-10-01. That folder now holds only the
structured-extraction work.

## What Changes

- Two new automated browser tiers, both free and self-hosted:
  - `4a-patchright`: Patchright, a drop-in replacement for the Playwright API that drives a patched Chromium.
  - `4b-camoufox`: Camoufox, a hardened Firefox driven through the Playwright API, tried when `4a-patchright` is
    detected or fails.
- The ladder order becomes `1-beautifulsoup`, `2-trafilatura`, `3-flaresolverr` (only when enabled),
  `4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive`, `6-novnc`. Every existing public tier
  value keeps its name and meaning, so a caller that passes `tier` today is unaffected. The two new values are added
  to the `TierName` Literal in `src/reader/web_reader.py` and accepted by the REST `tier` field and the MCP `web_read`
  `tier` argument.
- FlareSolverr stays for one release behind `FLARESOLVERR_ENABLED`, default `false`. When it is false the
  `3-flaresolverr` tier is skipped by the ladder, a caller that names it gets HTTP 409 `tier_disabled` (owner answers
  94.6 and 95.3 of 2026-10-08), readiness does not probe it,
  and a session it produced earlier is replayed by the browser tiers. Removing FlareSolverr and every reference to it
  is the follow-up change `remove-flaresolverr-tier`, written out in full and not started.
- Per-domain tier memory: the tier that last succeeded for a registrable domain is kept in Redis and the next read
  starts there, decaying back to the start of the ladder after `TIER_MEMORY_TTL_SECONDS`. A caller-selected `tier`
  (ADR-011) always wins over the memory.
- Every browser tier checks every page load, redirect hop and subresource request against the shared URI guard of
  `add-ascend-python-common` before the browser connects, through Playwright request interception, and blocks a
  request that fails (owner decision 66 of 2026-10-04, design D6). FlareSolverr needs nothing, because it is off here
  and removed by `remove-flaresolverr-tier`.
- No CAPTCHA solver is added. The owner dropped the local solver on 2026-10-01. A CAPTCHA still goes to the human at
  `6-novnc`.

## Capabilities

### New Capabilities

- `web-search-tier-ladder`: the ladder order, the two new tiers, the FlareSolverr flag, and per-domain tier memory
  with decay.

### Modified Capabilities

- `web-search-authenticated-sessions`: session replay covers the two new tiers, FlareSolverr persists and replays
  cookies only while it is enabled, and a session produced by `3-flaresolverr` goes to the browser tiers when the flag
  is off.
- `web-search-antibot-evasion`: the coherent fingerprint and the proxy seam cover the two new tiers. Camoufox brings
  its own Firefox fingerprint, so coherence is required per browser family.

## Dependencies and Build Order

Build order (owner build order of 2026-10-04, which supersedes the earlier orders, among them the owner order of
2026-10-01): build group 2 (web-hunter), position 5. It needs `detect-challenge-walls-in-any-language` (position 4),
because the two new tiers pass their response to `ChallengeDetector.assess` and raise on its verdict, exactly like the
existing tiers after that change. It also needs `add-ascend-python-common` (position 1, the URI guard and its
`ALLOWED_PRIVATE_HOSTS` setting) and `add-python-runtime-upgrades` (position 2), so the MCP tools and tests of this
change are written against FastMCP 4 and every test that uses `fastmcp.Client` names its protocol era
(`add-python-runtime-upgrades` D9). Its e2e spec uses the shared fake site of `add-web-search-scraping-e2e` (build
group 1). `enhance-web-search-extraction-and-tiers` (position 6) follows it, and `remove-flaresolverr-tier`
(position 7) builds on this change having shipped for one release.

## Impact

- `apps/ascend-web-hunter/pyproject.toml`: `patchright` and `camoufox` pinned to exact versions.
- `apps/ascend-web-hunter/Dockerfile`: the Patchright Chromium build and the Camoufox Firefox build fetched at image
  build time, never at request time.
- `apps/ascend-web-hunter/src/reader/strategies/patchright_strategy.py` and `camoufox_strategy.py`: new.
- `apps/ascend-web-hunter/src/reader/web_reader.py`: `TierName`, the ladder list, tier memory lookup and update.
- `apps/ascend-web-hunter/src/reader/tier_memory.py`: new, the Redis store.
- `apps/ascend-web-hunter/src/reader/browser_guard.py`: new, the guarded route handler of every browser tier, and
  `playwright_strategy.py`, `crawlee_strategy.py` and `novnc_strategy.py` install it.
- `apps/ascend-web-hunter/src/config/config.py`: `FLARESOLVERR_ENABLED`, `TIER_MEMORY_TTL_SECONDS`,
  `CAMOUFOX_ENABLED`, and `NETWORKIDLE_POLL_MS` and `SCROLL_PAUSE_MS` (the two waits `playwright_strategy.py` holds as
  code today, owner answer 100.3 of 2026-10-09), each passed by both compose files as `${VAR:-default}` with the same default and added to both
  `.env.example` files and the bundle README by the sync rule (owner rule 98 of 2026-10-08).
- `apps/ascend-web-hunter/src/api/readiness.py` and `src/config/startup_banner.py`: FlareSolverr only when enabled.
- `apps/ascend-web-hunter/src/api/rest/rest_endpoints.py` and `src/api/mcp/mcp_server.py`: the new tier values and the
  409 `tier_disabled` for a disabled tier.
- e2e: a new automated spec, `<N>-tier-ladder-and-guard` (next free number at implementation time), that proves the
  URL guard in every tier against the shared e2e fake site, the two new tiers and the tier memory (the disabled
  FlareSolverr tier is proven by unit tests, owner answer 91.3 of 2026-10-08), its Bruno folder `docs/api/request/AscendAI/web-hunter/testing/tier-ladder/`, a best-effort spec 7 row
  for `nowsecure.nl`, and its place in `docs/E2E_RUN_SCENARIOS.md`.
- Docs: `apps/ascend-web-hunter/AGENTS.md`, `README.md`, `docs/configuration.md`, ADR-015 for the ladder, an
  amendment to ADR-011 listing the two new public values, and a CHANGELOG entry with a version bump from 0.0.10 to 0.0.11.

## Relevant Skills

- `/python-patterns`
- `/tdd-workflow`
- `/api-design`
- `/docker-patterns`
- `/security-review`
- `/architecture-decision-records`
