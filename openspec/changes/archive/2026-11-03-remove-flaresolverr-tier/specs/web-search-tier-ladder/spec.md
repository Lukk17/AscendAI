## MODIFIED Requirements

### Requirement: Ladder order with two patched-browser tiers

ascend-web-hunter SHALL escalate a read through `1-beautifulsoup`, `2-trafilatura`, `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` (only while enabled), `5-crawlee_adaptive` and `6-novnc`, in that order. Every public tier value from ADR-011 except the removed `3-flaresolverr` SHALL keep its name and meaning. `4a-patchright` and `4b-camoufox` SHALL be accepted as caller-selected starting tiers on REST and MCP. No tier SHALL need a paid external service.

#### Scenario: Patchright blocked escalates to Camoufox

- **WHEN** a read is blocked at `4-playwright_stealth` and at `4a-patchright`
- **THEN** the read runs at `4b-camoufox`
- **AND** if `4b-camoufox` returns accepted content the read answers with it

#### Scenario: Existing tier value still works

- **WHEN** a caller passes `tier` `4-playwright_stealth`
- **THEN** the chain starts at the Playwright tier exactly as before this change

#### Scenario: The ladder goes from trafilatura straight to the browser tiers

- **WHEN** a read is blocked at `1-beautifulsoup` and at `2-trafilatura`
- **THEN** the next tier that runs is `4-playwright_stealth`

## REMOVED Requirements

### Requirement: FlareSolverr is disabled by default for one release

**Reason**: The FlareSolverr tier, `FLARESOLVERR_ENABLED` and `FLARESOLVERR_URL` are deleted. A request that selects `3-flaresolverr` is refused by the requirement "The removed FlareSolverr tier value is refused", and readiness has no FlareSolverr component to probe.

**Migration**: A caller that passed `3-flaresolverr` got HTTP 400 `tier_disabled` while the tier was disabled, and now gets HTTP 400 with the validation code for a value outside the allowed set. A caller still passing it stops passing it.

## ADDED Requirements

### Requirement: The removed FlareSolverr tier value is refused

`3-flaresolverr` SHALL NOT be an accepted tier value after the FlareSolverr tier is deleted. A request that selects it
SHALL be refused as any value outside the allowed set is refused: with HTTP 400 on REST, as an RFC 7807 problem body
with the validation code of the shared library, and as an invalid argument on MCP, and no tier SHALL run. The value
SHALL never be given to another tier, and no tier SHALL take the number 3.

#### Scenario: Caller selects the removed tier over REST

- **WHEN** a caller passes `tier` `3-flaresolverr` to `POST /api/v2/web/read`
- **THEN** the answer is HTTP 400 with media type `application/problem+json`, `code` `validation` and a `traceId` of 32 lower case hex characters
- **AND** no tier runs

#### Scenario: Caller selects the removed tier over MCP

- **WHEN** a caller passes `tier` `3-flaresolverr` to the `web_read` tool
- **THEN** the tool refuses the argument as a value outside the allowed set
- **AND** no tier runs

#### Scenario: No FlareSolverr anywhere in the running stack

- **WHEN** the stack runs after this change
- **THEN** `/ready` reports no FlareSolverr component and no `flaresolverr` container runs
