# ADR-015: Patched browser tiers and per-domain tier memory

## Status

Accepted, 2026-10-19

## Amendment, 2026-10-20 (remove-flaresolverr-tier)

D2 no longer applies: the FlareSolverr tier, `FLARESOLVERR_ENABLED`,
`FLARESOLVERR_URL` and the `flaresolverr` container are removed. A
request that selects `3-flaresolverr` is now refused as a value outside the
allowed set, not with `tier_disabled`. `tier_disabled` (409) stays for the
switched-off Camoufox tier. See [ADR-018](ADR-018-flaresolverr-tier-removed.md).

## Amendment, 2026-11-06 (tier memory write rule)

Owner decision: D3's overwrite rule changes. The memory holds the tier that
last returned accepted content, whichever ladder position it has, so a
success at a dearer tier replaces a cheaper memory too. Only a read with no
caller `tier` and with `heavy_mode` off writes it, because the start point of
any other read was chosen by the caller, not found by the ladder. The
consequence that a cheaper success overwrites a dearer memory at once still
holds, as one case of the new rule. The requirement is "Per-domain tier
memory with decay" in `openspec/specs/web-search-tier-ladder/spec.md`.

## Amendment, 2026-11-07 (security fix 19)

D4 changes on a pass: the handler no longer uses `route.fetch`. It sends the request through the pinned
curl_cffi fetch to the address the guard checked and hands the answer back with `route.fulfill`. A redirected
navigation is aborted and its frame navigates to the checked and pinned next hop, so the page shows the final
address, and a redirected subresource is followed inside the handler. Every page WebSocket is closed, and every
browser launches with a refusing proxy for the connections routing does not see. The residual DNS rebinding window of D4 is
closed. The full decision and its measurements are the 2026-11-07 amendment of
[ADR-012](ADR-012-connect-time-address-pinning.md).

## Amendment, 2026-11-09

The 2026-11-07 fetch is replaced. On a pass the handler continues the request with `route.continue_()`, and the browser
connects through the pinned tunnel of `src/reader/pinned_tunnel.py`, the only way out it has, so its own TLS reaches the
site. The human NoVNC window launches Patchright, like the `4a-patchright` tier. The full decision and its measurements
are the 2026-11-09 amendment of [ADR-012](ADR-012-connect-time-address-pinning.md).

## Context

The ladder of [ADR-001](ADR-001-multi-tier-extraction-strategy.md) climbs from cheap static tiers to a
single headed-stealth Chromium (`4-playwright_stealth`) and then to Crawlee and NoVNC. Two gaps stayed open.
First, the only browser rung before the heavy Crawlee tier is stock Playwright with `playwright-stealth`,
so a site that fingerprints that combination leaves one expensive jump. Second, the ladder remembers
nothing: a domain that only renders in a browser pays the cheap tiers on every read before reaching the
tier that works.

## Decision

### D1, two patched browser tiers between Playwright and Crawlee

`4a-patchright` and `4b-camoufox` sit after `4-playwright_stealth` and before `5-crawlee_adaptive` in
`TIER_ORDER` in `src/reader/web_reader.py`, and the order of that tuple is the ladder order, never a
sort on the name. The public values of ADR-011 keep their names and meanings; the new values are
accepted as caller-selected starting tiers on REST and MCP. Patchright replays the Chromium fingerprint
family, Camoufox draws its own Firefox identity per context and never takes an injected user agent, so a
stored Chromium user agent cannot contradict the drawn fingerprint. Both tiers reuse the Playwright
tier's waits and scroll values (`DYNAMIC_CONTENT_WAIT`, `SCROLL_ITERATIONS`, `SCROLL_STEP_PX`,
`NETWORKIDLE_POLL_MS`, `SCROLL_PAUSE_MS`) from the same settings, and add no timeout of their own. The
browser binaries are fetched at image build time, pinned to the `pyproject.toml` versions.

### D2, FlareSolverr behind a disabled-by-default flag for one release

`FLARESOLVERR_ENABLED` (default `false`) removes `3-flaresolverr` from the ladder while off. A request
that selects it is refused with HTTP 409 and problem code `tier_disabled`, the same status the
switched-off Camoufox tier answers, because one problem code has one status. Readiness does not probe
`FLARESOLVERR_URL` while the flag is off, and a stored session produced by `3-flaresolverr` is routed
to the browser tiers. The container stays in both compose files for this release so an operator can
turn the flag on without a new image.

### D3, per-domain tier memory in Redis

`src/reader/tier_memory.py` stores the tier that last returned accepted content under
`tier_memory:{registrable_domain}` with TTL `TIER_MEMORY_TTL_SECONDS` (default 86400, minimum 60).
The next read for that domain starts at the remembered tier. A caller `tier` and a stored session's
producer both outrank the memory, a success at a cheaper tier overwrites a dearer memory, and a Redis
failure only logs and climbs the full ladder, it never fails the read.

### D4, every browser request passes the shared URI guard before the browser connects

`src/reader/browser_guard.py` installs one guarded route handler on every browser context, with
`service_workers="block"`, before the first navigation: the ad blocklist first, then `check_fetch_uri`
with the web-hunter policy, `route.abort("blockedbyclient")` on a refusal and
`route.fetch(max_redirects=0)` plus `route.fulfill(response=...)` on a pass, so every redirect hop
re-enters the handler and is checked before anything connects to it. `data:` and `blob:` pass, any
other scheme is refused, and a refused main navigation raises `UnsafeUriError`. The Crawlee tier
installs the same handler in its pre-navigation hook and passes its seed URL through `check_fetch_uri`
before the crawler runs. The residual DNS rebinding window of `route.fetch` stays open: the fetch
resolves the host again, so the connect-time address pinning of ADR-012 is not applied inside the
browser path, and that window is accepted for the same reason ADR-012 accepted it.

## Consequences

### Positive

- A site that blocks the Playwright tier has two more free rungs before the expensive tiers.
- Repeat reads of a browser-only domain start where the last read succeeded.
- Every browser subresource, redirect hop and WebSocket passes the guard; a refused navigation
  answers `unsafe_uri` instead of opening a connection.

### Negative

- The image grows by two browser builds, measured in the CHANGELOG.
- Camoufox is heavier than Chromium and runs only after Patchright fails, or not at all with
  `CAMOUFOX_ENABLED=false`.
- Tier memory can pin a domain to a slow tier for one TTL after a single bad day; a cheaper
  success overwrites it at once.

## Related

- `src/reader/web_reader.py` - `TierName`, `TIER_ORDER`, `_drop_disabled_tiers`.
- `src/reader/strategies/patchright_strategy.py` - the `4a-patchright` tier.
- `src/reader/strategies/camoufox_strategy.py` - the `4b-camoufox` tier.
- `src/reader/browser_guard.py` - the guarded route handler and the WebSocket check.
- `src/reader/tier_memory.py` - the per-domain tier memory.
- [ADR-011](ADR-011-caller-selectable-starting-tier.md), whose values this change extends.
- [ADR-012](ADR-012-connect-time-address-pinning.md), whose pinning stops at the browser path.
