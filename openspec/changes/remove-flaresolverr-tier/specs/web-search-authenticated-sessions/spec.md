## MODIFIED Requirements

### Requirement: Captured session includes full browser storage state

When a session is captured by the NoVNC login monitor, the service SHALL persist the full Playwright `storage_state`, meaning cookies including httpOnly cookies AND per-origin localStorage, not only `context.cookies()`. The persisted blob SHALL be sufficient to reconstruct an authenticated browser context. The Playwright, Patchright and Camoufox tiers replay a stored session and do not write one back.

#### Scenario: Human logs in to a site via NoVNC

- **WHEN** a user completes a login for `linkedin.com` in the NoVNC browser
- **THEN** the stored session for that domain contains the httpOnly auth cookies (e.g. `li_at`)
- **AND** it contains the page's localStorage entries captured via `context.storage_state()`

## REMOVED Requirements

### Requirement: FlareSolverr persists returned cookies unconditionally

**Reason**: The FlareSolverr tier is deleted. The patched-browser tiers from `enhance-web-search-tier-ladder` clear the same challenges and replay the stored session themselves.

**Migration**: None for callers. A stored record with `produced_by` `3-flaresolverr` is replayed by the browser tiers.
