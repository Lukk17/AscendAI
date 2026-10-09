## ADDED Requirements

### Requirement: Keycloak is the platform's identity layer, one realm and one issuer

The platform SHALL run a self-hosted Keycloak as its identity provider in every deployment posture, development and production alike. A single realm, `ascend-ai`, SHALL be the only token issuer ascend-ai-agent validates against. ascend-ai-agent SHALL require no issuer registry, no per-request issuer resolution ahead of token validation, and no more than one configured `issuer-uri`.

#### Scenario: A production deployment runs the same realm shape as development

- **WHEN** the compose stack is brought up locally and when an operator deploys the same realm export to a production Keycloak
- **THEN** the realm name, roles, clients, protocol mappers and password policy are identical in both
- **AND** the only differences are the Keycloak start command, the hostname and TLS configuration, and the absence of the development overlay in production

### Requirement: Password sign-in is the default authentication path

The platform SHALL support a Keycloak account with a password as its default and primary way for a person to sign in. The person SHALL enter their password on Keycloak's own login page, and the application SHALL receive an authorization code which it exchanges for tokens using PKCE. The application SHALL NEVER receive, hold or transmit the person's password.

The direct access grant, in which the application itself collects the password and posts it to the token endpoint, SHALL NOT be enabled on any client a person uses, and SHALL NOT be treated as a way of providing password sign-in.

#### Scenario: A person signs in with a password

- **WHEN** an administrator creates an account with a password and that person signs in through the application
- **THEN** they are taken to Keycloak's own login page, and after entering their password the application receives an authorization code
- **AND** exchanging that code with PKCE yields an access token ascend-ai-agent accepts on a protected endpoint

#### Scenario: The application never sees the password

- **WHEN** a person signs in through the `ascend-flutter` client
- **THEN** no request issued by the application carries the person's password
- **AND** the client's configuration has direct access grants disabled

### Requirement: Keycloak runs as a provisioned docker-compose service

The compose stack SHALL include a `keycloak` service that imports the checked-in realm export (`keycloak/realm-ascend-ai.json`) at startup, backed by the external PostgreSQL prerequisite (dedicated `keycloak` database). Keycloak SHALL be a separate service on its own host address and port, host port 8180 mapped to container port 8080, and SHALL NOT be routed under a path of any gateway in front of ascend-ai-agent. The development posture SHALL run `start-dev --import-realm`, and the production posture SHALL run `start --import-realm` with `KC_HOSTNAME` set to the public Keycloak address. After `docker compose up`, the realm SHALL be usable with zero manual console configuration, and the service SHALL expose a healthcheck the ascend-ai-agent's `depends_on` can gate on. The checked-in export SHALL be the source of truth for realm configuration.

#### Scenario: Fresh stack yields a working issuer

- **WHEN** the compose stack is brought up on a clean environment
- **THEN** the OIDC discovery document at `<keycloak-url>/realms/ascend-ai/.well-known/openid-configuration` returns 200 with a JWKS URI
- **AND** no manual Keycloak configuration step was performed

### Requirement: The realm export provisions a production identity system for one tenant

The realm export SHALL be treated as the provisioning of a real system rather than as a test fixture, and SHALL define all of the following: realm `ascend-ai`, realm roles `USER` and `ADMIN` with `USER` as the realm default role granted to every new account, a public client `ascend-flutter` configured for the authorization code flow with PKCE (`S256`), no client secret, direct access grants disabled, and exactly the redirect URIs `http://127.0.0.1/callback` (accepted on any port), `com.lukk.ascend:/callback` and, when the operator sets `ASCEND_CHAT_WEB_URL`, that address followed by `/callback`, with no wildcard redirect URI, a realm password policy setting a minimum length and enabling brute-force detection, a protocol mapper emitting the `email` claim, explicit realm SSO session and access token lifetimes, a confidential client `ascend-openclaw-host` with only the client credentials grant, whose secret only the `channels` containers of `add-openclaw-plugin-host` hold, with a client scope `channel.relay` assigned to it and to no other client, and a confidential client `ascend-agent-directory` holding the service account role `view-users` of `realm-management` and nothing else. The export SHALL NOT contain a seeded human user or a client with direct access grants enabled.

#### Scenario: The application client cannot be used for a password grant

- **WHEN** the `ascend-flutter` client configuration in the production export is inspected
- **THEN** it is a public client with the authorization code grant and PKCE method `S256` required, and no client secret
- **AND** direct access grants are disabled

#### Scenario: The application client accepts the loopback address on any port

- **WHEN** an authorization request against `ascend-flutter` names the redirect URI `http://127.0.0.1:<port>/callback` with a random free port
- **THEN** Keycloak accepts it and returns the code to that port

#### Scenario: The application client refuses a redirect it does not list

- **WHEN** an authorization request against `ascend-flutter` names `http://localhost:8080/callback` or `https://evil.example/callback`
- **THEN** Keycloak refuses the request and issues no code

#### Scenario: A password policy is provisioned rather than left to an operator

- **WHEN** the export is inspected
- **THEN** the realm carries an explicit password policy with a minimum length and brute-force detection enabled

#### Scenario: Session and token lifetimes are checked in rather than defaulted

- **WHEN** the export is inspected
- **THEN** the realm SSO session lifetime and the access token lifetime carry explicit values
- **AND** those values are the ones the staleness disclosure in `docs/SECURITY.md` states

#### Scenario: The channel scope and the directory role are held by one client each

- **WHEN** the export is inspected
- **THEN** `ascend-openclaw-host` is a confidential client with only the client credentials grant and the client scope `channel.relay`
- **AND** no other client holds `channel.relay`
- **AND** `ascend-agent-directory` holds the service account role `view-users` of `realm-management` and no other role

#### Scenario: The production export carries no seeded human account

- **WHEN** the production export is imported into a clean Keycloak
- **THEN** the realm contains no human user account
- **AND** no client in the realm accepts a password grant

### Requirement: Development-only realm content lives in a separate overlay

The seeded development user, the e2e users of tenant `default` (`e2e-user`, `e2e-user-2`, `e2e-admin`), and any client permitting a password grant for the Bruno collection and the e2e suite SHALL live in a development overlay imported only in the development compose posture, and SHALL NOT be part of the production realm export. The overlay SHALL also carry the client `ascend-openclaw-host` with a development secret. The e2e users SHALL share one password read at import from `${E2E_USER_PASSWORD}`. The password-grant clients SHALL exist only so the test suites can obtain a token without driving a browser, and SHALL NOT be presented as the way password sign-in works.

#### Scenario: The development overlay provisions the e2e identities

- **WHEN** the development compose posture is brought up and a token is obtained for `e2e-admin`
- **THEN** the JWT contains `sub`, `preferred_username`, `email` and `realm_access.roles` including `USER` and `ADMIN`
- **AND** the agent resolves its identity in tenant `default`

#### Scenario: The overlay is absent from a production import

- **WHEN** a production deployment imports only the production export
- **THEN** the seeded users are absent
- **AND** the e2e suite's token-acquisition step fails rather than succeeding against a production realm

### Requirement: Validating a different issuer directly remains supported as an escape hatch

The platform SHALL keep the token issuer replaceable by configuration for a deployment that validates a different provider's tokens directly: pointing `spring.security.oauth2.resourceserver.jwt.issuer-uri` at any OIDC-compliant issuer, registering an equivalent client there, and mapping its email claim name under `app.identity.claims` SHALL be sufficient, with no ascend-ai-agent code change. This SHALL be documented as an escape hatch rather than as the normal deployment. The claims contract a replacement issuer must satisfy SHALL be: a stable subject claim for storage partitioning, an email claim, and a role claim in one of the shapes the converter accepts. `docs/SECURITY.md` SHALL document the swap procedure and this contract.

#### Scenario: Issuer swap requires configuration only

- **WHEN** the issuer-uri is repointed to a different OIDC-compliant identity provider that issues tokens satisfying the claims contract, and its email claim name is mapped under `app.identity.claims`
- **THEN** ascend-ai-agent validates those tokens and resolves identity, roles and email without any code change
