## ADDED Requirements

### Requirement: AscendAgent validates JWTs as an OAuth2 resource server

AscendAgent SHALL act as an OAuth2 resource server: every request to a protected endpoint MUST carry an `Authorization: Bearer <JWT>` header, and the JWT SHALL be validated (signature via the issuer's JWKS, `iss`, `exp`, `nbf`) against the OIDC issuer configured at `spring.security.oauth2.resourceserver.jwt.issuer-uri`. Requests with a missing, expired, malformed, or wrongly-signed token SHALL be rejected with HTTP 401. The validation logic SHALL contain no issuer-specific code beyond the role-claim mapping, so that swapping Keycloak for any OIDC-compliant identity provider (Entra ID, Google, Auth0) requires only an issuer-uri configuration change.

#### Scenario: Request without a token is rejected

- **WHEN** `POST /api/v1/ai/prompt` is called with no `Authorization` header and the agent runs in its default (non-dev) posture
- **THEN** the response status is 401
- **AND** no chat processing, history write, or downstream call occurs

#### Scenario: Request with a valid token is accepted

- **WHEN** `POST /api/v1/ai/prompt` is called with a bearer JWT signed by the configured issuer, unexpired, and carrying the `USER` role
- **THEN** the request proceeds to the chat pipeline and returns a non-401/403 status

#### Scenario: Expired or wrongly-signed token is rejected

- **WHEN** the bearer JWT is expired, or signed by a key not published in the configured issuer's JWKS
- **THEN** the response status is 401

### Requirement: Endpoint authorization matrix with USER and ADMIN roles

AscendAgent SHALL enforce role-based authorization in the security filter chain. Roles SHALL be mapped from the token's `realm_access.roles` claim when present, else a top-level `roles` claim, to Spring authorities `ROLE_USER` / `ROLE_ADMIN`. The matrix SHALL be: `POST /api/v1/ai/prompt` and `POST /api/v1/ingestion/upload` require `USER` or `ADMIN`; `POST /api/v1/ingestion/run` requires `ADMIN`; any other non-public endpoint requires authentication. A caller with a valid token but an insufficient role SHALL receive HTTP 403.

#### Scenario: USER can chat and upload

- **WHEN** a token carrying only the `USER` role calls `POST /api/v1/ai/prompt` and `POST /api/v1/ingestion/upload`
- **THEN** both requests are authorized (no 401/403)

#### Scenario: USER cannot trigger ingestion run

- **WHEN** a token carrying only the `USER` role calls `POST /api/v1/ingestion/run`
- **THEN** the response status is 403
- **AND** no ingestion run is started

#### Scenario: ADMIN can trigger ingestion run

- **WHEN** a token carrying the `ADMIN` role calls `POST /api/v1/ingestion/run`
- **THEN** the request is authorized and the ingestion run starts

### Requirement: Public infrastructure and documentation endpoints under the secured posture

Under the secured posture, AscendAgent SHALL permit unauthenticated access ONLY to: `/actuator/health`, `/actuator/prometheus`, `/v3/api-docs/**`, `/swagger-ui/**`, and `/swagger-ui.html`. All other actuator endpoints SHALL remain unavailable to unauthenticated callers. Swagger UI pages SHALL load without a token, but API calls issued from Swagger's "Try it out" SHALL be subject to the same 401/403 rules as any other client.

#### Scenario: Health and metrics scrape without a token

- **WHEN** `GET /actuator/health` and `GET /actuator/prometheus` are called with no credentials
- **THEN** both return 200

#### Scenario: Swagger UI loads but cannot call protected endpoints

- **WHEN** `GET /swagger-ui.html` is fetched with no credentials, and then a prompt request is issued from the UI without a bearer token
- **THEN** the UI page returns 200
- **AND** the prompt request returns 401

### Requirement: Dev profile preserves the open local workflow

When the Spring profile `dev` is active, AscendAgent SHALL permit all requests without a token and SHALL synthesize an identity from `app.user.default-id` carrying both `USER` and `ADMIN` roles, so local single-user runs and the Bruno collection work without an identity provider. The agent SHALL log a WARN at startup stating that authentication is disabled. The default and `docker` postures SHALL require JWTs. The legacy `app.security.enabled` flag and the `app.security.user` HTTP Basic block SHALL be removed.

#### Scenario: Dev profile accepts tokenless requests

- **WHEN** the agent starts with profile `dev` and `POST /api/v1/ai/prompt` is called with no `Authorization` header
- **THEN** the request succeeds and is processed under the `app.user.default-id` identity
- **AND** the startup log contains a WARN that security is disabled

#### Scenario: HTTP Basic path is gone

- **WHEN** the agent starts in any posture
- **THEN** setting `app.security.enabled` or `app.security.user.*` has no effect (properties no longer exist)
- **AND** no in-memory Basic user is registered
