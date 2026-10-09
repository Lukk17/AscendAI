## ADDED Requirements

### Requirement: ascend-ai-agent validates JWTs as an OAuth2 resource server

ascend-ai-agent SHALL act as an OAuth2 resource server: every request to a protected endpoint MUST carry an `Authorization: Bearer <JWT>` header, and the JWT SHALL be validated (signature through the issuer's JWKS, `iss`, `exp`, `nbf`) against the OIDC issuer configured at `spring.security.oauth2.resourceserver.jwt.issuer-uri`. Requests with a missing, expired, malformed or wrongly signed token SHALL be rejected with HTTP 401. In the shipped deployment that issuer is the platform's own Keycloak realm `ascend-ai`. The validation logic SHALL contain no issuer-specific code beyond the role-claim mapping, so that a deployment choosing to validate a different OIDC-compliant issuer's tokens directly needs only an issuer-uri configuration change.

#### Scenario: Request without a token is rejected

- **WHEN** `POST /api/v1/ai/prompt` is called with no `Authorization` header and the agent runs in its default (non-dev) posture
- **THEN** the response status is 401
- **AND** no chat processing, history write, or downstream call occurs

#### Scenario: Request with a valid token is accepted

- **WHEN** `POST /api/v1/ai/prompt` is called with a bearer JWT signed by the configured issuer, unexpired, and carrying the `USER` role
- **THEN** the request proceeds to the chat pipeline and returns a status that is neither 401 nor 403

#### Scenario: Expired or wrongly signed token is rejected

- **WHEN** the bearer JWT is expired, or signed by a key not published in the configured issuer's JWKS
- **THEN** the response status is 401

### Requirement: Endpoint authorization matrix with USER and ADMIN roles

ascend-ai-agent SHALL enforce role-based authorization in the security filter chain, not in method annotations, so one place answers which roles reach which paths. Roles SHALL be mapped from the token's `realm_access.roles` claim when present, else a top-level `roles` claim, to Spring authorities `ROLE_USER` and `ROLE_ADMIN`. The scope authorities of the `scope` claim SHALL be kept, and a scope SHALL NOT be a role. The matrix SHALL be: `POST /api/v1/ai/prompt` and `POST /api/v1/ingestion/upload` require `USER` or `ADMIN`, `POST /api/v1/ingestion/run` requires `ADMIN`, every other endpoint present when this change is implemented has an explicit row, and any other non-public endpoint requires authentication. A caller with a valid token but an insufficient role SHALL receive HTTP 403.

#### Scenario: USER can chat and upload

- **WHEN** a token carrying only the `USER` role calls `POST /api/v1/ai/prompt` and `POST /api/v1/ingestion/upload`
- **THEN** both requests are authorized (no 401 or 403)

#### Scenario: USER cannot trigger ingestion run

- **WHEN** a token carrying only the `USER` role calls `POST /api/v1/ingestion/run`
- **THEN** the response status is 403
- **AND** no ingestion run is started

#### Scenario: ADMIN can trigger ingestion run

- **WHEN** a token carrying the `ADMIN` role calls `POST /api/v1/ingestion/run`
- **THEN** the request is authorized and the ingestion run starts

### Requirement: Each later change adds its own matrix rows and no endpoint is left without one

A change that adds endpoints after this change SHALL add its own rows to the authorization matrix, in its own tasks, with a security slice test per row. The build SHALL include a coverage test that lists every request mapping of the agent and fails when a mapping is not named by an explicit row of the matrix, so an administrator endpoint can never fall through to the default rule of merely authenticated. `docs/SECURITY.md` SHALL list the later changes known when this change lands and the rows each one adds.

#### Scenario: An endpoint without a row fails the build

- **WHEN** a later change adds a controller method and no matrix row names its path
- **THEN** the coverage test fails and names that method and path

#### Scenario: A later admin endpoint is closed to a user

- **WHEN** a later change has added the row `ADMIN` only for its administrator endpoint and a token carrying only the `USER` role calls that endpoint
- **THEN** the response status is 403
- **AND** the endpoint's action does not happen

### Requirement: Every 403 of the filter chain is a problem body

Every request that the filter chain refuses because the caller lacks a required role or scope SHALL answer HTTP 403 with the RFC 7807 problem detail of `upgrade-spring-boot-4`: `Content-Type: application/problem+json`, `code` `forbidden`, `type` `https://ascend.ai/errors/forbidden`, and a `detail` that names no user. Every endpoint that a later change adds SHALL use the same body for the same refusal, and no later change SHALL add the code `forbidden` again.

#### Scenario: A user on an administrator path gets the problem body

- **WHEN** a token carrying only the `USER` role calls `POST /api/v1/ingestion/run`
- **THEN** the response is 403 with `Content-Type: application/problem+json`, `code` `forbidden` and `type` `https://ascend.ai/errors/forbidden`

### Requirement: Public infrastructure and documentation endpoints under the secured posture

Under the secured posture, ascend-ai-agent SHALL permit unauthenticated access ONLY to: `/actuator/health` and `/actuator/prometheus` on the internal management port `9918` (the application port `9917` serves no actuator path), `/v3/api-docs/**`, `/swagger-ui/**`, and `/swagger-ui.html`. All other actuator endpoints SHALL remain unavailable to unauthenticated callers. Swagger UI pages SHALL load without a token, but API calls issued from Swagger's "Try it out" SHALL be subject to the same 401 and 403 rules as any other client.

#### Scenario: Health and metrics scrape without a token

- **WHEN** `GET /actuator/health` and `GET /actuator/prometheus` are called with no credentials on the management port
- **THEN** both return 200

#### Scenario: Swagger UI loads but cannot call protected endpoints

- **WHEN** `GET /swagger-ui.html` is fetched with no credentials, and then a prompt request is issued from the UI without a bearer token
- **THEN** the UI page returns 200
- **AND** the prompt request returns 401

### Requirement: Dev profile preserves the open local workflow

When the Spring profile `dev` is active, ascend-ai-agent SHALL permit all requests without a token, except requests to `/api/v1/channel-host/**`, which SHALL still require the scope `channel.relay`, and SHALL synthesize an identity from `app.user.default-id` with tenant `default` and both `USER` and `ADMIN` roles, so local single-user runs work without an identity provider. The synthesized identity SHALL pass through the same identity extension points as a token identity. The agent SHALL log a WARN at startup stating that authentication is disabled. The default and `docker` postures SHALL require JWTs. The legacy `app.security.enabled` flag and the `app.security.user` HTTP Basic block SHALL be removed, together with their `@ConfigurationProperties` binding and the `SECURITY_ENABLED`, `SECURITY_USERNAME` and `SECURITY_PASSWORD` environment variables they read.

#### Scenario: Dev profile accepts tokenless requests

- **WHEN** the agent starts with profile `dev` and `POST /api/v1/ai/prompt` is called with no `Authorization` header
- **THEN** the request succeeds and is processed under the `app.user.default-id` identity in tenant `default`
- **AND** the startup log contains a WARN that security is disabled

#### Scenario: The channel host path stays closed under dev

- **WHEN** the agent runs with profile `dev` and `/api/v1/channel-host/**` is called with no token
- **THEN** the response status is 403

#### Scenario: HTTP Basic path is gone

- **WHEN** the agent starts in any posture
- **THEN** setting `app.security.enabled` or `app.security.user.*` has no effect (the properties no longer exist)
- **AND** no in-memory Basic user is registered

### Requirement: A public deployment refuses to start without login

When the Spring profile `production` is active, ascend-ai-agent SHALL refuse to start, with a non-zero exit before it accepts a connection, when the `dev` profile is also active, when `spring.security.oauth2.resourceserver.jwt.issuer-uri` is not set or blank, or when `SERVICE_AUTH_TOKEN` is not set or blank. The agent SHALL have one production startup guard (owner answer 89.10 of 2026-10-08): `application-production.yaml` SHALL set the issuer and the service token from their environment variables with no default, so an unset variable stops start-up with an error naming the missing placeholder, and one guard class SHALL run every registered production start-up check for what a placeholder cannot express (the `dev` profile, a blank issuer, a blank token), each refusal written as one ERROR line that names the check or the property and never a value. A later change SHALL add a placeholder or a check to this guard and SHALL NOT add a guard of its own. No environment variable or flag SHALL turn the guard off. Without the `production` profile neither the file nor the guard SHALL be read.

#### Scenario: Dev profile in a public deployment

- **WHEN** the agent starts with the profiles `docker,production,dev`
- **THEN** it exits non-zero before accepting a connection
- **AND** the ERROR line names the `dev` profile

#### Scenario: No issuer in a public deployment

- **WHEN** the agent starts with the profiles `docker,production` and an empty issuer-uri
- **THEN** it exits non-zero before accepting a connection

#### Scenario: An unset service token in a public deployment

- **WHEN** the agent starts with the profiles `docker,production`, an issuer-uri and `SERVICE_AUTH_TOKEN` unset
- **THEN** it exits non-zero before accepting a connection with an error naming the missing placeholder
- **AND** no output of the start-up prints a credential value

#### Scenario: A complete public deployment starts

- **WHEN** the agent starts with the profiles `docker,production`, an issuer-uri and a service token
- **THEN** it starts and requires a JWT on every protected endpoint

### Requirement: Authentication is covered by end-to-end tests against the live stack

The ascend-ai-agent e2e suite SHALL carry a spec for every caller-visible behaviour of this change, run against the secured stack with tokens of the development overlay's e2e users of tenant `default`. A behaviour that an HTTP status, a response body or persisted state can show SHALL be checked by a deterministic Bruno test that calls no AI model. Pass criteria SHALL be observable behaviour only, never a log line. The development overlay SHALL carry the e2e users `e2e-user`, `e2e-user-2` and `e2e-admin` of tenant `default` and SHALL NOT be part of the production export. Once this change lands every end-to-end run SHALL use these users, and an existing spec SHALL be updated in place for the secured posture rather than replaced by a new spec. The role matrix spec SHALL hold one request per matrix row and caller, and each later change SHALL add the rows of its endpoints to it in place.

#### Scenario: Token and claims checks need no model

- **WHEN** the token and claims spec runs against the live stack
- **THEN** the discovery document answers 200 with a `jwks_uri`, each e2e user's token decodes to the seeded `sub`, `email` and roles, a wrong password answers 401 `invalid_grant`, and a password grant on `ascend-flutter` is refused
- **AND** no request of the spec reaches a chat model

#### Scenario: The role matrix is checked for every caller

- **WHEN** the role matrix spec calls each protected endpoint with no token, a malformed or wrongly signed token, a `USER` token and an `ADMIN` token
- **THEN** each answer equals the matrix: 401 for every invalid token, 403 for `USER` on admin rows, authorized for the permitted role, and 200 without a token on the public endpoints
- **AND** an authorized prompt is proven by a 400 `unknown_compaction_provider` answer that no model call produced

#### Scenario: An expired token is refused

- **WHEN** a slice test sends a token signed with the decoder's test key whose `exp` lies in the past
- **THEN** the answer is 401 with the problem body code `unauthorized`

#### Scenario: A log line is never a pass criterion

- **WHEN** a contributor reads any spec this change adds
- **THEN** its Expected section names only statuses, response bodies, decoded token claims and persisted rows, keys or points
