# web-search-antibot-evasion Specification

## Purpose

Defines how ascend-web-hunter presents itself to a target site's anti-bot defences: one internally consistent browser fingerprint shared by every browser tier, an optional and off-by-default proxy egress seam wired into all four fetch tiers, and the deliberate absence of any service-side request throttling, which is left to the deployment stack.

## Requirements

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

The service SHALL support routing fetches through a configurable proxy for all tiers (curl_cffi, Playwright, Patchright, Camoufox, Crawlee) via a single proxy abstraction. Proxy support SHALL be disabled by default and enabled only by configuration.

#### Scenario: Proxy not configured

- **WHEN** no proxy is configured
- **THEN** all tiers fetch over the host's direct egress exactly as today

#### Scenario: Proxy configured

- **WHEN** a proxy is configured
- **THEN** each tier routes its outbound fetch through that proxy

#### Scenario: Crawl proxy used only by crawls

- **WHEN** `CRAWL_PROXY_URL` is set and a crawl job and a single read run
- **THEN** the crawl job's fetches go through the crawl proxy
- **AND** the single read does not

### Requirement: No outbound self-throttling, and inbound limits only per caller

The service SHALL NOT impose per-domain rate limiting or self-throttling on the outbound fetches of single reads. Throughput control of those fetches is delegated to the deployment stack. The only request limit the service applies to callers SHALL be the inbound per-caller limit of `python-service-platform`, read from settings. Crawl jobs are the one exception to the outbound rule: they SHALL apply the per-domain crawl delay and concurrency cap of the crawl frontier.

#### Scenario: Rapid successive reads within the caller's limit

- **WHEN** many read requests are issued in quick succession and stay within the caller's configured limit
- **THEN** the service does not delay, queue, or reject them for rate-limiting reasons

#### Scenario: Reads of one domain are not throttled

- **WHEN** many reads of pages on the same domain arrive within the callers' limits
- **THEN** the service fetches each of them without waiting for an earlier fetch of that domain

#### Scenario: A caller over its limit

- **WHEN** one caller sends more read requests than its configured limit allows in the window
- **THEN** the next request answers HTTP 429 with code `rate_limited`

#### Scenario: Crawl politeness does not slow single reads

- **WHEN** a crawl job is throttling its fetches to one domain and a single read for that domain arrives
- **THEN** the single read is not delayed by the crawl's throttle
