## ADDED Requirements

### Requirement: Keycloak runs as a provisioned docker-compose service

The compose stack SHALL include a `keycloak` service that imports a checked-in realm export (`keycloak/realm-ascend-ai.json`) at startup, backed by the external PostgreSQL prerequisite (dedicated `keycloak` database). After `docker compose up`, the realm SHALL be usable with zero manual console configuration, and the service SHALL expose a healthcheck the AscendAgent's `depends_on` can gate on. The checked-in export SHALL be the source of truth for realm configuration; manual console edits are not part of the contract.

#### Scenario: Fresh stack yields a working issuer

- **WHEN** the compose stack is brought up on a clean environment
- **THEN** the OIDC discovery document at `<keycloak-url>/realms/ascend-ai/.well-known/openid-configuration` returns 200 with a JWKS URI
- **AND** no manual Keycloak configuration step was performed

### Requirement: Realm export provisions the client, roles, and test user

The realm export SHALL define: realm `ascend-ai`; realm roles `USER` and `ADMIN`; a public client `ascend-flutter` configured for authorization-code flow with PKCE (`S256`) and no client secret, with placeholder loopback redirect URIs for the future Flutter app; a `tenant` client protocol mapper emitting the `tenant` claim (value `default` locally); a `groups` client protocol mapper emitting the realm groups the user belongs to as a full-path-free list of group names; an `email` mapper emitting the user's address; and a seeded local test user carrying both roles, an email address, and membership of at least one realm group, for the e2e suite and Bruno collection.

#### Scenario: Token from the seeded user carries the contract claims

- **WHEN** a token is obtained from the `ascend-ai` realm for the seeded test user
- **THEN** the JWT contains `sub`, `preferred_username`, `email`, a `groups` claim listing the seeded user's realm groups, a `tenant` claim with value `default`, and `realm_access.roles` including `USER` and `ADMIN`

#### Scenario: Flutter client enforces PKCE

- **WHEN** the `ascend-flutter` client configuration is inspected
- **THEN** it is a public client with authorization-code grant and PKCE method `S256` required, and no client secret

### Requirement: Identity provider is swappable via issuer-uri

The platform SHALL treat the token issuer as replaceable by configuration: pointing `spring.security.oauth2.resourceserver.jwt.issuer-uri` at any OIDC-compliant issuer, registering an equivalent client there, and mapping its claim names under `app.identity.claims` SHALL be sufficient, with no AscendAgent code change. The claims contract a replacement issuer must satisfy SHALL be: a stable subject claim for storage partitioning; a directory-subject claim carrying the provider's immutable directory identifier (`oid` for Microsoft Entra ID, `sub` for Google); an email claim; a role claim in one of the shapes the converter accepts; a `tenant` claim, defaulting to `default` when absent; and either a complete group claim or a directory provider configured under `app.identity.directories` that can answer transitive membership for the directory subject. `docs/SECURITY.md` SHALL document the swap procedure and this contract.

#### Scenario: Issuer swap requires configuration only

- **WHEN** the issuer-uri is repointed to a different OIDC-compliant identity provider that issues tokens satisfying the claims contract, and its claim names are mapped under `app.identity.claims`
- **THEN** AscendAgent validates those tokens and resolves identity, roles, directory subject, email, and group principals without any code change

#### Scenario: A replacement issuer missing the group source is rejected at startup

- **WHEN** the configuration names an issuer whose tokens carry no group claim and configures no directory adapter under `app.identity.directories`
- **THEN** the agent logs the gap at startup and every resolved principal set is exactly `tenant:everyone:{tenantId}`
- **AND** this outcome is documented in `docs/SECURITY.md` as the no-directory deployment shape rather than presented as a fault

### Requirement: Directory lookups are configured separately from the token issuer

The platform SHALL configure the directory used for group membership independently of the token issuer, so that a customer signing in through one vendor and storing files at another is a configuration rather than a code fork. `app.identity.directories` SHALL be a list of adapters, each naming a provider kind (`microsoft-graph`, `google-directory`), the principal namespace its groups mint into, and its own credentials. An empty list SHALL be valid and SHALL mean the token's group claim is the only source of groups. Adding support for a directory vendor beyond the two shipped adapters SHALL be understood as new code, and the documentation SHALL NOT claim otherwise.

#### Scenario: Split-provider customer resolves groups from both sides

- **WHEN** the token issuer is Microsoft Entra ID, a `google-directory` adapter is configured, and the caller has an `ACTIVE` identity link carrying a Google account id
- **THEN** the resolved principal set contains `entra:group:*` principals from the Entra side and `google:group:*` principals from the Google side

#### Scenario: No directory configured is a valid deployment

- **WHEN** `app.identity.directories` is empty and the token carries a complete group claim
- **THEN** the principal set is resolved from the token claim alone and no directory call is made
