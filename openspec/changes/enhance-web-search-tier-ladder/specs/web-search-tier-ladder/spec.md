## ADDED Requirements

### Requirement: Ladder order with two patched-browser tiers

ascend-web-hunter SHALL escalate a read through `1-beautifulsoup`, `2-trafilatura`, `3-flaresolverr` (only while enabled), `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` (only while enabled), `5-crawlee_adaptive` and `6-novnc`, in that order. Every public tier value from ADR-011 SHALL keep its name and meaning. `4a-patchright` and `4b-camoufox` SHALL be accepted as caller-selected starting tiers on REST and MCP. No tier SHALL need a paid external service.

#### Scenario: Patchright blocked escalates to Camoufox

- **WHEN** a read is blocked at `4-playwright_stealth` and at `4a-patchright`
- **THEN** the read runs at `4b-camoufox`
- **AND** if `4b-camoufox` returns accepted content the read answers with it

#### Scenario: Existing tier value still works

- **WHEN** a caller passes `tier` `4-playwright_stealth`
- **THEN** the chain starts at the Playwright tier exactly as before this change

### Requirement: FlareSolverr is disabled by default for one release

The `3-flaresolverr` tier SHALL run only when `FLARESOLVERR_ENABLED` is true, and the default SHALL be false. While it is false the ladder SHALL skip it, readiness SHALL NOT probe it, and a request that selects it SHALL be refused with HTTP 400 on REST and a tool error on MCP, naming the disabled tier.

#### Scenario: Caller selects the disabled tier

- **WHEN** `FLARESOLVERR_ENABLED` is false and a caller passes `tier` `3-flaresolverr`
- **THEN** the request is refused with HTTP 400 naming the disabled tier
- **AND** no tier runs

#### Scenario: Readiness ignores a disabled FlareSolverr

- **WHEN** `FLARESOLVERR_ENABLED` is false and `FLARESOLVERR_URL` is unreachable
- **THEN** `/ready` reports ready

### Requirement: Per-domain tier memory with decay

ascend-web-hunter SHALL store in Redis, per registrable domain, the tier that last returned accepted content, and SHALL start the next read for that domain at that tier. The record SHALL expire after `TIER_MEMORY_TTL_SECONDS`, after which the read starts at the beginning of the ladder. A caller-selected `tier` and a stored session's producer SHALL take precedence over the memory. A Redis failure SHALL NOT fail the read.

#### Scenario: Remembered tier is the start point

- **WHEN** a domain last succeeded at `4b-camoufox` within the TTL and a new read for it begins without a `tier`
- **THEN** the read starts at `4b-camoufox`

#### Scenario: Memory expires

- **WHEN** `TIER_MEMORY_TTL_SECONDS` has passed since the last record for a domain
- **THEN** the next read starts at `1-beautifulsoup`

#### Scenario: Redis unavailable

- **WHEN** the tier memory cannot reach Redis
- **THEN** the read climbs the full ladder and a WARNING is logged
