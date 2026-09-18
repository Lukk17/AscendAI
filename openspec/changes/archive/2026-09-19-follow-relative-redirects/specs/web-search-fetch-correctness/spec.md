## MODIFIED Requirements

### Requirement: SSRF guard re-validated on every redirect hop

The SSRF safety check SHALL be enforced at the transport layer, not only at the API edge. The in-process fetch
tiers SHALL NOT follow redirects blindly: automatic redirect following is disabled and each redirect `Location`
SHALL be re-validated with the same private, loopback, link-local and metadata-IP rules before that hop is
fetched, up to a bounded hop count. The re-validation SHALL happen before each hop is fetched rather than by
inspecting a response history afterwards, because the tier follows the chain itself, one request at a time, and no
history of hops it did not follow exists to inspect. A `Location` that is a relative reference, whether
root-relative, path-relative or protocol-relative, SHALL first be resolved against the URL of the hop that
returned it, as RFC 9110 section 10.2.2 requires, and the resolved absolute URL SHALL then face exactly the same
validation a `Location` that was absolute to begin with faces. The tiers that fetch outside this process,
FlareSolverr and Crawlee, SHALL be validated before dispatch, which is the only check available for them.

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

#### Scenario: Out-of-process tier dispatch

- **WHEN** a read is dispatched to FlareSolverr or Crawlee
- **THEN** the target URL is validated before dispatch
- **AND** the redirect hops those tiers take internally are accepted as residual risk, since they are not observable from this process
