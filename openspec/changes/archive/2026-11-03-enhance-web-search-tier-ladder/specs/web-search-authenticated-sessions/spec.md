## MODIFIED Requirements

### Requirement: Stored session is replayed into every fetch tier

Every fetch tier that can carry a session SHALL load the stored session for the target domain/profile and inject it before fetching: curl_cffi via request cookies, FlareSolverr via its request `cookies` array while that tier is enabled, Playwright, Patchright, Camoufox and Crawlee via `new_context(storage_state=...)`. A tier MUST NOT start an anonymous context when a session exists for the target.

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

### Requirement: FlareSolverr persists returned cookies unconditionally

While `FLARESOLVERR_ENABLED` is true, the FlareSolverr tier SHALL persist the cookies returned by FlareSolverr whenever the cookie set is non-empty, regardless of whether a Cloudflare `cf_clearance` cookie is present. While it is false the tier does not run and persists nothing.

#### Scenario: FlareSolverr returns auth cookies for a non-Cloudflare site

- **WHEN** `FLARESOLVERR_ENABLED` is true and FlareSolverr returns a non-empty cookie set with no `cf_clearance`
- **THEN** the returned cookies are saved to the session store for the domain/profile

### Requirement: A stored session is replayed by the tier that earned it

The store SHALL record which tier produced a session, and the orchestrator SHALL use that producer to choose where the chain restarts. A session produced by FlareSolverr SHALL be replayed through FlareSolverr before any browser tier is tried while `FLARESOLVERR_ENABLED` is true, because a WAF clearance is bound to the fingerprint that earned it. While it is false, a session produced by FlareSolverr SHALL send the read to the browser tiers. A session produced by a browser tier SHALL send the read to the browser tiers, and SHALL be replayed only by a tier of the same browser family.

#### Scenario: Stored WAF clearance from FlareSolverr

- **WHEN** `FLARESOLVERR_ENABLED` is true and a read targets a domain whose stored session was produced by the FlareSolverr tier
- **THEN** the FlareSolverr tier runs first, ahead of the browser tiers

#### Scenario: Stored FlareSolverr session while the tier is disabled

- **WHEN** `FLARESOLVERR_ENABLED` is false and a read targets a domain whose stored session was produced by the FlareSolverr tier
- **THEN** the read starts at the browser tiers

#### Scenario: Stored login captured by a browser

- **WHEN** a read targets a domain whose stored session was produced by a browser tier
- **THEN** the read starts at the browser tiers
