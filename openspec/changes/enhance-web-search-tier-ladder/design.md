## Context

The ladder lives in `apps/ascend-web-hunter/src/reader/web_reader.py`. `TierName` is a `Literal` of six public values
(ADR-011), and the strategies sit in `src/reader/strategies/`. Session replay, producer-aware replay (ADR-010),
coherent fingerprints (`src/reader/fingerprint.py`), the proxy seam (`src/proxy/proxy_provider.py`), connect-time
address pinning (ADR-012, `pin_safe_host`), session validation (`session_manager.validate`) and the caller-selected
`tier` and `output_format` are all built and shipped. This change adds to them and rebuilds none of them.

## Goals and Non-Goals

Goals: two stronger free browser tiers, FlareSolverr off by default for one release, and a ladder that remembers what
worked per domain.

Non-Goals: removing FlareSolverr (follow-up `remove-flaresolverr-tier`), any CAPTCHA solver (dropped by the owner on
2026-10-01), any paid proxy or solving service, a headed browser as an automated tier (recorded as a possible
follow-up in `open-several-novnc-windows-at-once`), and anything about extraction.

## Decisions

### D1: New tiers get new public names, old names stay

ADR-011 made the tier values public. Renaming `4-playwright_stealth` would break every caller that passes it. The new
tiers are `4a-patchright` and `4b-camoufox`, placed after `4-playwright_stealth` and before `5-crawlee_adaptive`. The
order of the ladder is the order of the `TIER_ORDER` tuple in `web_reader.py`, never a sort on the name.

Rejected: replacing the Playwright engine inside `4-playwright_stealth` with Patchright. It changes what a public
value means without a new name, and a regression could not be isolated by selecting the old tier.

### D2: FlareSolverr behind a disabled-by-default flag for one release

`FLARESOLVERR_ENABLED` (default `false`). When false: the ladder skips `3-flaresolverr`, a request naming it answers
HTTP 400 with `detail` naming the disabled tier on REST and a `ToolError` on MCP, `readiness.py` does not probe
`FLARESOLVERR_URL`, `startup_banner.py` prints the tier as disabled, and a stored session whose `produced_by` is
`3-flaresolverr` is sent to the browser tiers (its clearance was bound to FlareSolverr's fingerprint and is likely
useless, but its auth cookies may not be). The container stays in both compose files for this release so an operator
can turn the flag on without a new image.

### D3: Per-domain tier memory in Redis

Key `tier_memory:{registrable_domain}` where the domain is `CookieManager.registrable_domain(url)`, value the tier name
that last returned accepted content, TTL `TIER_MEMORY_TTL_SECONDS` (default 86400). The TTL is the decay: when the key
expires the next read starts at the beginning of the ladder again. A success at a cheaper tier than the remembered one
overwrites it. A caller `tier` overrides the memory. A stored session's producer (ADR-010) overrides the memory too,
because a session must be replayed by the tier that earned it. A Redis failure is logged and the read climbs the full
ladder, it never fails the read.

### D4: Camoufox has its own fingerprint family

Camoufox generates a Firefox fingerprint. Injecting the Chromium fingerprint from `fingerprint.py` into it would be the
exact incoherence the antibot spec forbids. The fingerprint group is therefore chosen per browser family, and a stored
session's recorded user agent is replayed only into a tier of the same family.

### D5: Browsers are fetched at build time

The Dockerfile runs the Patchright and Camoufox fetch steps during the image build, pinned to the versions in
`pyproject.toml`. A missing browser binary is a startup error, never a download at request time.

## Risks

- Image size grows by two browser builds. Measured in task 6.3 and recorded in the CHANGELOG.
- Camoufox is heavier than Chromium. It runs only after `4a-patchright` fails, and `CAMOUFOX_ENABLED=false` removes it.
- Tier memory can pin a domain to a slow tier for one TTL after a single bad day. The TTL bounds it, and a cheaper
  success overwrites it at once.
