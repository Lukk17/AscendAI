# web-search-authenticated-sessions Specification

## Purpose

Defines how ascend-web-hunter captures a browser session for a site, stores it under a domain and a named profile with independent auth and WAF lifetimes, and replays it into whichever fetch tier can carry it, so a login completed once by a human is reused headlessly on later reads instead of being discarded. Also covers the session management API (establish, status, clear), the validation that slides an actively used auth lifetime, and the routing rule that a stored session is replayed by the tier that earned it.

## Requirements

### Requirement: Captured session includes full browser storage state

When a session is captured by the NoVNC login monitor, the service SHALL persist the full Playwright `storage_state`, meaning cookies including httpOnly cookies AND per-origin localStorage, not only `context.cookies()`. The persisted blob SHALL be sufficient to reconstruct an authenticated browser context. The Playwright, Patchright and Camoufox tiers replay a stored session and do not write one back.

#### Scenario: Human logs in to a site via NoVNC

- **WHEN** a user completes a login for `linkedin.com` in the NoVNC browser
- **THEN** the stored session for that domain contains the httpOnly auth cookies (e.g. `li_at`)
- **AND** it contains the page's localStorage entries captured via `context.storage_state()`

### Requirement: Stored session is replayed into every fetch tier

Every fetch tier that can carry a session SHALL load the stored session for the target domain/profile and inject it before fetching: curl_cffi via request cookies, Playwright, Patchright, Camoufox and Crawlee via `new_context(storage_state=...)`. A tier MUST NOT start an anonymous context when a session exists for the target.

#### Scenario: Authenticated headless read after login

- **WHEN** a session exists for `linkedin.com` and a read for a `linkedin.com` URL escalates to the Playwright tier
- **THEN** the Playwright context is created with the stored `storage_state`
- **AND** the response is the authenticated page, not the logged-out/anonymous version

#### Scenario: Authenticated read on a patched-browser tier

- **WHEN** a session exists for `linkedin.com` and a read for a `linkedin.com` URL reaches `4a-patchright` or `4b-camoufox`
- **THEN** that tier's context is created with the stored `storage_state`

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

### Requirement: Import a captured browser storage state through the REST API

ascend-web-hunter SHALL expose `POST /api/v2/web/session/import` accepting `url`, an optional `profile`, a Playwright `storage_state` (`cookies` and `origins`) and an optional `user_agent`. Before storing anything it SHALL refuse, with no address lookup because the import makes no request to the URL, a URL whose host has no registrable domain (an IP address literal or a name with no public suffix) with `400 unsafe_uri`, a profile outside `^[A-Za-z0-9_-]{1,64}$` with `400 invalid_profile` and a storage state with no cookie for the URL's registrable domain with `400 no_cookies_for_domain`. On success it SHALL drop cookies of other domains, store the rest under the URL's registrable domain and the effective profile with provenance `import` in the same record shape a NoVNC capture produces, clear the read cache for that domain on every running ascend-web-hunter instance through the same purge a session clear runs, and answer `200` with the domain, the profile and the counts of stored and dropped cookies. The endpoint SHALL NOT refuse a storage state for its size or for its number of cookies. Every later request that uses the imported session SHALL still pass the `check_fetch_uri` guard of the `ascend-python-common` library when it is made.

#### Scenario: The read cache of every instance is cleared

- **WHEN** two ascend-web-hunter instances hold a cached anonymous read of `https://www.example.net/` and a caller imports a session for that URL through the first instance
- **THEN** the import triggers the same domain purge a session clear triggers
- **AND** a following read of that URL on the second instance is not answered from its cache

#### Scenario: Imported session is replayed on the next read

- **WHEN** a caller imports a storage state holding a valid `saucedemo.com` login cookie for `https://www.saucedemo.com/inventory.html` with profile `e2e`
- **THEN** the answer is `200` with `domain` `saucedemo.com` and `profile` `e2e`
- **AND** a following read of `https://www.saucedemo.com/inventory.html` with `profile=e2e` returns the logged-in page instead of the login wall

#### Scenario: Private address is refused

- **WHEN** a caller imports a storage state for `http://127.0.0.1/admin`
- **THEN** the answer is `400` with code `unsafe_uri`
- **AND** nothing is written to the session store
- **AND** no address lookup is made

#### Scenario: Every refusal is a problem body

- **WHEN** an import is refused with `unsafe_uri`, `invalid_profile` or `no_cookies_for_domain`
- **THEN** the answer has media type `application/problem+json`, `type` `https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`, the `code` and a `traceId` of 32 lower case hex characters

#### Scenario: Imported session is reported active

- **WHEN** a caller imports a storage state for `https://www.example.net/` with profile `e2e-import` and then asks `POST /api/v2/web/session/status` for that URL and profile
- **THEN** the status answer is `active`
- **AND** the stored record names `import` as its provenance

#### Scenario: Large storage state is accepted

- **WHEN** a caller imports a storage state holding 1000 cookies for the URL's registrable domain
- **THEN** the answer is `200`
- **AND** all 1000 cookies are stored

#### Scenario: Cookies for another site only

- **WHEN** every cookie in the storage state belongs to `example.org` and the URL is on `saucedemo.com`
- **THEN** the answer is `400` with code `no_cookies_for_domain`
- **AND** nothing is written to the session store

#### Scenario: Foreign cookies are dropped

- **WHEN** the storage state holds two `saucedemo.com` cookies and one `example.org` cookie
- **THEN** the answer is `200` with `dropped_cookies` equal to `1`
- **AND** the stored record holds no `example.org` cookie

#### Scenario: Invalid profile is refused

- **WHEN** a caller imports with profile `../work`
- **THEN** the answer is `400` with code `invalid_profile`

### Requirement: A stored session is replayed by the browser family that earned it

The store SHALL record which tier produced a session, and the orchestrator SHALL use that producer to choose where the chain restarts. A session produced by a browser tier SHALL send the read to the browser tiers, and SHALL be replayed only by a tier of the same browser family.

#### Scenario: Stored login captured by a browser

- **WHEN** a read targets a domain whose stored session was produced by a browser tier
- **THEN** the read starts at the browser tiers
