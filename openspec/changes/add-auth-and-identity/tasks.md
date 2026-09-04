Ordering rule for this change: identity exists before anything reads it. Sections 1 through 8 build the verified caller, the two subjects, the principal set, and the identity link. Everything after them consumes that work or hardens the perimeter around it.

Blocked siblings. `add-tenant-isolation` cannot compose an access-list predicate until a principal set exists on the request, and `add-document-connectors` cannot write access lists until the principal format is fixed. The tasks they wait on are section 3 (the resolved identity with both subjects), section 4 (the principal format and its factory), and section 6.1 (the assembled set on the request). Those three are the contract freeze. Neither sibling starts before all of them are done and their verifications pass.

Every task carries its own verification, and every verification is an observable check: a status code, a response body, a stored row, a call that was or was not made, a value on a resolved object. None of them is a log line.

## 1. Identity provider (Keycloak), additive, nothing consumes it yet

- [ ] 1.1 Author `keycloak/realm-ascend-ai.json`: realm `ascend-ai`, realm roles `USER` and `ADMIN`, public client `ascend-flutter` (authorization-code with PKCE `S256`, no secret, loopback placeholder redirect URIs), a `tenant` protocol mapper emitting `default`, a `groups` mapper emitting the user's realm group names, an `email` mapper, a realm group `dev-all`, and a seeded test user carrying both roles, an email address, and membership of `dev-all`
  - verify: `jq` over the export shows the client is public with `pkceCodeChallengeMethod` of `S256` and no secret, and shows mappers named `tenant`, `groups`, and `email`
- [ ] 1.2 Add the `keycloak` service to `docker-compose.yaml`: `quay.io/keycloak/keycloak` with `start-dev --import-realm`, the export mounted into `/opt/keycloak/data/import/`, backed by the external PostgreSQL on a dedicated `keycloak` database, healthcheck exposed, non-conflicting host port
  - verify: on a clean environment the container reaches healthy, and `GET /realms/ascend-ai/.well-known/openid-configuration` returns 200 carrying a `jwks_uri`, with no manual console step performed
- [ ] 1.3 Verify the claims contract on a real token
  - verify: a password-grant token for the seeded user decodes to `sub`, `preferred_username`, `email`, `groups` containing `dev-all`, `tenant` equal to `default`, and `realm_access.roles` containing both `USER` and `ADMIN`
- [ ] 1.4 Confirm realm state survives container recreation beyond the import
  - verify: create a second realm user through the admin API, recreate the container, and that user is still present

## 2. AscendAgent resource server

- [ ] 2.1 `AscendAgent/build.gradle.kts`: replace `spring-boot-starter-oauth2-client` with `spring-boot-starter-oauth2-resource-server`; add `spring-security-test` to the test scope
  - verify: `./gradlew dependencies --configuration runtimeClasspath` lists `spring-boot-starter-oauth2-resource-server` and does not list `spring-boot-starter-oauth2-client`
- [ ] 2.2 Rewrite `SecurityConfig.java` as a JWT resource-server chain carrying the D4 matrix: `/api/v1/ai/prompt` and `/api/v1/ingestion/upload` need `USER` or `ADMIN`; `/api/v1/ingestion/run` needs `ADMIN`; `/api/v1/admin/**` needs `ADMIN`; `/actuator/health`, `/actuator/prometheus`, and the Swagger and OpenAPI paths are permitAll; everything else is authenticated. CSRF stays disabled, sessions stateless. Delete the HTTP Basic branch, the `UserDetailsService`, and the `PasswordEncoder` bean
  - verify: MockMvc returns 401 tokenless on prompt, 403 for a `USER` token on `/api/v1/ingestion/run` and on `/api/v1/admin/identity-links`, 200 for an `ADMIN` token on both, and 200 tokenless on `/actuator/health` and `/swagger-ui.html`
- [ ] 2.3 Add the tolerant role-claim converter: `realm_access.roles` when present, else a top-level `roles` claim, mapped to `ROLE_USER` and `ROLE_ADMIN`, and consuming no group claim
  - verify: a token in each shape resolves the same authorities, and a token carrying a `groups` claim resolves no authority derived from it
- [ ] 2.4 Delete `SecurityProperties.java` and the `app.security` block from `application.yaml`; add `spring.security.oauth2.resourceserver.jwt.issuer-uri`, environment-overridable, with the docker default pointing at the compose Keycloak
  - verify: the application starts with `app.security.enabled=true` set on the command line and the property has no effect, because binding no longer exists
- [ ] 2.5 Add the `dev` profile chain: permitAll plus the synthesized identity, with the default and `docker` profiles requiring JWTs
  - verify: under `dev` a tokenless prompt request returns a non-401 status; under no profile the same request returns 401
- [ ] 2.6 Security slice tests with `SecurityMockMvcRequestPostProcessors.jwt()` covering the full matrix, including expired and wrongly-signed tokens
  - verify: the slice suite passes and includes a case asserting 401 for a token signed by a key absent from the configured JWKS

## 3. Identity from claims, both subjects (contract freeze, blocks add-tenant-isolation and add-document-connectors)

- [ ] 3.1 Create the resolved identity record carrying `userId`, `directorySubject`, `username`, `email`, `tenant`, `roles`, `groupIds`, and `principals`, immutable in every field
  - verify: the type is a Java record, its collection fields are unmodifiable, and a test asserting a mutation attempt on `principals` throws passes
- [ ] 3.2 Bind `app.identity.claims` through `@ConfigurationProperties`: the directory-subject claim name, the group claim name, and the email claim name, with the Keycloak defaults `sub`, `groups`, `email`
  - verify: an integration test overriding the directory-subject claim name to `oid` resolves `directorySubject` from `oid` without a code change
- [ ] 3.3 Implement the resolver mapping `Jwt` to the resolved identity: `sub` to `userId`, the configured claim to `directorySubject`, `preferred_username` to `username`, the normalized email claim to `email`, the `tenant` claim to `tenant` defaulting to `default`
  - verify: a token whose `sub` and `oid` differ resolves `userId` from `sub` and `directorySubject` from `oid`, and swapping the two claim values in the token swaps them on the resolved identity
- [ ] 3.4 `PromptController.java`: remove the `X-User-Id` `@RequestHeader` parameter and the `defaultUserId` fallback, take identity from the resolved object, and update the OpenAPI annotations
  - verify: a request authenticated as `alice-sub` and carrying `X-User-Id: bob` writes chat history under `alice-sub`, and no Redis or Postgres row keyed on `bob` exists afterwards
- [ ] 3.5 `IngestionController.java`: the same identity switch for every user-attributed operation
  - verify: an upload authenticated as `alice-sub` records `alice-sub` as the uploader regardless of any header sent
- [ ] 3.6 Reject a token that carries no value under the configured directory-subject claim when at least one directory adapter is configured, rather than substituting `sub`
  - verify: such a request returns 401 and no call is made to any directory adapter
- [ ] 3.7 Tests for the identity contract: subject-versus-directory-subject separation, header spoofing ignored, missing `tenant` claim defaulting, `tenant: acme` surfacing
  - verify: the suite passes and includes the swapped-claims case from 3.3, which is the test that catches the Entra ID pairwise-subject trap by construction

## 4. Principal identifiers and the typed factory (contract freeze, blocks add-tenant-isolation and add-document-connectors)

- [ ] 4.1 Create the principal value type and its single factory, validating the `namespace:type:id` shape, the 128-character cap, and the character set of lowercase letters, digits, `.`, `-`, `_`, `@`
  - verify: the factory produces exactly `entra:group:8f4a1b2c-3d5e-4f60-9a1b-2c3d4e5f6071`, `google:group:engineering@acme.example`, `local:group:policy-readers`, and `tenant:everyone:acme` for the corresponding inputs
- [ ] 4.2 Model the closed namespace set (`entra`, `google`, `local`, `tenant`) and the closed type set (`group`, `everyone`) as enums, with Keycloak realm groups minting into `local`
  - verify: a Keycloak token carrying group `policy-readers` resolves the principal `local:group:policy-readers`
- [ ] 4.3 Reject invalid input by throwing rather than by returning a truncated or best-effort value
  - verify: uppercase input, a space, a namespace outside the set, and a 129-character value each throw an exception naming the violated constraint, and no principal value is produced
- [ ] 4.4 Make the factory the only construction path
  - verify: an ArchUnit rule fails the build if any class outside the factory constructs the principal type directly or assembles a principal string by concatenation

## 5. Group membership resolution and the principal cache

- [ ] 5.1 Read the configured group claim and implement the completeness test: complete means the claim is present and neither `_claim_names` nor `_claim_sources` is
  - verify: a token with a `groups` claim and no overflow markers resolves without any directory call; a token with no `groups` claim and with `_claim_names` present triggers the directory call
- [ ] 5.2 Define the directory adapter interface (transitive group membership for a directory subject) and implement the Microsoft Graph adapter against the transitive `memberOf` call
  - verify: against a stubbed Graph endpoint, the adapter sends the `oid` value and never the `sub` value, and returns the flattened group list the endpoint provided without walking nesting locally
- [ ] 5.3 Implement the Google Directory adapter against the Directory API group listing
  - verify: against a stubbed endpoint, the adapter returns `google:group:*` principals built through the factory from the group addresses returned
- [ ] 5.4 Bind `app.identity.directories` as a list of adapters, each with a provider kind, a principal namespace, and credentials, with an empty list valid and meaning token-claim-only resolution
  - verify: with an empty list and a complete group claim the principal set resolves and no directory call is made; with one adapter configured the call is made on a cache miss
- [ ] 5.5 Cache the resolved principal set in Redis under `principals:v1:{issuerHash}:{subject}` with a time to live of the shorter of the remaining token lifetime and five minutes
  - verify: a second request inside the window makes no directory call; a token with two minutes of life left produces a Redis key whose remaining time to live is at most 120 seconds; two tokens sharing a `sub` from different issuers resolve independently and neither reads the other's entry
- [ ] 5.6 Prove Redis unavailability degrades latency only
  - verify: with Redis stopped, the request completes and resolves a principal set identical to the one produced with Redis running

## 6. Principal set assembly, cap, and failure behaviour

- [ ] 6.1 Assemble the principal set during authentication, before any controller method runs, attach it to the resolved identity, and make it immutable for the life of the request (contract freeze, blocks add-tenant-isolation)
  - verify: the set observed in a controller equals the set observed at authentication time, any mutation attempt throws, and the set always contains `tenant:everyone:{tenantId}`
- [ ] 6.2 Enforce the configurable cap, default 256, refusing rather than truncating
  - verify: a caller resolving more principals than the cap receives 403 with an `application/problem+json` body naming both the cap and the resolved size, and no vector search is executed
- [ ] 6.3 Fail a directory resolution failure with 503 and `Retry-After`, with no fallback to the tenant floor and no cached set served past its time to live
  - verify: with the directory adapter stubbed to throw, the response is 503 carrying `Retry-After`, no vector search is executed, and no 200 carrying an answer is produced
- [ ] 6.4 Give the `dev` profile a principal set of `tenant:everyone:default` and `local:group:dev-all`
  - verify: under `dev`, a chunk stored with `local:group:dev-all` in its access list is retrieved by a tokenless prompt request, and a chunk stored with no access list is not
- [ ] 6.5 Publish the principal-set-size metric the design document requires
  - verify: after a request, the metric is present on `/actuator/prometheus` and its recorded value equals the resolved set size for that request
- [ ] 6.6 Assert that roles contribute no principals
  - verify: two callers in one tenant with identical group membership, one holding only `USER` and one holding `ADMIN`, resolve equal principal sets

## 7. Cross-provider identity link

- [ ] 7.1 Add the Liquibase changelog creating `identity_link` (normalized email, login issuer, login directory subject, file-provider directory subject, status, created and last-confirmed timestamps, conflicting subject), unique on normalized email within a tenant and indexed on each subject, plus the JPA entity and repository
  - verify: the changelog applies to a Testcontainers PostgreSQL, the unique constraint rejects a duplicate email within one tenant, and lookups by either subject use an index according to `EXPLAIN`
- [ ] 7.2 Implement email normalization as one function: trim, NFKC, lowercase, IDNA-encode the domain, strip a `+tag` suffix, and do not strip dots
  - verify: `  Alice.Smith+reports@ACME.example `, `alice.smith@acme.example`, and `ALICE.SMITH+ci@acme.example` all normalize to `alice.smith@acme.example`, while `alicesmith@acme.example` normalizes to a different value
- [ ] 7.3 Resolve the link at login: create when absent, confirm when every stored subject matches, move to `SUSPECT` when a stored subject differs, recording both subjects and never overwriting automatically
  - verify: first login writes an `ACTIVE` row; a repeat login updates the last-confirmation timestamp and leaves the status `ACTIVE`; a login with the same normalized email and a different directory subject leaves a `SUSPECT` row carrying both subjects, and the request still authenticates
- [ ] 7.4 Contribute no group principals from any provider while the link is `SUSPECT` or `DISABLED`
  - verify: such a caller resolves a principal set equal to exactly `tenant:everyone:{tenantId}`, containing no `entra:group:*`, `google:group:*`, or `local:group:*` value, and a prompt request from them still returns 200
- [ ] 7.5 Prove the link is durable rather than cached
  - verify: after a Redis flush, the same caller's next login finds and confirms the existing row rather than creating a second one

## 8. Administrator API for identity links

- [ ] 8.1 `GET /api/v1/admin/identity-links`, `ADMIN` only, cursor-paginated, filterable by status and by normalized email
  - verify: an `ADMIN` filtering on `status=SUSPECT` receives the suspect links with both recorded subjects and the last-confirmation timestamp; a `USER` token receives 403 and no email address appears in the body
- [ ] 8.2 `GET /api/v1/admin/identity-links/{id}`, `ADMIN` only, including the conflicting subject recorded at detection time
  - verify: the response for a suspect link carries both the stored subject and the presented one; an unknown id returns 404 as `application/problem+json`
- [ ] 8.3 `PATCH /api/v1/admin/identity-links/{id}`, `ADMIN` only, correcting a provider subject or moving the status between `ACTIVE`, `SUSPECT`, and `DISABLED`, and deleting that person's cached principal set on success
  - verify: correcting a suspect link and setting it `ACTIVE` returns 200, the affected person's next request resolves their group principals again, and that next request issues a fresh directory call rather than reading the pre-correction cached entry
- [ ] 8.4 Return every error on this surface as `application/problem+json` and document the three endpoints in the OpenAPI definition
  - verify: a 403, a 404, and a validation failure each return `Content-Type: application/problem+json` with `type`, `title`, and `status`, and all three paths appear in `/v3/api-docs`
- [ ] 8.5 Tests for the administrator surface
  - verify: the suite covers `USER` refused on all three endpoints, `ADMIN` allowed on all three, the cache deletion on correction, and pagination returning a stable cursor across two pages

## 9. Downstream service auth, Python services, warn-only when the token is unset

- [ ] 9.1 AscendMemory: a FastAPI bearer-token dependency (HTTPBearer plus `secrets.compare_digest` against `SERVICE_AUTH_TOKEN`) on all `/api/v1/memory/*` routes, `/health` left open, fail-fast at startup when the compose posture is signalled and the token is unset
  - verify: `POST /api/v1/memory/wipe` without a header returns 401 and the Qdrant point count is unchanged; with the correct token it returns non-401
- [ ] 9.2 AscendMemory: the same check on the FastMCP surface so `/mcp` is not a bypass
  - verify: a tokenless MCP `tools/call` returns 401 and no tool executes; the same call with the token executes normally
- [ ] 9.3 AudioScribe: the same REST dependency on `/api/v1/transcribe/*` and the same FastMCP enforcement, `/health` open
  - verify: 401 tokenless on a transcribe route and on `/mcp`, 200 on `/health`
- [ ] 9.4 AscendWebSearch: the same REST dependency and FastMCP enforcement, `/health` open
  - verify: 401 tokenless on a search route and on `/mcp`, 200 on `/health`
- [ ] 9.5 PaddleOCR: the same REST dependency on `/v1/ocr` and FastMCP enforcement, `/health` and `/ready` open
  - verify: 401 tokenless on `/v1/ocr` and on `/mcp`, 200 on `/health` and `/ready`
- [ ] 9.6 pytest per service covering the token matrix
  - verify: each service's suite asserts 401 without a token, 401 with a wrong token, non-401 with the correct token, open health, and a rejected tokenless MCP `tools/call`
- [ ] 9.7 pytest per service for the posture rule
  - verify: with the compose posture signalled and `SERVICE_AUTH_TOKEN` unset the process exits non-zero before serving traffic; on a bare local run without the variable it serves requests without one

## 10. Downstream service auth, WeatherMCP

- [ ] 10.1 Add a `OncePerRequestFilter` doing the constant-time bearer compare against `SERVICE_AUTH_TOKEN` ahead of the MCP endpoints, health excluded, warn-and-open when unset locally and fail-fast in the docker posture
  - verify: MockMvc returns 401 on the MCP path without a token and with a wrong token, passes through with the correct token, and returns 200 on health without one
- [ ] 10.2 Prove the docker posture refuses to boot open
  - verify: starting the container in the compose posture with `SERVICE_AUTH_TOKEN` unset exits non-zero before the port accepts a connection

## 11. AscendAgent outbound token attachment

- [ ] 11.1 Bind `SERVICE_AUTH_TOKEN` through `@ConfigurationProperties` with no checked-in default, and attach `Authorization: Bearer` as a default header on the `SemanticMemoryClient` RestClient builder when configured
  - verify: MockRestServiceServer sees the header on `search` and on `wipeUserMemory`, sees no `Authorization` header when the token is unset, and the token value appears in no log output at any level
- [ ] 11.2 Attach the same header on the PaddleOCR ingestion client
  - verify: a stubbed PaddleOCR endpoint records the bearer header on an OCR call issued by the ingestion pipeline
- [ ] 11.3 Attach the header on all three MCP client connections (audioscribe, weather, ascend-web-search), through Spring AI connection header configuration, falling back to a WebClient customizer where the connection type lacks header support
  - verify: an integration test against a stub MCP server records the bearer header on the outbound `tools/call` for each of the three connections
- [ ] 11.4 Prove the secured path end to end at the client level
  - verify: with all downstream services enforcing, a chat turn that triggers a semantic-memory search and one MCP tool call completes with no 401 recorded by any downstream stub

## 12. Secured compose posture end to end

- [ ] 12.1 Wire `SERVICE_AUTH_TOKEN` and the issuer environment variables through `docker-compose.yaml` for all six services, with the agent's `depends_on` gated on the Keycloak healthcheck
  - verify: `docker compose config` shows the variables resolved for every service and the dependency condition on Keycloak's health
- [ ] 12.2 Integration test against a real issuer using a Testcontainers Keycloak
  - verify: the agent boots against the container's issuer, obtains a token, and the full authorization matrix from 2.2 holds over real HTTP
- [ ] 12.3 Full-stack smoke of the secured posture
  - verify: one secured chat turn exercising semantic memory and one MCP tool completes with no downstream 401, and a tokenless `POST /api/v1/memory/wipe` against AscendMemory returns 401 with the Qdrant point count unchanged

## 13. e2e and Bruno migration

- [ ] 13.1 Add a token-acquisition request against the seeded realm user to the Bruno collection at `docs/api/request/AscendAI/` and thread the bearer token through the existing requests by environment variable
  - verify: `bru run` against the secured stack completes the collection with no 401, and removing the token step reproduces 401 on the first protected request
- [ ] 13.2 Update the five e2e specs and their tasks-templates in `AscendAgent/e2e/` for the secured posture, adding the token step to setup and removing `X-User-Id` usage, while keeping the dev-profile path documented for ad-hoc manual runs
  - verify: no spec or template under `AscendAgent/e2e/` still references `X-User-Id`, and each of the five names its token-acquisition setup step
- [ ] 13.3 Run the e2e sweep against the secured stack
  - verify: all five specs pass with verdicts recorded under `AscendAgent/e2e/testing/runs/`

## 14. Documentation and architecture decision records

- [ ] 14.1 Author `docs/SECURITY.md`: auth architecture, token flow diagram, the claims contract (`sub`, the directory-subject claim, `preferred_username`, `email`, `tenant`, roles, groups), the principal identifier format, the identity-link lifecycle and its correction procedure, the issuer swap recipe, the directory adapter configuration, the service-token rotation procedure, and dev-profile usage including the two synthesized principals. Link it from the root README documentation map
  - verify: the document names every configuration key this change introduces, and a reader following the issuer swap recipe against a second Keycloak realm reaches a working token without reading any other file
- [ ] 14.2 Update the root `AGENTS.md` and the per-module `AGENTS.md` files (AscendAgent, AscendMemory, AudioScribe, AscendWebSearch, PaddleOCR, WeatherMCP) with the new environment variables, the secured-by-default posture, and the dev-profile note
  - verify: `grep` for `SERVICE_AUTH_TOKEN` and `issuer-uri` finds them documented in every module whose service consumes them
- [ ] 14.3 Install the three architecture decision records drafted in `openspec/changes/add-auth-and-identity/decisions/` into `AscendAgent/docs/architecture/decisions/`, taking the next free numbers at that moment, and flip each Status line from proposed to accepted with the merge date
  - verify: the three files exist under `AscendAgent/docs/architecture/decisions/` with unique sequential numbers, no number collides with an existing record, and every relative link inside them resolves
- [ ] 14.4 Update `AscendAgent/docs/architecture/` diagrams and arc42 sections for the resource-server posture, the principal resolution path, and the identity link store
  - verify: the component diagram shows the directory adapters and the Redis principal cache, and the data view lists `identity_link`
- [ ] 14.5 Keep `openspec/changes/add-auth-and-identity/tasks.md` checkboxes current as work proceeds
  - verify: `openspec instructions apply --change add-auth-and-identity --json` reports a completion count matching the checked boxes at every review point
