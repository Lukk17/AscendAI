## MODIFIED Requirements

### Requirement: Optional proxy egress, disabled by default

The service SHALL support routing fetches through a configurable proxy for all tiers (curl_cffi, Playwright, Patchright, Camoufox, Crawlee) via a single proxy abstraction. Proxy support SHALL be disabled by default and enabled only by configuration. The same abstraction SHALL offer a separate customer-supplied crawl proxy, `CRAWL_PROXY_URL`, used only by crawl jobs and never by single reads. The service SHALL NOT run, host or resell a proxy.

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
