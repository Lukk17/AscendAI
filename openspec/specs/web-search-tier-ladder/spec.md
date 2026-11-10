# web-search-tier-ladder Specification

## Purpose
Defines the order in which ascend-web-hunter escalates a read through its extraction tiers, which tier values a caller may select and which are refused, the URI guard every browser request passes, and the per-domain memory of the tier that last returned accepted content.

## Requirements

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

### Requirement: A caller who selects the switched-off Camoufox tier is refused with 409

The `4b-camoufox` tier SHALL run only while `CAMOUFOX_ENABLED` is true, and the default SHALL be true. While it is false the ladder SHALL skip it, and a request that selects `4b-camoufox` as its `tier` SHALL be refused with HTTP 409 on REST, as a problem body with `code` `tier_disabled` and a `detail` naming the tier `4b-camoufox`, and with a tool error on MCP that starts with `tier_disabled: ` and names the same tier. No tier SHALL run for that request.

#### Scenario: Caller selects Camoufox while it is switched off on REST

- **WHEN** `CAMOUFOX_ENABLED` is false and a REST caller reads a page with `tier` `4b-camoufox`
- **THEN** the answer is HTTP 409 with `code` `tier_disabled` and a `detail` that names `4b-camoufox`
- **AND** no tier runs

#### Scenario: Caller selects Camoufox while it is switched off on MCP

- **WHEN** `CAMOUFOX_ENABLED` is false and an MCP caller calls `web_read` with `tier` `4b-camoufox`
- **THEN** the tool fails with a text that starts with `tier_disabled: ` and names `4b-camoufox`

### Requirement: Every browser request passes the shared URI guard before the browser connects

Every browser tier (`4-playwright_stealth`, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive` and the browser of
`6-novnc`) SHALL check every page load, every redirect hop and every subresource request against `check_fetch_uri` of
the `ascend-python-common` library before the browser connects, through a route handler installed on the browser
context before the first navigation, with service workers blocked. A request the guard refuses SHALL be aborted with no
connection to its address. A request the guard allows SHALL be sent by the handler through the pinned curl_cffi fetch,
with the request's method, headers, body and the context's cookies and the TLS fingerprint of the tier's browser family
(Chromium or Firefox), and its answer SHALL reach the browser through `route.fulfill`, with its `Set-Cookie` lines
applied to the context. A fulfilled redirect is followed by the browser without passing the route handler again, so
the handler SHALL never fulfill a redirect. A navigation that answers with a redirect SHALL be aborted and its frame
SHALL navigate to the next hop, which passes the handler as a new request, checked and pinned, with the method and
body a browser rewrites the redirect to, so the page's address, its relative links and subresources, its history and
the latest main-frame response belong to the final hop. A subresource redirect SHALL be followed inside the handler,
checking and pinning every hop. The `Set-Cookie` lines of every hop the browser never sees SHALL be applied to the
context for that hop's address. Requests to one checked host SHALL reuse their connections through one curl_cffi
session per pinned address set and browser context, and a reused connection SHALL never reach an address the request
was not checked against. An answer larger than
`BROWSER_RESPONSE_MAX_BYTES` SHALL be aborted. Every page WebSocket SHALL be closed, and every browser SHALL launch with
a proxy on `127.0.0.1:1` that refuses the connections the route handler does not see (speculative prefetch, preconnect,
shared and Firefox worker requests, WebRTC). A refused main navigation SHALL end the read with code `unsafe_uri`
(HTTP 400 on REST, a tool error on MCP). A refused subresource SHALL be blocked while the page continues. Owner decision
66 of 2026-10-04, amended by security fix 19 of 2026-11-07.

#### Scenario: A public page that redirects the browser to a private address is refused

- **WHEN** a read of a public page runs in a browser tier and the page answers with a redirect to `http://169.254.169.254/latest/meta-data/`
- **THEN** the browser sends no request to `169.254.169.254`
- **AND** the read answers code `unsafe_uri`

#### Scenario: A page that loads a subresource from a private address

- **WHEN** a public page in a browser tier includes an image from `http://10.0.0.5/pixel.png`
- **THEN** that request is aborted with no connection to `10.0.0.5`
- **AND** the page is still read and returned

#### Scenario: A script navigation to a private address is refused

- **WHEN** a public page in a browser tier sets `window.location` to `http://127.0.0.1:6379/`
- **THEN** the browser sends no request to `127.0.0.1` and the read answers code `unsafe_uri`

#### Scenario: A cross-host redirect shows the final address

- **WHEN** a browser tier reads `http://a.test/start`, which redirects to `http://www.b.test/x`, which redirects to
  `/final`, and every hop sets a cookie
- **THEN** the page's address and `document.location` are `http://www.b.test/final`
- **AND** a relative link or image on the page resolves against `http://www.b.test/final`
- **AND** each hop's cookie is stored for the domain of that hop

#### Scenario: A form post answered with 303 continues as a GET

- **WHEN** a page in a browser tier posts a form and the answer is a 303 to another host
- **THEN** the next hop is requested with `GET` and no body, the page shows the next hop's address, and the history
  gains one entry

#### Scenario: A form post answered with 307 keeps the post

- **WHEN** a page in a browser tier posts a form and the answer is a 307 to another host
- **THEN** the next hop is requested with `POST` and the same body

#### Scenario: A page with many subresources on one host reuses connections

- **WHEN** a page in a browser tier loads fifty images from its own host
- **THEN** the host accepts at most ten connections for the whole page

#### Scenario: A page opens a WebSocket

- **WHEN** a public page in a browser tier opens a WebSocket to any address
- **THEN** the socket is closed before any connection is made to that address
- **AND** the page is still read and returned

#### Scenario: A private target is refused whatever tier the caller selects

- **WHEN** a caller reads a URL whose host resolves to a private address and passes `tier` `1-beautifulsoup`, `2-trafilatura`, `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` or `5-crawlee_adaptive`
- **THEN** each REST answer is HTTP 400 with media type `application/problem+json`, `code` `unsafe_uri` and a `traceId` of 32 lower case hex characters
- **AND** no request reaches the private address

### Requirement: Per-domain tier memory with decay

ascend-web-hunter SHALL store in Redis, per registrable domain, the tier that last returned accepted content, and SHALL start the next read for that domain at that tier. Each accepted read SHALL overwrite the record with the tier that served it, whether that tier sits earlier or later in the ladder than the one stored. Only a read with no caller-selected `tier` and with `heavy_mode` off SHALL write the record, because the start point of any other read was chosen by the caller and not found by the ladder. The record SHALL expire after `TIER_MEMORY_TTL_SECONDS`, after which the read starts at the beginning of the ladder. A caller-selected `tier` and a stored session's producer SHALL take precedence over the memory. A Redis failure SHALL NOT fail the read.

#### Scenario: Remembered tier is the start point

- **WHEN** a domain last succeeded at `4b-camoufox` within the TTL and a new read for it begins without a `tier`
- **THEN** the read starts at `4b-camoufox`

#### Scenario: The remembered tier is stored per domain

- **WHEN** a read without a `tier` succeeds at a browser tier
- **THEN** Redis holds `tier_memory:<registrable domain>` naming that tier with a TTL no larger than `TIER_MEMORY_TTL_SECONDS`
- **AND** the next read of that domain answers with the same tier as its `mode`

#### Scenario: A later success at a dearer tier replaces the memory

- **WHEN** the memory for a domain names `4-playwright_stealth` and the next read without a `tier` is accepted only at `4b-camoufox`
- **THEN** the memory for that domain names `4b-camoufox`

#### Scenario: A read with a selected tier or heavy mode leaves the memory alone

- **WHEN** a read passes `tier` `4a-patchright`, or passes `heavy_mode` true, and is accepted
- **THEN** the memory for that domain is not written by that read

#### Scenario: Memory expires

- **WHEN** `TIER_MEMORY_TTL_SECONDS` has passed since the last record for a domain
- **THEN** the next read starts at `1-beautifulsoup`

#### Scenario: Redis unavailable

- **WHEN** the tier memory cannot reach Redis
- **THEN** the read climbs the full ladder and a WARNING is logged

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
