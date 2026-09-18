## ADDED Requirements

### Requirement: The validated address is the address connected to

An in-process fetch SHALL connect to an address that was validated by the same name resolution that authorised it.
One resolution SHALL both check every returned address against the private, loopback, link-local, multicast and
reserved rules and supply those addresses to the transport, so no second resolution stands between the check and
the connection. A host that resolves to no public address SHALL NOT be connected to at all.

A URL whose host is already an IP literal SHALL be checked against the same address rules, and SHALL carry no pin,
because there is no name there for a second resolution to answer differently.

This applies to the initial URL and to every redirect hop the in-process tier follows. The tiers that fetch outside
this process, FlareSolverr and Crawlee, and the tiers that fetch through the shared browser, Playwright and NoVNC,
SHALL keep pre-dispatch validation, which remains the only check available for them, and the residual DNS-rebinding
window for those four tiers SHALL be recorded as an accepted risk.

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

#### Scenario: A host with several public addresses

- **WHEN** a host resolves to more than one address and all of them are public
- **THEN** every one of them is offered to the transport as a permitted connection target
