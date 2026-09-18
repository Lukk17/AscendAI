## MODIFIED Requirements

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

## ADDED Requirements

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
