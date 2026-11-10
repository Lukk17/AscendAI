# ADR-018: The FlareSolverr tier is removed

## Status

Accepted, 2026-10-20

## Context

[ADR-015](ADR-015-patched-browser-tiers-and-tier-memory.md) kept the
`3-flaresolverr` tier for one release behind `FLARESOLVERR_ENABLED`
(default `false`) while the patched-browser tiers `4a-patchright` and
`4b-camoufox` took over its work. The owner decided on 2026-10-04
(decision 65.12 of `remove-flaresolverr-tier` task 1.2) that FlareSolverr
is then removed with every reference. One release with the flag off is
the evidence that nothing needs it: had an operator needed to turn it
on, this change would not have started.

## Decision

### D1, the tier, its settings and its container are deleted

`src/reader/strategies/flaresolverr_strategy.py` is deleted.
`3-flaresolverr` leaves `TierName` and `TIER_ORDER` in
`src/reader/web_reader.py`, `FLARESOLVERR_URL` and `FLARESOLVERR_ENABLED`
leave `src/config/config.py`, and the FlareSolverr probe, banner entry,
circuit breaker, proxy branch and cookie producer constant
(`PRODUCED_BY_FLARESOLVERR`) leave with them. The `flaresolverr` service
leaves both compose files with its port, `depends_on` entries and
environment lines, and the `FLARESOLVERR_HOST_PORT` setting of
`fix-linux-docker-host-access` task 10.2 leaves with it. The fixed
container names drop from four to three.

### D2, the removed value is refused and never reused

`3-flaresolverr` leaves the accepted tier values like any value that
never existed. A request that passes it gets the normal refusal for a
value outside the allowed set: HTTP 400 with the problem body code
`validation` on REST, and the invalid-argument refusal on MCP. No tier
runs. No future tier takes the name or the number 3.

### D3, no compatibility with old session records

Session records the FlareSolverr tier stored before this change get no
special handling and no migration. The owner decided on 2026-10-02
(confirmed by owner answer 73.1 of 2026-10-06) that there is no existing
data to keep, and the owner clears stored sessions at will. This holds
only until the first real customer deployment.

## Consequences

- A stored session of any producer starts the read at the browser
  tiers. The producer-aware replay of
  [ADR-010](ADR-010-producer-aware-session-replay.md) keeps only its
  browser rule.
- The `tier_disabled` problem code (status 409) stays: `4b-camoufox`
  still raises it while `CAMOUFOX_ENABLED` is false.
- This change ships as ascend-web-hunter 0.0.13, one patch step after
  0.0.12 of `enhance-web-search-extraction-and-tiers`.

## Related

- [ADR-001](ADR-001-multi-tier-extraction-strategy.md), amended: the
  ladder no longer lists `3-flaresolverr`.
- [ADR-002](ADR-002-cloudflare-cookie-persistence-redis.md), amended:
  FlareSolverr is no longer a session writer.
- [ADR-005](ADR-005-strategy-budget-and-singleton-chromium.md),
  amended: the FlareSolverr timeout rule leaves with the tier.
- [ADR-006](ADR-006-proxy-seam-and-fingerprint.md), amended: the
  FlareSolverr proxy payload branch is deleted.
- [ADR-010](ADR-010-producer-aware-session-replay.md), amended: only
  the browser rule survives.
- [ADR-011](ADR-011-caller-selectable-starting-tier.md), amended:
  `3-flaresolverr` is no longer an accepted value.
- [ADR-012](ADR-012-connect-time-address-pinning.md), amended:
  FlareSolverr leaves the out-of-process tier list.
- [ADR-015](ADR-015-patched-browser-tiers-and-tier-memory.md): kept
  FlareSolverr behind the flag this change removes.
