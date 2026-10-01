# web-search-authenticated-sessions Specification

## Purpose

Defines how ascend-web-hunter captures a browser session for a site, stores it under a domain and a named profile with independent auth and WAF lifetimes, and replays it into whichever fetch tier can carry it, so a login completed once by a human is reused headlessly on later reads instead of being discarded. Also covers the session management API (establish, status, clear), the validation that slides an actively used auth lifetime, and the routing rule that a stored session is replayed by the tier that earned it.

## Requirements

### Requirement: Captured session includes full browser storage state

When a session is captured by the NoVNC login monitor, the service SHALL persist the full Playwright `storage_state`, meaning cookies including httpOnly cookies AND per-origin localStorage, not only `context.cookies()`. The persisted blob SHALL be sufficient to reconstruct an authenticated browser context. The FlareSolverr tier, which never holds a browser context of its own, SHALL persist the flat cookie set that tier returns. The Playwright tier replays a stored session and does not write one back.

#### Scenario: Human logs in to a site via NoVNC

- **WHEN** a user completes a login for `linkedin.com` in the NoVNC browser
- **THEN** the stored session for that domain contains the httpOnly auth cookies (e.g. `li_at`)
- **AND** it contains the page's localStorage entries captured via `context.storage_state()`

### Requirement: Stored session is replayed into every fetch tier

Every fetch tier that can carry a session SHALL load the stored session for the target domain/profile and inject it before fetching: curl_cffi via request cookies, FlareSolverr via its request `cookies` array, Playwright and Crawlee via `new_context(storage_state=...)`. A tier MUST NOT start an anonymous context when a session exists for the target.

#### Scenario: Authenticated headless read after login

- **WHEN** a session exists for `linkedin.com` and a read for a `linkedin.com` URL escalates to the Playwright tier
- **THEN** the Playwright context is created with the stored `storage_state`
- **AND** the response is the authenticated page, not the logged-out/anonymous version

#### Scenario: No session present

- **WHEN** no session exists for the target domain/profile
- **THEN** each tier fetches anonymously exactly as before
- **AND** no error is raised for the missing session

### Requirement: Auth and WAF cookies expire independently

A stored session SHALL separate long-lived auth state from short-lived WAF clearance into two record sets with independent, configurable TTLs (auth default 14 days and sliding on a successful authenticated read; WAF default 30 minutes). Both sets SHALL be merged when injected.

#### Scenario: WAF clearance expires but login survives

- **WHEN** more than the WAF TTL but less than the auth TTL has elapsed since login
- **THEN** the auth cookies are still returned by the session store
- **AND** the expired WAF cookies are not returned

### Requirement: FlareSolverr persists returned cookies unconditionally

The FlareSolverr tier SHALL persist the cookies returned by FlareSolverr whenever the cookie set is non-empty, regardless of whether a Cloudflare `cf_clearance` cookie is present.

#### Scenario: FlareSolverr returns auth cookies for a non-Cloudflare site

- **WHEN** FlareSolverr returns a non-empty cookie set with no `cf_clearance`
- **THEN** the returned cookies are saved to the session store for the domain/profile

### Requirement: Single-user named session profiles

The session store SHALL be keyed by domain and an optional `profile` label (default `"default"`), so a single local user can hold multiple accounts per site. The `profile` label is a free-form string and implies no authentication or cross-caller isolation.

#### Scenario: Two profiles for one domain

- **WHEN** a session is established for `linkedin.com` with profile `work` and another with profile `personal`
- **THEN** the two sessions are stored independently and neither overwrites the other
- **AND** a read specifying `profile=work` injects the `work` session

### Requirement: Session validation slides the auth TTL

The service SHALL expose a validation operation that reports whether a stored session for a domain and profile is
still usable. Validation SHALL check that the auth TTL has not lapsed and that the stored record still carries
cookies, and on success it SHALL slide the auth TTL so an actively used login does not expire under a caller.
Validation is a store-side check, not a network probe against the target site.

The read path SHALL invoke validation before it runs any tier, and only for a target whose stored record carries
auth cookies, meaning a login was captured for it at some point. A target with no stored record, or one whose
record only ever carried WAF-clearance cookies, SHALL NOT be gated on validation and SHALL read exactly as an
unauthenticated target does.

#### Scenario: Valid session is validated

- **WHEN** validation runs for a domain and profile whose stored record is within the auth TTL and carries cookies
- **THEN** validation succeeds
- **AND** the auth TTL for that record is slid forward

#### Scenario: Lapsed or empty session is validated

- **WHEN** validation runs for a domain and profile whose auth TTL has lapsed, or whose stored record carries no
  cookies
- **THEN** validation fails
- **AND** the auth TTL is not slid

#### Scenario: A read of a target with a live login

- **WHEN** a read targets a domain and profile whose stored record carries auth cookies within the auth TTL
- **THEN** validation runs before the tier chain, succeeds, and slides the auth TTL
- **AND** the tier chain runs as it otherwise would

#### Scenario: A read of a target with no stored session

- **WHEN** a read targets a domain and profile with no stored record, or one whose record carries only WAF
  cookies
- **THEN** no validation gate applies
- **AND** the tier chain runs as it otherwise would

### Requirement: A logged-out page is never accepted as extracted content

Because validation is not a network probe, the guarantee that a read does not silently return a logged-out page rests on detection rather than on session state. Every response SHALL be scanned for login and challenge signatures before it is accepted as content, and a URL that is itself a known login redirect SHALL be routed to the human-intervention tier without being fetched by the cheap tiers first.

#### Scenario: Read lands on a login wall

- **WHEN** a fetched page carries a login signature
- **THEN** the orchestrator escalates or raises the human-intervention signal
- **AND** the login page is not returned as successfully extracted content

#### Scenario: Requested URL is itself a login redirect

- **WHEN** the requested URL matches a known login-redirect pattern
- **THEN** the read goes straight to the human-intervention tier

### Requirement: Session management API and per-request profile

The service SHALL expose, over both REST and MCP: a proactive operation to establish a login for a domain
(optionally a profile) that opens the NoVNC flow and returns the VNC URL; a session-status query returning
`active | expired | none`, remaining auth TTL, and last-validated time; an idempotent clear operation that deletes
the stored session for a domain and profile and purges that domain's cached read results; and, on the read
operation, an optional `profile` field, an optional `output_format` field, and an optional starting `tier` field.

`output_format` SHALL accept `text` or `structured` and SHALL default to `text`. `tier` SHALL accept one of the
named strategy tiers and SHALL be unset by default, in which case `heavy_mode` and the producer of the stored
session decide where the chain starts, unchanged. Both fields SHALL be part of the read cache key.

#### Scenario: Proactively establish a login

- **WHEN** the establish operation is called for `linkedin.com` with profile `work`
- **THEN** the response returns a usable NoVNC URL for the user to complete login
- **AND** after login the captured session is stored under domain `linkedin.com`, profile `work`

#### Scenario: Query session status

- **WHEN** the status operation is called for a domain with a valid stored session
- **THEN** the response reports `active` with a positive remaining auth TTL

#### Scenario: Clear a session that was never stored

- **WHEN** the clear operation is called for a domain and profile that carry no stored session
- **THEN** the call succeeds and reports that no session existed, rather than failing

#### Scenario: Read with neither new field

- **WHEN** a read is requested over REST or MCP with neither `output_format` nor `tier`
- **THEN** the response is the flat content shape and the chain starts where it started before those fields existed

### Requirement: A stored session is replayed by the tier that earned it

The store SHALL record which tier produced a session, and the orchestrator SHALL use that producer to choose where the chain restarts. A session produced by FlareSolverr SHALL be replayed through FlareSolverr before any browser tier is tried, because a WAF clearance is bound to the fingerprint that earned it. A session produced by a browser tier SHALL send the read to the browser tiers.

#### Scenario: Stored WAF clearance from FlareSolverr

- **WHEN** a read targets a domain whose stored session was produced by the FlareSolverr tier
- **THEN** the FlareSolverr tier runs first, ahead of the browser tiers

#### Scenario: Stored login captured by a browser

- **WHEN** a read targets a domain whose stored session was produced by a browser tier
- **THEN** the read starts at the browser tiers

### Requirement: An expired stored session is reported, not used blindly

When a read targets a domain and profile whose stored record carries auth cookies and validation fails, the read
SHALL return a `session_expired` outcome without running any tier. The outcome SHALL name the domain, the profile,
and the operation that re-establishes the session. It SHALL NOT be reported as a generic failure and the read SHALL
NOT fall back to an anonymous fetch of the same URL.

The gate SHALL be applied before any cached result for the request is served, so the outcome does not depend on
whether an earlier read of the same URL is still cached.

#### Scenario: Read against a lapsed login

- **WHEN** a read targets a domain and profile whose stored auth cookies have lapsed
- **THEN** the caller receives the `session_expired` outcome naming the domain and the profile
- **AND** no extraction tier runs

#### Scenario: The outcome is not a generic failure

- **WHEN** a read returns `session_expired`
- **THEN** the outcome is distinguishable from the all-tiers-failed and budget-exhausted outcomes
- **AND** it carries the next step the caller can take

#### Scenario: A cached read does not mask an expired session

- **WHEN** a read whose result is still cached is repeated after its stored session has lapsed
- **THEN** the caller receives the `session_expired` outcome rather than the cached content
