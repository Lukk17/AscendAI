## ADDED Requirements

### Requirement: Coherent browser fingerprint across tiers

Every browser-based tier (Playwright, Crawlee, NoVNC) SHALL be configured from a single internally consistent fingerprint set — user agent, locale, timezone, geolocation, and viewport chosen as one coherent group. Mismatched combinations (e.g. `en-US` locale with `UTC` timezone, or a New York timezone with San Francisco coordinates) SHALL NOT be used.

#### Scenario: Browser context uses a consistent fingerprint

- **WHEN** any browser tier creates a context
- **THEN** its locale, timezone, and geolocation belong to the same coherent fingerprint
- **AND** the user agent's implied platform matches the injected navigator fingerprint

### Requirement: Optional proxy egress, disabled by default

The service SHALL support routing fetches through a configurable proxy for all tiers (curl_cffi, FlareSolverr, Playwright, Crawlee) via a single proxy abstraction. Proxy support SHALL be disabled by default and enabled only by configuration.

#### Scenario: Proxy not configured

- **WHEN** no proxy is configured
- **THEN** all tiers fetch over the host's direct egress exactly as today

#### Scenario: Proxy configured

- **WHEN** a proxy is configured
- **THEN** each tier routes its outbound fetch through that proxy

### Requirement: No service-side request rate limiting

The service SHALL NOT impose per-domain or per-caller request rate limiting or self-throttling. Throughput control is delegated to the deployment stack.

#### Scenario: Rapid successive reads

- **WHEN** many read requests are issued in quick succession
- **THEN** the service does not delay, queue, or reject them for rate-limiting reasons
