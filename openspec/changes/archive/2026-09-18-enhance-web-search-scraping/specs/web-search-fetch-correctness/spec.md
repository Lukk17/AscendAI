## ADDED Requirements

### Requirement: SSRF guard re-validated on every redirect hop

The SSRF safety check SHALL be enforced at the transport layer, not only at the API edge. The in-process fetch tiers SHALL NOT follow redirects blindly: automatic redirect following is disabled and each redirect `Location` SHALL be re-validated with the same private, loopback, link-local and metadata-IP rules before it is followed, up to a bounded hop count. A response history SHALL likewise be re-checked hop by hop. The tiers that fetch outside this process, FlareSolverr and Crawlee, SHALL be validated before dispatch, which is the only check available for them.

#### Scenario: Redirect to an internal address

- **WHEN** a fetched public URL responds with a redirect to `http://169.254.169.254/` or a private/loopback address
- **THEN** the redirect is rejected and the read fails with an unsafe-URL outcome
- **AND** the internal address is never fetched

#### Scenario: Redirect chain longer than the hop bound

- **WHEN** a URL redirects more times than the configured hop bound
- **THEN** following stops at the bound rather than continuing indefinitely

#### Scenario: Out-of-process tier dispatch

- **WHEN** a read is dispatched to FlareSolverr or Crawlee
- **THEN** the target URL is validated before dispatch
- **AND** the redirect hops those tiers take internally are accepted as residual risk, since they are not observable from this process

### Requirement: Challenge and login detection regardless of page size

Challenge, block and login detection SHALL NOT be skipped based on response size. A page larger than the size threshold SHALL still be scanned: detection reads a bounded prefix of the response rather than abandoning the scan, so a large page can never fail open into being treated as clean content. The prefix length SHALL be a named configuration setting.

#### Scenario: Large challenge page

- **WHEN** a Cloudflare interstitial or login page larger than the configured prefix is returned
- **THEN** detection scans the bounded prefix and still identifies it as a challenge or login page
- **AND** the orchestrator escalates or signals login rather than accepting it as content

### Requirement: Content validation fails closed

When the content validator's quality assessment raises an error, the content SHALL be treated as invalid (escalate to a stronger tier) rather than accepted as a successful read.

#### Scenario: Quality assessment errors

- **WHEN** the content quality assessment raises an exception for a candidate extraction
- **THEN** the candidate is treated as failing validation and the orchestrator escalates

### Requirement: Human-intervention signal propagates on the links path

The `include_links` read path SHALL propagate the human-intervention signal (the 428 with the VNC URL) the same way the plain read path does, rather than swallowing it in a generic failure.

#### Scenario: Login wall hit on the include_links path

- **WHEN** a read with `include_links=true` hits a login wall that requires human intervention
- **THEN** the caller receives the 428 response with the VNC URL
- **AND** it is not reported as a generic all-tiers-failed error

### Requirement: Crawlee runtime state is not tracked and is purged

Crawlee request-queue / key-value-store runtime state SHALL NOT be committed to the repository and SHALL NOT accumulate across runs. The storage directory SHALL be gitignored, relocated outside the source tree, and purged on start.

#### Scenario: Repository cleanliness

- **WHEN** the service runs the Crawlee tier
- **THEN** no Crawlee runtime-state files appear as tracked changes in git
- **AND** stale queues from prior runs are purged on start

### Requirement: Crawlee tier honours headless configuration

The Crawlee tier SHALL honour the `PLAYWRIGHT_HEADLESS` setting rather than hardcoding a headed browser, so it launches in a headless container.

#### Scenario: Headless deployment

- **WHEN** `PLAYWRIGHT_HEADLESS` is true and a read escalates to the Crawlee tier
- **THEN** the Crawlee browser launches headless and does not fail for lack of a display
