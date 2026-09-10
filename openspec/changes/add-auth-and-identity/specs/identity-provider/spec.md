## ADDED Requirements

### Requirement: Keycloak is the platform's identity layer, one realm and one issuer

The platform SHALL run a self-hosted Keycloak as its identity provider in every deployment posture, development and production alike. A single realm, `ascend-ai`, SHALL be the only token issuer ascend-ai-agent validates against, and every customer SHALL be served by that one issuer rather than by an issuer of their own. Customer separation SHALL be expressed by the `tenant` claim, never by a realm boundary. ascend-ai-agent SHALL therefore require no issuer registry, no per-request issuer resolution ahead of token validation, and no more than one configured `issuer-uri`.

#### Scenario: Two customers share one issuer

- **WHEN** two people belonging to two different customers sign in and present their access tokens to ascend-ai-agent
- **THEN** both tokens carry the same `iss` value, that of the `ascend-ai` realm
- **AND** both are validated against the same JWKS with no per-customer issuer configuration
- **AND** their resolved identities carry different `tenant` values

#### Scenario: A production deployment runs the same realm shape as development

- **WHEN** the compose stack is brought up locally and when an operator deploys the same realm export to a production Keycloak
- **THEN** the realm name, roles, groups, client, protocol mappers, and password policy are identical in both
- **AND** the only differences are the Keycloak start command, the hostname and TLS configuration, and the absence of the development overlay in production

### Requirement: Password sign-in is the default authentication path

The platform SHALL support a Keycloak account with a password as its default and primary way for a person to sign in, and that path SHALL work with no brokered identity provider configured anywhere in the realm. The person SHALL enter their password on Keycloak's own login page, and the application SHALL receive an authorization code which it exchanges for tokens using PKCE. The application SHALL NEVER receive, hold, or transmit the person's password.

The direct access grant, in which the application itself collects the password and posts it to the token endpoint, SHALL NOT be enabled on any client a customer uses, and SHALL NOT be treated as a way of providing password sign-in. Enabling password sign-in SHALL NOT be understood to mean enabling that grant.

#### Scenario: A person signs in with a password and no identity provider exists

- **WHEN** an administrator creates an account with a password in a realm that has no brokered identity provider configured, and that person signs in through the application
- **THEN** they are taken to Keycloak's own login page, and after entering their password the application receives an authorization code
- **AND** exchanging that code with PKCE yields an access token ascend-ai-agent accepts on a protected endpoint

#### Scenario: The application never sees the password

- **WHEN** a person signs in through the `ascend-flutter` client
- **THEN** no request issued by the application carries the person's password
- **AND** the client's configuration has direct access grants disabled

### Requirement: Groups are administered in Keycloak

Realm groups SHALL be the only source of a caller's group membership. An administrator SHALL create groups in the `ascend-ai` realm and assign people to them, and a group protocol mapper SHALL emit the caller's group names into the access token as an array claim. No group membership SHALL be read from any external directory, and no group claim SHALL be imported from any upstream identity provider.

Group names SHALL satisfy the principal character set, so that every group can be minted into a principal, and the administrator runbook SHALL state that constraint.

#### Scenario: An administrator grants access by group membership

- **WHEN** an administrator creates the realm group `policy-readers`, adds a person to it, and that person obtains a new access token
- **THEN** the token's group claim lists `policy-readers`
- **AND** the resolved principal set contains `local:group:policy-readers`

#### Scenario: Removing a person from a group removes the principal

- **WHEN** an administrator removes that person from `policy-readers` and the person obtains a new access token
- **THEN** the token's group claim does not list `policy-readers`
- **AND** the resolved principal set does not contain `local:group:policy-readers`

### Requirement: Keycloak runs as a provisioned docker-compose service

The compose stack SHALL include a `keycloak` service that imports the checked-in realm export (`keycloak/realm-ascend-ai.json`) at startup, backed by the external PostgreSQL prerequisite (dedicated `keycloak` database). After `docker compose up`, the realm SHALL be usable with zero manual console configuration, and the service SHALL expose a healthcheck the ascend-ai-agent's `depends_on` can gate on. The checked-in export SHALL be the source of truth for realm configuration, and a console edit that is not reflected back into the export SHALL be understood as lost at the next clean deploy.

#### Scenario: Fresh stack yields a working issuer

- **WHEN** the compose stack is brought up on a clean environment
- **THEN** the OIDC discovery document at `<keycloak-url>/realms/ascend-ai/.well-known/openid-configuration` returns 200 with a JWKS URI
- **AND** no manual Keycloak configuration step was performed

### Requirement: The realm export provisions a production identity system

The realm export SHALL be treated as the provisioning of a real system rather than as a test fixture, and SHALL define all of the following: realm `ascend-ai`; realm roles `USER` and `ADMIN`, with `USER` as the realm default role granted to every new account; a public client `ascend-flutter` configured for authorization-code flow with PKCE (`S256`), no client secret, and direct access grants disabled; a realm password policy setting a minimum length and enabling brute-force detection; realm groups and a group protocol mapper emitting them into the access token; protocol mappers emitting the `tenant` claim and the `email` claim; explicit realm SSO session and access token lifetimes, because they bound how stale a group membership can be; and a disabled brokered-provider template entry carrying the tenant-stamp mapper and no mapper importing an upstream authorization claim. The export SHALL NOT contain a seeded human user, a client with direct access grants enabled, or any brokered provider configured to store provider tokens.

#### Scenario: The application client cannot be used for a password grant

- **WHEN** the `ascend-flutter` client configuration in the production export is inspected
- **THEN** it is a public client with authorization-code grant and PKCE method `S256` required, and no client secret
- **AND** direct access grants are disabled

#### Scenario: A password policy is provisioned rather than left to an operator

- **WHEN** the export is inspected
- **THEN** the realm carries an explicit password policy with a minimum length and brute-force detection enabled

#### Scenario: Session and token lifetimes are checked in rather than defaulted

- **WHEN** the export is inspected
- **THEN** the realm SSO session lifetime and the access token lifetime carry explicit values
- **AND** those values are the ones the staleness disclosure in `docs/SECURITY.md` states

#### Scenario: The production export carries no seeded human account

- **WHEN** the production export is imported into a clean Keycloak
- **THEN** the realm contains no human user account
- **AND** no client in the realm accepts a password grant

### Requirement: Development-only realm content lives in a separate overlay

The seeded test user, the `dev-all` realm group, and any client permitting a password grant for the Bruno collection and the e2e suite SHALL live in a development overlay imported only in the development compose posture, and SHALL NOT be part of the production realm export. The overlay's seeded user SHALL carry both roles, an email address, and membership of `dev-all`, so the e2e suite remains deterministic. The password-grant client SHALL exist only so the test suites can obtain a token without driving a browser, and SHALL NOT be presented as the way password sign-in works.

#### Scenario: The development overlay provisions the e2e identity

- **WHEN** the development compose posture is brought up and a token is obtained for the seeded test user
- **THEN** the JWT contains `sub`, `preferred_username`, `email`, a group claim listing `dev-all`, a `tenant` claim with value `default`, and `realm_access.roles` including `USER` and `ADMIN`

#### Scenario: The overlay is absent from a production import

- **WHEN** a production deployment imports only the production export
- **THEN** the seeded test user and the `dev-all` group are absent
- **AND** the e2e suite's token-acquisition step fails rather than succeeding against a production realm

### Requirement: Validating a different issuer directly remains supported as an escape hatch

The platform SHALL keep the token issuer replaceable by configuration for a deployment that validates a different provider's tokens directly: pointing `spring.security.oauth2.resourceserver.jwt.issuer-uri` at any OIDC-compliant issuer, registering an equivalent client there, and mapping its claim names under `app.identity.claims` SHALL be sufficient, with no ascend-ai-agent code change. This SHALL be documented as an escape hatch rather than as the normal deployment. The claims contract a replacement issuer must satisfy SHALL be: a stable subject claim for storage partitioning; an email claim; a role claim in one of the shapes the converter accepts; a `tenant` claim, defaulting to `default` when absent; and a group claim carrying the caller's group names. `docs/SECURITY.md` SHALL document the swap procedure, this contract, and the fact that it is not the normal deployment.

#### Scenario: Issuer swap requires configuration only

- **WHEN** the issuer-uri is repointed to a different OIDC-compliant identity provider that issues tokens satisfying the claims contract, and its claim names are mapped under `app.identity.claims`
- **THEN** ascend-ai-agent validates those tokens and resolves identity, roles, email, and group principals without any code change

#### Scenario: A replacement issuer with no group claim resolves the tenant floor

- **WHEN** the configuration names an issuer whose tokens carry no group claim
- **THEN** the agent logs the gap at startup and every resolved principal set is exactly `tenant:everyone:{tenantId}`
- **AND** this outcome is documented in `docs/SECURITY.md` as a deployment shape rather than presented as a fault
