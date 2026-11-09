# web-search-fetch-correctness Specification

## Purpose

Defines the correctness and safety rules the fetch path holds to regardless of which tier serves a read: the SSRF guard re-validated on every redirect hop rather than only at the API edge, challenge and login detection that cannot be skipped by a large response, content validation that fails closed, the human-intervention signal propagating on the links path, and Crawlee runtime state staying out of the repository and out of the next run.

## Requirements

### Requirement: SSRF guard re-validated on every redirect hop

The SSRF safety check SHALL be enforced at the transport layer, not only at the API edge. The in-process fetch
tiers SHALL NOT follow redirects blindly: automatic redirect following is disabled and each redirect `Location`
SHALL be re-validated with the same private, loopback, link-local and metadata-IP rules before that hop is
fetched, up to a bounded hop count. The re-validation SHALL happen before each hop is fetched rather than by
inspecting a response history afterwards, because the tier follows the chain itself, one request at a time, and no
history of hops it did not follow exists to inspect. A `Location` that is a relative reference, whether
root-relative, path-relative or protocol-relative, SHALL first be resolved against the URL of the hop that
returned it, as RFC 9110 section 10.2.2 requires, and the resolved absolute URL SHALL then face exactly the same
validation a `Location` that was absolute to begin with faces. The browser tiers, `4-playwright_stealth`,
`4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive` and `6-novnc`, do not follow redirects in this process. They
SHALL pass every request their browser makes, every redirect hop included, through the shared browser URI guard of
`web-search-tier-ladder` before the browser connects to it, and the Crawlee tier SHALL also validate its seed URL
before the crawler runs.

#### Scenario: Redirect to an internal address

- **WHEN** a fetched public URL responds with a redirect to `http://169.254.169.254/` or a private/loopback address
- **THEN** the redirect is rejected and the read fails with an unsafe-URL outcome
- **AND** the internal address is never fetched

#### Scenario: Redirect chain longer than the hop bound

- **WHEN** a URL redirects more times than the configured hop bound
- **THEN** following stops at the bound rather than continuing indefinitely

#### Scenario: Relative redirect to a safe public URL

- **WHEN** a fetched public URL responds with a relative `Location` such as `/article` or `../index.html`
- **THEN** the reference is resolved against the URL of the hop that returned it
- **AND** the resolved URL is validated, fetched, and its content returned by the tier that received the redirect

#### Scenario: Protocol-relative redirect to a second host

- **WHEN** a hop responds with a `Location` of the form `//other.example/page`
- **THEN** the reference takes the scheme of the hop that returned it and is validated as that second host

#### Scenario: Relative redirect that resolves onto an internal address

- **WHEN** a relative `Location` resolves to a host that answers with a private, loopback, link-local, multicast or
  reserved address
- **THEN** the hop is refused and no request is issued for it
- **AND** the read returns no content

#### Scenario: Browser tier dispatch

- **WHEN** a read is dispatched to a browser tier
- **THEN** the target URL is validated before the browser connects to it
- **AND** every redirect hop the browser takes passes the same guard before it is fetched

### Requirement: Challenge and login detection regardless of page size

Challenge, block and login detection SHALL NOT be skipped based on response size. A page larger than the size threshold SHALL still be scanned: detection reads a bounded prefix of the response rather than abandoning the scan, so a large page can never fail open into being treated as clean content. The prefix length SHALL be a named configuration setting. The wall decision SHALL be the scored verdict of `ChallengeDetector.assess`, which reads the status code, the response headers and the cookie names when the tier has them, plus the bounded prefix, so a wall whose text is in a language the phrase list does not know is still detected through its language-independent signals.

#### Scenario: Large challenge page

- **WHEN** a Cloudflare interstitial or login page larger than the configured prefix is returned
- **THEN** detection scans the bounded prefix and still identifies it as a challenge or login page
- **AND** the orchestrator escalates or signals login rather than accepting it as content

#### Scenario: Wall in a language with no captured phrase

- **WHEN** a tier receives Amazon's captcha page from `amazon.co.jp` and no Japanese phrase is in the catalogue
- **THEN** the verdict is a wall from the structure and shape signals alone
- **AND** the read answers HTTP 428 with a `vnc_url` rather than HTTP 200 with the interstitial as content

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

### Requirement: Crawlee tier leaves the process logging unchanged

The Crawlee tier SHALL build its crawler with Crawlee's own logging setup turned off (`configure_logging=False`), so a read through it SHALL NOT change the handlers, formatters or levels of the root, web server or `httpx` loggers, and Crawlee's own records SHALL reach the service's handlers.

#### Scenario: Service logs keep their format after a Crawlee read

- **WHEN** a read runs through `5-crawlee_adaptive` in a service that logs with `LOG_FORMAT=json`
- **THEN** every later service log line, access lines included, is still JSON with `correlation_id` and `trace_id`
- **AND** Crawlee's own log records are written by the service's handler

### Requirement: The validated address is the address connected to

An in-process fetch SHALL connect to an address that was validated by the same name resolution that authorised it.
One resolution SHALL both check every returned address against the private, loopback, link-local, multicast and
reserved rules and supply those addresses to the transport, so no second resolution stands between the check and
the connection. A host that resolves to no public address SHALL NOT be connected to at all.

A URL whose host is already an IP literal SHALL be checked against the same address rules, and SHALL carry no pin,
because there is no name there for a second resolution to answer differently.

This applies to the initial URL and to every redirect hop the in-process tier follows. It applies to the browser
tiers too, `4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive` and `6-novnc`, and to the
screenshot capture: every request the browser guard allows SHALL be sent through the same pinned fetch the in-process
tier uses and answered to the browser with `route.fulfill`, so the browser never resolves the name of a routed
request. Owner decision, security fix 19 of 2026-11-07.

#### Scenario: The name answers differently after it has been validated

- **WHEN** a host resolves to a public address at validation time and to a private, loopback or metadata address by
  the time the connection is made
- **THEN** the connection is made to the validated public address
- **AND** the later address is never connected to

#### Scenario: A host with no public address

- **WHEN** a fetch targets a host that resolves only to private, loopback, link-local, multicast or reserved
  addresses
- **THEN** no request is issued for that host
- **AND** the fetch returns no content

#### Scenario: A redirect hop is pinned too

- **WHEN** an in-process fetch follows a redirect to a second host
- **THEN** that host is resolved and validated once, and the hop connects to an address from that same resolution

#### Scenario: A browser tier reads the validated address after the name is rebound

- **WHEN** a browser tier reads a page whose host resolves to a public address at validation time and to a loopback
  address by the time a connection would be made
- **THEN** the page and its subresources are read from the validated address
- **AND** the loopback address is never connected to

#### Scenario: A host with several public addresses

- **WHEN** a host resolves to more than one address and all of them are public
- **THEN** every one of them is offered to the transport as a permitted connection target
