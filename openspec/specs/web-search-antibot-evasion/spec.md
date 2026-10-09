# web-search-antibot-evasion Specification

## Purpose

Defines how ascend-web-hunter presents itself to a target site's anti-bot defences: one internally consistent browser fingerprint shared by every browser tier, an optional and off-by-default proxy egress seam wired into all four fetch tiers, and the deliberate absence of any service-side request throttling, which is left to the deployment stack.

## Requirements

### Requirement: Coherent browser fingerprint across tiers

Every browser-based tier (Playwright, Crawlee, NoVNC) SHALL be configured from a single internally consistent fingerprint set - user agent, locale, timezone, geolocation, and viewport chosen as one coherent group. Mismatched combinations (e.g. `en-US` locale with `UTC` timezone, or a New York timezone with San Francisco coordinates) SHALL NOT be used.

#### Scenario: Browser context uses a consistent fingerprint

- **WHEN** any browser tier creates a context
- **THEN** its locale, timezone, and geolocation belong to the same coherent fingerprint
- **AND** the user agent's implied platform matches the injected navigator fingerprint

#### Scenario: Replaying a stored session

- **WHEN** a browser tier replays a stored session that recorded its own user agent
- **THEN** that recorded user agent is used instead of the fingerprint's default, so the replayed session stays coherent with the identity that earned it

### Requirement: Optional proxy egress, disabled by default

The service SHALL support routing fetches through a configurable proxy for all tiers (curl_cffi, FlareSolverr, Playwright, Crawlee) via a single proxy abstraction. Proxy support SHALL be disabled by default and enabled only by configuration.

#### Scenario: Proxy not configured

- **WHEN** no proxy is configured
- **THEN** all tiers fetch over the host's direct egress exactly as today

#### Scenario: Proxy configured

- **WHEN** a proxy is configured
- **THEN** each tier routes its outbound fetch through that proxy

### Requirement: No outbound self-throttling, and inbound limits only per caller

The service SHALL NOT impose per-domain rate limiting or self-throttling on its outbound fetches. Throughput control of outbound fetches is delegated to the deployment stack. The only request limit the service applies SHALL be the inbound per-caller limit of `python-service-platform`, read from settings.

#### Scenario: Rapid successive reads within the caller's limit

- **WHEN** many read requests are issued in quick succession and stay within the caller's configured limit
- **THEN** the service does not delay, queue, or reject them for rate-limiting reasons

#### Scenario: Reads of one domain are not throttled

- **WHEN** many reads of pages on the same domain arrive within the callers' limits
- **THEN** the service fetches each of them without waiting for an earlier fetch of that domain

#### Scenario: A caller over its limit

- **WHEN** one caller sends more read requests than its configured limit allows in the window
- **THEN** the next request answers HTTP 429 with code `rate_limited`
