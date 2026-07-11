## ADDED Requirements

### Requirement: Keycloak runs as a provisioned docker-compose service

The compose stack SHALL include a `keycloak` service that imports a checked-in realm export (`keycloak/realm-ascend-ai.json`) at startup, backed by the external PostgreSQL prerequisite (dedicated `keycloak` database). After `docker compose up`, the realm SHALL be usable with zero manual console configuration, and the service SHALL expose a healthcheck the AscendAgent's `depends_on` can gate on. The checked-in export SHALL be the source of truth for realm configuration; manual console edits are not part of the contract.

#### Scenario: Fresh stack yields a working issuer

- **WHEN** the compose stack is brought up on a clean environment
- **THEN** the OIDC discovery document at `<keycloak-url>/realms/ascend-ai/.well-known/openid-configuration` returns 200 with a JWKS URI
- **AND** no manual Keycloak configuration step was performed

### Requirement: Realm export provisions the client, roles, and test user

The realm export SHALL define: realm `ascend-ai`; realm roles `USER` and `ADMIN`; a public client `ascend-flutter` configured for authorization-code flow with PKCE (`S256`) and no client secret, with placeholder loopback redirect URIs for the future Flutter app; a `tenant` client protocol mapper emitting the `tenant` claim (value `default` locally); and a seeded local test user carrying both roles for the e2e suite and Bruno collection.

#### Scenario: Token from the seeded user carries the contract claims

- **WHEN** a token is obtained from the `ascend-ai` realm for the seeded test user
- **THEN** the JWT contains `sub`, `preferred_username`, a `tenant` claim with value `default`, and `realm_access.roles` including `USER` and `ADMIN`

#### Scenario: Flutter client enforces PKCE

- **WHEN** the `ascend-flutter` client configuration is inspected
- **THEN** it is a public client with authorization-code grant and PKCE method `S256` required, and no client secret

### Requirement: Identity provider is swappable via issuer-uri

The platform SHALL treat the identity provider as replaceable: pointing `spring.security.oauth2.resourceserver.jwt.issuer-uri` at any OIDC-compliant issuer (Entra ID, Google, Auth0) and registering an equivalent client there SHALL be sufficient — no AscendAgent code change beyond the already-specified tolerant role-claim mapping. `docs/SECURITY.md` SHALL document the swap procedure and the claims contract (`sub`, `preferred_username`, `tenant`, roles) the replacement issuer must satisfy.

#### Scenario: Issuer swap requires configuration only

- **WHEN** the issuer-uri is repointed to a different OIDC-compliant identity provider that issues tokens satisfying the claims contract
- **THEN** AscendAgent validates those tokens and resolves identity and roles without any code change
