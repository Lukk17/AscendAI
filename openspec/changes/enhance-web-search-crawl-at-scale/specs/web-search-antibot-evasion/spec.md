## MODIFIED Requirements

### Requirement: Optional proxy egress, disabled by default

The service SHALL support routing fetches through a configurable proxy for all tiers (curl_cffi, FlareSolverr, Playwright, Patchright, Camoufox, Crawlee) via a single proxy abstraction. Proxy support SHALL be disabled by default and enabled only by configuration. The same abstraction SHALL offer a separate customer-supplied crawl proxy, `CRAWL_PROXY_URL`, used only by crawl jobs and never by single reads. The service SHALL NOT run, host or resell a proxy.

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

### Requirement: No service-side request rate limiting

The service SHALL NOT impose per-domain or per-caller request rate limiting or self-throttling on single reads. Throughput control for single reads is delegated to the deployment stack. Crawl jobs are the one exception: they SHALL apply the per-domain crawl delay and concurrency cap of the crawl frontier.

#### Scenario: Rapid successive reads

- **WHEN** many read requests are issued in quick succession
- **THEN** the service does not delay, queue, or reject them for rate-limiting reasons

#### Scenario: Crawl politeness does not slow single reads

- **WHEN** a crawl job is throttling its fetches to one domain and a single read for that domain arrives
- **THEN** the single read is not delayed by the crawl's throttle
