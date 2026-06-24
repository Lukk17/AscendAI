## ADDED Requirements

### Requirement: Captured session includes full browser storage state

When a session is captured (NoVNC login monitor and the Playwright tier), the service SHALL persist the full Playwright `storage_state` — cookies including httpOnly cookies AND per-origin localStorage — not only `context.cookies()`. The persisted blob SHALL be sufficient to reconstruct an authenticated browser context.

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

### Requirement: Session validation before authenticated read

When a read targets a domain that has a stored session, the service SHALL validate the session is still authenticated (an optional per-domain probe + logged-in marker) before relying on it. On success it SHALL slide the auth TTL; on failure it SHALL report a `session_expired` outcome rather than returning the anonymous page as success.

#### Scenario: Stored session has silently expired

- **WHEN** a stored session is no longer logged in and a probe confirms the anonymous state
- **THEN** the read result reports `session_expired`
- **AND** the anonymous page content is not returned as a successful authenticated read

### Requirement: Session management API and per-request overrides

The service SHALL expose, over both REST and MCP: a proactive operation to establish a login for a domain (optionally a profile) that opens the NoVNC flow and returns the VNC URL; a session-status query returning `active | expired | none`, remaining auth TTL, and last-validated time; and optional `profile`, starting `tier`, and `output_format` fields on the read operation.

#### Scenario: Proactively establish a login

- **WHEN** the establish operation is called for `linkedin.com` with profile `work`
- **THEN** the response returns a usable NoVNC URL for the user to complete login
- **AND** after login the captured session is stored under domain `linkedin.com`, profile `work`

#### Scenario: Query session status

- **WHEN** the status operation is called for a domain with a valid stored session
- **THEN** the response reports `active` with a positive remaining auth TTL
