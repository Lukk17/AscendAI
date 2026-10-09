## ADDED Requirements

### Requirement: One realm serves every customer, separated by the tenant claim

Every customer of a company deployment SHALL be served by the one realm `ascend-ai` and the one issuer of `add-keycloak-login`, rather than by a realm or an issuer of their own. Customer separation SHALL be expressed by the `tenant` claim, never by a realm boundary. The realm export SHALL carry a protocol mapper emitting the `tenant` user attribute as the `tenant` claim.

#### Scenario: Two customers share one issuer

- **WHEN** two people belonging to two different customers sign in and present their access tokens to ascend-ai-agent
- **THEN** both tokens carry the same `iss` value, that of the `ascend-ai` realm
- **AND** both are validated against the same JWKS with no per-customer issuer configuration
- **AND** their resolved identities carry different `tenant` values

### Requirement: Groups are administered in Keycloak

Realm groups SHALL be the only source of a caller's group membership. An administrator SHALL create groups in the `ascend-ai` realm and assign people to them, and a group protocol mapper in the realm export SHALL emit the caller's group names into the access token as an array claim. No group membership SHALL be read from any external directory, and no group claim SHALL be imported from any upstream identity provider.

Group names SHALL satisfy the principal character set, so that every group can be minted into a principal, and the administrator runbook SHALL state that constraint.

#### Scenario: An administrator grants access by group membership

- **WHEN** an administrator creates the realm group `policy-readers`, adds a person to it, and that person obtains a new access token
- **THEN** the token's group claim lists `policy-readers`
- **AND** the resolved principal set contains `local:group:policy-readers`

#### Scenario: Removing a person from a group removes the principal

- **WHEN** an administrator removes that person from `policy-readers` and the person obtains a new access token
- **THEN** the token's group claim does not list `policy-readers`
- **AND** the resolved principal set does not contain `local:group:policy-readers`

### Requirement: The realm export carries the company additions and no stored provider token

The realm export of `add-keycloak-login` SHALL gain, through this change: the `tenant` protocol mapper, realm groups with the group protocol mapper, a disabled brokered-provider template entry carrying the tenant-stamp mapper and no mapper importing an upstream authorization claim, and an organization template for Keycloak Organizations. The export SHALL NOT contain any brokered provider configured to store provider tokens. A replacement issuer used through the escape hatch of `add-keycloak-login` SHALL additionally emit a `tenant` claim (defaulting to `default` when absent) and a group claim carrying the caller's group names.

#### Scenario: Company additions are present and stored tokens are off

- **WHEN** the production export is inspected after this change
- **THEN** it shows the `tenant` mapper, the group mapper, the disabled template entry and the organization template
- **AND** no provider has token storage enabled

#### Scenario: A replacement issuer with no group claim resolves the tenant floor

- **WHEN** the configuration names an issuer whose tokens carry no group claim
- **THEN** the agent logs the gap at startup and every resolved principal set is exactly `tenant:everyone:{tenantId}`
- **AND** this outcome is documented in `docs/SECURITY.md` as a deployment shape rather than presented as a fault

### Requirement: The development overlay carries the test tenants

The development overlay of `add-keycloak-login` SHALL gain the realm group `dev-all` with the seeded development user in it, and the users of the test tenants `e2e-acme`, `e2e-globex` and `e2e-soul`, including the group users the company specs need. None of it SHALL be part of the production export.

#### Scenario: Test tenant users carry their tenant

- **WHEN** a token is obtained for `e2e-admin-globex`
- **THEN** it carries `tenant` `e2e-globex` and the roles `USER` and `ADMIN`

#### Scenario: The test tenants are absent from a production import

- **WHEN** a production deployment imports only the production export
- **THEN** no user of `e2e-acme`, `e2e-globex` or `e2e-soul` exists and no `dev-all` group exists
