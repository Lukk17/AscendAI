## MODIFIED Requirements

### Requirement: Coherent browser fingerprint across tiers

Every browser-based tier (Playwright, Patchright, Camoufox, Crawlee, NoVNC) SHALL be configured from a single internally consistent fingerprint set - user agent, locale, timezone, geolocation, and viewport chosen as one coherent group. The group SHALL match the tier's browser family: Chromium tiers use a Chromium group and Camoufox uses a Firefox group. Mismatched combinations (e.g. `en-US` locale with `UTC` timezone, a New York timezone with San Francisco coordinates, or a Chromium user agent in Firefox) SHALL NOT be used.

#### Scenario: Browser context uses a consistent fingerprint

- **WHEN** any browser tier creates a context
- **THEN** its locale, timezone, and geolocation belong to the same coherent fingerprint
- **AND** the user agent's implied platform matches the injected navigator fingerprint

#### Scenario: Replaying a stored session

- **WHEN** a browser tier replays a stored session that recorded its own user agent
- **THEN** that recorded user agent is used instead of the fingerprint's default, so the replayed session stays coherent with the identity that earned it

#### Scenario: Camoufox never carries a Chromium identity

- **WHEN** `4b-camoufox` runs for a domain whose stored session recorded a Chromium user agent
- **THEN** the Chromium user agent is not injected into the Camoufox context

### Requirement: Optional proxy egress, disabled by default

The service SHALL support routing fetches through a configurable proxy for all tiers (curl_cffi, FlareSolverr, Playwright, Patchright, Camoufox, Crawlee) via a single proxy abstraction. Proxy support SHALL be disabled by default and enabled only by configuration.

#### Scenario: Proxy not configured

- **WHEN** no proxy is configured
- **THEN** all tiers fetch over the host's direct egress exactly as today

#### Scenario: Proxy configured

- **WHEN** a proxy is configured
- **THEN** each tier routes its outbound fetch through that proxy
