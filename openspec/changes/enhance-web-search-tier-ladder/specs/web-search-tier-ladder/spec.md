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

The `3-flaresolverr` tier SHALL run only when `FLARESOLVERR_ENABLED` is true, and the default SHALL be false. While it is false the ladder SHALL skip it, readiness SHALL NOT probe it, and a request that selects it SHALL be refused with HTTP 409 on REST, as a problem body with `code` `tier_disabled`, and a tool error on MCP that starts with `tier_disabled: `, naming the disabled tier.

#### Scenario: Caller selects the disabled tier

- **WHEN** `FLARESOLVERR_ENABLED` is false and a caller passes `tier` `3-flaresolverr`
- **THEN** the request is refused with HTTP 409, `code` `tier_disabled` and a `detail` naming the disabled tier
- **AND** no tier runs

#### Scenario: Readiness ignores a disabled FlareSolverr

- **WHEN** `FLARESOLVERR_ENABLED` is false and `FLARESOLVERR_URL` is unreachable
- **THEN** `/ready` reports ready

### Requirement: A caller who selects the switched-off Camoufox tier is refused with 409

The `4b-camoufox` tier SHALL run only while `CAMOUFOX_ENABLED` is true, and the default SHALL be true. While it is false the ladder SHALL skip it, and a request that selects `4b-camoufox` as its `tier` SHALL be refused with HTTP 409 on REST, as a problem body with `code` `tier_disabled` and a `detail` naming the tier `4b-camoufox`, and with a tool error on MCP that starts with `tier_disabled: ` and names the same tier. No tier SHALL run for that request.

#### Scenario: Caller selects Camoufox while it is switched off on REST

- **WHEN** `CAMOUFOX_ENABLED` is false and a REST caller reads a page with `tier` `4b-camoufox`
- **THEN** the answer is HTTP 409 with `code` `tier_disabled` and a `detail` that names `4b-camoufox`
- **AND** no tier runs

#### Scenario: Caller selects Camoufox while it is switched off on MCP

- **WHEN** `CAMOUFOX_ENABLED` is false and an MCP caller calls `web_read` with `tier` `4b-camoufox`
- **THEN** the tool fails with a text that starts with `tier_disabled: ` and names `4b-camoufox`

### Requirement: Every browser request passes the shared URI guard before the browser connects

Every browser tier (`4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive` and the browser of
`6-novnc`) SHALL check every page load, every redirect hop and every subresource request against `check_fetch_uri` of
the `ascend-python-common` library before the browser connects, through a route handler installed on the browser
context before the first navigation, with service workers blocked. A request the guard refuses SHALL be aborted with no
connection to its address. A redirect SHALL reach the browser as a new request that passes the same check. A refused
main navigation SHALL end the read with code `unsafe_uri` (HTTP 400 on REST, a tool error on MCP). A refused subresource
SHALL be blocked while the page continues. Owner decision 66 of 2026-10-04.

#### Scenario: A public page that redirects the browser to a private address is refused

- **WHEN** a read of a public page runs in a browser tier and the page answers with a redirect to `http://169.254.169.254/latest/meta-data/`
- **THEN** the browser sends no request to `169.254.169.254`
- **AND** the read answers code `unsafe_uri`

#### Scenario: A page that loads a subresource from a private address

- **WHEN** a public page in a browser tier includes an image from `http://10.0.0.5/pixel.png`
- **THEN** that request is aborted with no connection to `10.0.0.5`
- **AND** the page is still read and returned

#### Scenario: A script navigation to a private address is refused

- **WHEN** a public page in a browser tier sets `window.location` to `http://127.0.0.1:6379/`
- **THEN** the browser sends no request to `127.0.0.1` and the read answers code `unsafe_uri`

#### Scenario: A private target is refused whatever tier the caller selects

- **WHEN** a caller reads a URL whose host resolves to a private address and passes `tier` `1-beautifulsoup`, `2-trafilatura`, `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` or `5-crawlee_adaptive`
- **THEN** each REST answer is HTTP 400 with media type `application/problem+json`, `code` `unsafe_uri` and a `traceId` of 32 lower case hex characters
- **AND** no request reaches the private address

### Requirement: Per-domain tier memory with decay

ascend-web-hunter SHALL store in Redis, per registrable domain, the tier that last returned accepted content, and SHALL start the next read for that domain at that tier. The record SHALL expire after `TIER_MEMORY_TTL_SECONDS`, after which the read starts at the beginning of the ladder. A caller-selected `tier` and a stored session's producer SHALL take precedence over the memory. A Redis failure SHALL NOT fail the read.

#### Scenario: Remembered tier is the start point

- **WHEN** a domain last succeeded at `4b-camoufox` within the TTL and a new read for it begins without a `tier`
- **THEN** the read starts at `4b-camoufox`

#### Scenario: The remembered tier is stored per domain

- **WHEN** a read without a `tier` succeeds at a browser tier
- **THEN** Redis holds `tier_memory:<registrable domain>` naming that tier with a TTL no larger than `TIER_MEMORY_TTL_SECONDS`
- **AND** the next read of that domain answers with the same tier as its `mode`

#### Scenario: Memory expires

- **WHEN** `TIER_MEMORY_TTL_SECONDS` has passed since the last record for a domain
- **THEN** the next read starts at `1-beautifulsoup`

#### Scenario: Redis unavailable

- **WHEN** the tier memory cannot reach Redis
- **THEN** the read climbs the full ladder and a WARNING is logged
