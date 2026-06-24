## ADDED Requirements

### Requirement: SSRF guard re-validated on redirects and pinned to resolved IP

The SSRF safety check SHALL be enforced at the transport layer, not only at the API edge. Fetch tiers SHALL NOT follow redirects blindly: each redirect `Location` SHALL be re-validated with the same private/loopback/link-local/metadata-IP rules before being followed, and the validated IP SHALL be pinned through to the connection so a hostname cannot resolve to a public IP at validation time and a private IP at fetch time (DNS-rebinding).

#### Scenario: Redirect to an internal address

- **WHEN** a fetched public URL responds with a redirect to `http://169.254.169.254/` or a private/loopback address
- **THEN** the redirect is rejected and the read fails with an unsafe-URL outcome
- **AND** the internal address is never fetched

#### Scenario: DNS rebinding between validation and fetch

- **WHEN** a hostname resolves to a public IP during validation and a private IP at fetch time
- **THEN** the fetch connects only to the validated public IP (or fails) and never to the private IP

### Requirement: Challenge and login detection regardless of page size

Challenge/block and login detection SHALL NOT be skipped based on response size. Pages larger than the previous 50 000-byte cutoff SHALL still be scanned for challenge and login signatures.

#### Scenario: Large challenge page

- **WHEN** a Cloudflare interstitial or login page larger than 50 000 bytes is returned
- **THEN** detection still identifies it as a challenge/login page
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
