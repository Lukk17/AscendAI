## MODIFIED Requirements

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

## REMOVED Requirements

### Requirement: A stored session is replayed by the tier that earned it

**Reason**: Its FlareSolverr rules (replay through FlareSolverr first, and the scenarios of a FlareSolverr session) go with the tier. What stays is the browser part, now the requirement "A stored session is replayed by the browser family that earned it".

**Migration**: None for callers. A read of a domain with a session from a browser tier starts at the browser tiers as before.

### Requirement: FlareSolverr persists returned cookies unconditionally

**Reason**: The FlareSolverr tier is deleted. The patched-browser tiers from `enhance-web-search-tier-ladder` clear the same challenges and replay the stored session themselves.

**Migration**: None for callers. Session records stored by the FlareSolverr tier before this change are not supported, because there is no existing data to keep until the first real customer deployment. Owner answer 73.1 of 2026-10-06 confirms that the data in today's development stores is disposable.

## ADDED Requirements

### Requirement: A stored session is replayed by the browser family that earned it

The store SHALL record which tier produced a session, and the orchestrator SHALL use that producer to choose where the chain restarts. A session produced by a browser tier SHALL send the read to the browser tiers, and SHALL be replayed only by a tier of the same browser family.

#### Scenario: Stored login captured by a browser

- **WHEN** a read targets a domain whose stored session was produced by a browser tier
- **THEN** the read starts at the browser tiers
