Ordering rule for this change: identity exists before anything reads it, and the password sign-in path exists before anything optional. Sections 1 through 5 build the realm, password sign-in, the verified caller, the principal format, and the principal set. Section 6 adds optional corporate sign-on, and nothing before it depends on it. Everything after consumes that work or hardens the perimeter around it.

Blocked siblings. `add-tenant-isolation` cannot compose an access-list predicate until a principal set exists on the request, and `add-document-connectors` cannot write access lists until the principal format is fixed. The tasks they wait on are section 3 (the resolved identity), section 4 (the principal format and its factory), and section 5.1 (the assembled set on the request). Those three are the contract freeze. Neither sibling starts before all of them are done and their verifications pass.

Every task carries its own verification, and every verification is an observable check: a status code, a response body, a stored row, a call that was or was not made, a value on a resolved object. None of them is a log line.

## 1. Identity provider (Keycloak) and password sign-in, additive, nothing consumes it yet

- [ ] 1.1 Author the production realm export `keycloak/realm-ascend-ai.json`: realm `ascend-ai`, realm roles `USER` and `ADMIN` with `USER` as the realm default role, public client `ascend-flutter` (authorization-code with PKCE `S256`, no secret, loopback placeholder redirect URIs, direct access grants disabled), protocol mappers emitting the group claim, `tenant`, and `email`
  - verify: `jq` over the export shows the client is public with `pkceCodeChallengeMethod` of `S256`, no secret, and `directAccessGrantsEnabled` false; shows the three protocol mappers; and shows `USER` in the realm default roles
- [ ] 1.2 Set an explicit realm password policy in the export: a minimum length and brute-force detection enabled
  - verify: `jq` shows a non-empty `passwordPolicy` naming a minimum length, and `bruteForceProtected` true; creating an account with a password shorter than the minimum is refused by the admin API
- [ ] 1.3 Set explicit realm SSO session and access token lifetimes in the export, because they are the staleness bound for a group membership change
  - verify: `jq` shows explicit values rather than inherited defaults, and those values match the numbers stated in the staleness disclosure in `docs/SECURITY.md`
- [ ] 1.4 Create the realm groups and the group protocol mapper in the export, with at least one seeded group demonstrating the principal character set
  - verify: `jq` shows the group membership mapper on the `ascend-flutter` client emitting a full-path-free array claim, and a token for an account in the seeded group carries that group name in the claim
- [ ] 1.5 Author the development overlay separately: the seeded test user with both roles, an email address, and membership of realm group `dev-all`, plus the direct-access-grant client the Bruno collection and e2e suite use, imported only in the development compose posture
  - verify: importing the production export alone into a clean Keycloak yields no human user and no client accepting a password grant, and importing the overlay as well yields both
- [ ] 1.6 Add the `keycloak` service to `docker-compose.yaml`: `quay.io/keycloak/keycloak` with `start-dev --import-realm`, the export and the development overlay mounted into `/opt/keycloak/data/import/`, backed by the external PostgreSQL on a dedicated `keycloak` database, healthcheck exposed, non-conflicting host port
  - verify: on a clean environment the container reaches healthy, and `GET /realms/ascend-ai/.well-known/openid-configuration` returns 200 carrying a `jwks_uri`, with no manual console step performed
- [ ] 1.7 Prove password sign-in end to end through Keycloak's own login page, with no brokered provider configured anywhere in the realm
  - verify: an authorization request against `ascend-flutter` reaches Keycloak's login page, submitting the seeded account's password returns an authorization code, and exchanging that code with the PKCE verifier returns an access token; no request issued by the client carries the password
- [ ] 1.8 Prove the direct access grant stays off on the customer-facing client, which is the defect this change already fixed and must not reintroduce
  - verify: a `password` grant request against `ascend-flutter` is refused by Keycloak, and the same request against the development overlay's client succeeds, and the overlay client is absent from a production-only import
- [ ] 1.9 Verify the claims contract on a real token
  - verify: a token for the seeded overlay user decodes to `sub`, `preferred_username`, `email`, a group claim containing `dev-all`, `tenant` equal to `default`, and `realm_access.roles` containing both `USER` and `ADMIN`
- [ ] 1.10 Confirm realm state survives container recreation beyond the import
  - verify: create a second realm user through the admin API, recreate the container, and that user is still present

## 2. ascend-ai-agent resource server

- [ ] 2.1 `apps/ascend-ai-agent/build.gradle.kts`: replace `spring-boot-starter-oauth2-client` with `spring-boot-starter-oauth2-resource-server`; add `spring-security-test` to the test scope
  - verify: `./gradlew dependencies --configuration runtimeClasspath` lists `spring-boot-starter-oauth2-resource-server` and does not list `spring-boot-starter-oauth2-client`
- [ ] 2.2 Rewrite `SecurityConfig.java` as a JWT resource-server chain carrying the D4 matrix: `/api/v1/ai/prompt` and `/api/v1/ingestion/upload` need `USER` or `ADMIN`; `/api/v1/ingestion/run` needs `ADMIN`; `/actuator/health`, `/actuator/prometheus`, and the Swagger and OpenAPI paths are permitAll; everything else is authenticated. CSRF stays disabled, sessions stateless. Delete the HTTP Basic branch, the `UserDetailsService`, and the `PasswordEncoder` bean
  - verify: MockMvc returns 401 tokenless on prompt, 403 for a `USER` token on `/api/v1/ingestion/run`, 200 for an `ADMIN` token on the same path, and 200 tokenless on `/actuator/health` and `/swagger-ui.html`
- [ ] 2.3 Add the tolerant role-claim converter: `realm_access.roles` when present, else a top-level `roles` claim, mapped to `ROLE_USER` and `ROLE_ADMIN`, and consuming no group claim
  - verify: a token in each shape resolves the same authorities, and a token carrying a `groups` claim resolves no authority derived from it
- [ ] 2.4 Delete `SecurityProperties.java` and the `app.security` block from `application.yaml`; add `spring.security.oauth2.resourceserver.jwt.issuer-uri`, environment-overridable, with the docker default pointing at the compose Keycloak
  - verify: the application starts with `app.security.enabled=true` set on the command line and the property has no effect, because binding no longer exists
- [ ] 2.5 Add the `dev` profile chain: permitAll plus the synthesized identity, with the default and `docker` profiles requiring JWTs
  - verify: under `dev` a tokenless prompt request returns a non-401 status; under no profile the same request returns 401
- [ ] 2.6 Security slice tests with `SecurityMockMvcRequestPostProcessors.jwt()` covering the full matrix, including expired and wrongly-signed tokens
  - verify: the slice suite passes and includes a case asserting 401 for a token signed by a key absent from the configured JWKS

## 3. Identity from claims (contract freeze, blocks add-tenant-isolation and add-document-connectors)

- [ ] 3.1 Create the resolved identity record carrying `userId`, `username`, `email`, `tenant`, `roles`, `groupIds`, and `principals`, immutable in every field
  - verify: the type is a Java record, its collection fields are unmodifiable, and a test asserting a mutation attempt on `principals` throws passes
- [ ] 3.2 Bind `app.identity.claims` through `@ConfigurationProperties`: the group claim name and the email claim name, with the Keycloak defaults `groups` and `email`
  - verify: an integration test overriding the group claim name resolves `groupIds` from the overridden claim without a code change
- [ ] 3.3 Implement the resolver mapping `Jwt` to the resolved identity: `sub` to `userId`, `preferred_username` to `username`, the configured email claim to `email`, the `tenant` claim to `tenant` defaulting to `default`, and the configured group claim to `groupIds`
  - verify: a token carrying all five claims resolves each field to its own claim, and a token missing `tenant` resolves `default`
- [ ] 3.4 `PromptController.java`: remove the `X-User-Id` `@RequestHeader` parameter and the `defaultUserId` fallback, take identity from the resolved object, and update the OpenAPI annotations
  - verify: a request authenticated as `alice-sub` and carrying `X-User-Id: bob` writes chat history under `alice-sub`, and no Redis or Postgres row keyed on `bob` exists afterwards
- [ ] 3.5 `IngestionController.java`: the same identity switch for every user-attributed operation
  - verify: an upload authenticated as `alice-sub` records `alice-sub` as the uploader regardless of any header sent
- [ ] 3.6 Tests for the identity contract: header spoofing ignored, missing `tenant` claim defaulting, `tenant: acme` surfacing, `preferred_username` never used as a storage key
  - verify: the suite passes and includes a case asserting that a token whose `preferred_username` changes between two requests writes both under the same `sub`-keyed partition

## 4. Principal identifiers and the typed factory (contract freeze, blocks add-tenant-isolation and add-document-connectors)

- [ ] 4.1 Create the principal value type and its single factory, validating the `namespace:type:id` shape, the 128-character cap, and the character set of lowercase letters, digits, `.`, `-`, `_`, `@`
  - verify: the factory produces exactly `local:group:policy-readers` and `tenant:everyone:acme` for the corresponding inputs
- [ ] 4.2 Model the closed namespace set (`local`, `tenant`) and the closed type set (`group`, `everyone`) as enums, with every Keycloak realm group minting into `local`
  - verify: a token carrying the realm group `policy-readers` resolves `local:group:policy-readers`, and a request for a namespace outside the set fails to compile or throws
- [ ] 4.3 Reject invalid input by throwing rather than by returning a truncated or best-effort value
  - verify: uppercase input, a space, a namespace outside the set, and a 129-character value each throw an exception naming the violated constraint, and no principal value is produced
- [ ] 4.4 Make the factory the only construction path
  - verify: an ArchUnit rule fails the build if any class outside the factory constructs the principal type directly or assembles a principal string by concatenation

## 5. Group membership and principal set assembly

- [ ] 5.1 Resolve `groupIds` from the configured group claim, mint one principal per group through the factory, assemble the set during authentication before any controller method runs, attach it to the resolved identity, and make it immutable for the life of the request (contract freeze, blocks add-tenant-isolation)
  - verify: the set observed in a controller equals the set observed at authentication time, any mutation attempt throws, the set always contains `tenant:everyone:{tenantId}`, and a token listing two groups resolves both as `local:group:*` principals
- [ ] 5.2 Resolve an absent or empty group claim to no group principals, and make no outbound call of any kind during resolution
  - verify: a token with no group claim resolves exactly `tenant:everyone:{tenantId}` and the request returns 200, and a network stub asserts that resolution issues no HTTP call
- [ ] 5.3 Prove a group membership change becomes visible at the next token and that nothing is cached between requests
  - verify: an administrator removes a person from a realm group, the person's existing token still resolves the principal, the next token they obtain does not, and no Redis key holding a resolved principal set exists at any point
- [ ] 5.4 Fail loudly on a group name that cannot be minted
  - verify: a token carrying a group name with a character outside the permitted set produces an error naming the constraint, and no partially-populated set reaches any filter
- [ ] 5.5 Enforce the configurable cap, default 256, refusing rather than truncating
  - verify: a caller resolving more principals than the cap receives 403 with an `application/problem+json` body naming both the cap and the resolved size, and no vector search is executed
- [ ] 5.6 Give the `dev` profile a principal set of `tenant:everyone:default` and `local:group:dev-all`
  - verify: under `dev`, a chunk stored with `local:group:dev-all` in its access list is retrieved by a tokenless prompt request, and a chunk stored with no access list is not
- [ ] 5.7 Publish the principal-set-size metric the design document requires
  - verify: after a request, the metric is present on `/actuator/prometheus` and its recorded value equals the resolved set size for that request
- [ ] 5.8 Assert that roles contribute no principals
  - verify: two callers in one tenant with identical group membership, one holding only `USER` and one holding `ADMIN`, resolve equal principal sets
- [ ] 5.9 Assert that a directory group identifier matches nothing
  - verify: a chunk whose access list names a Microsoft Entra ID group by its directory object id is retrieved by no caller, and a chunk carrying `tenant:everyone:{tenantId}` is retrieved by every caller in that tenant

## 6. Optional corporate sign-on through identity brokering

Nothing in sections 1 through 5 depends on this section. A deployment that skips it is complete.

- [ ] 6.1 Add a disabled brokered-provider template entry to the realm export: a generic OpenID Connect provider carrying a hardcoded-attribute mapper for `tenant` and token storage off, with no mapper importing a group claim, a role claim, or any other attribute the resolved identity derives authorization from
  - verify: `jq` shows the entry disabled, shows its tenant mapper, shows no identity-provider mapper writing an attribute that any protocol mapper emits into a claim the agent reads for authorization, and shows no provider in the export with token storage enabled
- [ ] 6.2 Stand up a second Keycloak realm as a stand-in for a customer's identity provider, and broker it from `ascend-ai` using the template entry, with its own tenant value
  - verify: a person signing in through the brokered provider reaches a token whose `tenant` claim carries the brokered provider's value and not `default`
- [ ] 6.3 Prove a brokered person's authorization comes from Keycloak and not from the upstream token
  - verify: an administrator places the brokered person in the realm group `policy-readers` and their resolved principal set contains `local:group:policy-readers`; an upstream token carrying its own `tenant` claim naming a different customer yields an access token stamped with the brokered provider's tenant; and an upstream group named `ADMIN` yields no `ROLE_ADMIN` authority and a 403 on an `ADMIN`-only endpoint
- [ ] 6.4 Prove an unmatched person is not dropped into a brokered provider
  - verify: a person whose email domain is registered to no brokered provider is not signed in through one, and signing in with a local account and password still works

## 7. Downstream service auth, Python services, warn-only when the token is unset

- [ ] 7.1 AscendMemory: a FastAPI bearer-token dependency (HTTPBearer plus `secrets.compare_digest` against `SERVICE_AUTH_TOKEN`) on all `/api/v1/memory/*` routes, `/health` left open, fail-fast at startup when the compose posture is signalled and the token is unset
  - verify: `POST /api/v1/memory/wipe` without a header returns 401 and the Qdrant point count is unchanged; with the correct token it returns non-401
- [ ] 7.2 AscendMemory: the same check on the FastMCP surface so `/mcp` is not a bypass
  - verify: a tokenless MCP `tools/call` returns 401 and no tool executes; the same call with the token executes normally
- [ ] 7.3 ascend-audio-scribe: the same REST dependency on `/api/v1/transcribe/*` and the same FastMCP enforcement, `/health` open
  - verify: 401 tokenless on a transcribe route and on `/mcp`, 200 on `/health`
- [ ] 7.4 ascend-web-hunter: the same REST dependency and FastMCP enforcement, `/health` open
  - verify: 401 tokenless on a search route and on `/mcp`, 200 on `/health`
- [ ] 7.5 ascend-ocr: the same REST dependency on `/v1/ocr` and FastMCP enforcement, `/health` and `/ready` open
  - verify: 401 tokenless on `/v1/ocr` and on `/mcp`, 200 on `/health` and `/ready`
- [ ] 7.6 pytest per service covering the token matrix
  - verify: each service's suite asserts 401 without a token, 401 with a wrong token, non-401 with the correct token, open health, and a rejected tokenless MCP `tools/call`
- [ ] 7.7 pytest per service for the posture rule
  - verify: with the compose posture signalled and `SERVICE_AUTH_TOKEN` unset the process exits non-zero before serving traffic; on a bare local run without the variable it serves requests without one

## 8. Downstream service auth, ascend-weather-mcp

- [ ] 8.1 Add a `OncePerRequestFilter` doing the constant-time bearer compare against `SERVICE_AUTH_TOKEN` ahead of the MCP endpoints, health excluded, warn-and-open when unset locally and fail-fast in the docker posture
  - verify: MockMvc returns 401 on the MCP path without a token and with a wrong token, passes through with the correct token, and returns 200 on health without one
- [ ] 8.2 Prove the docker posture refuses to boot open
  - verify: starting the container in the compose posture with `SERVICE_AUTH_TOKEN` unset exits non-zero before the port accepts a connection

## 9. ascend-ai-agent outbound token attachment

- [ ] 9.1 Bind `SERVICE_AUTH_TOKEN` through `@ConfigurationProperties` with no checked-in default, and attach `Authorization: Bearer` as a default header on the `SemanticMemoryClient` RestClient builder when configured
  - verify: MockRestServiceServer sees the header on `search` and on `wipeUserMemory`, sees no `Authorization` header when the token is unset, and the token value appears in no log output at any level
- [ ] 9.2 Attach the same header on the ascend-ocr ingestion client
  - verify: a stubbed ascend-ocr endpoint records the bearer header on an OCR call issued by the ingestion pipeline
- [ ] 9.3 Attach the header on all three MCP client connections (ascend-audio-scribe, weather, ascend-web-hunter), through Spring AI connection header configuration, falling back to a WebClient customizer where the connection type lacks header support
  - verify: an integration test against a stub MCP server records the bearer header on the outbound `tools/call` for each of the three connections
- [ ] 9.4 Prove the secured path end to end at the client level
  - verify: with all downstream services enforcing, a chat turn that triggers a semantic-memory search and one MCP tool call completes with no 401 recorded by any downstream stub

## 10. Secured compose posture end to end

- [ ] 10.1 Wire `SERVICE_AUTH_TOKEN` and the issuer environment variables through `docker-compose.yaml` for all six services, with the agent's `depends_on` gated on the Keycloak healthcheck
  - verify: `docker compose config` shows the variables resolved for every service and the dependency condition on Keycloak's health
- [ ] 10.2 Integration test against a real issuer using a Testcontainers Keycloak
  - verify: the agent boots against the container's issuer, obtains a token, and the full authorization matrix from 2.2 holds over real HTTP
- [ ] 10.3 Full-stack smoke of the secured posture
  - verify: one secured chat turn exercising semantic memory and one MCP tool completes with no downstream 401, and a tokenless `POST /api/v1/memory/wipe` against AscendMemory returns 401 with the Qdrant point count unchanged

## 11. e2e and Bruno migration

- [ ] 11.1 Add a token-acquisition request against the seeded realm user to the Bruno collection at `docs/api/request/AscendAI/`, using the development overlay's client rather than the application client, and thread the bearer token through the existing requests by environment variable
  - verify: `bru run` against the secured stack completes the collection with no 401, removing the token step reproduces 401 on the first protected request, and the same collection run against a realm imported without the development overlay fails at the token step rather than obtaining a token
- [ ] 11.2 Update the five e2e specs and their tasks-templates in `apps/ascend-ai-agent/e2e/` for the secured posture, adding the token step to setup and removing `X-User-Id` usage, while keeping the dev-profile path documented for ad-hoc manual runs
  - verify: no spec or template under `apps/ascend-ai-agent/e2e/` still references `X-User-Id`, and each of the five names its token-acquisition setup step
- [ ] 11.3 Run the e2e sweep against the secured stack
  - verify: all five specs pass with verdicts recorded under `apps/ascend-ai-agent/e2e/testing/runs/`

## 12. Documentation and architecture decision records

- [ ] 12.1 Author `docs/SECURITY.md`: auth architecture, the authorization-code with PKCE token flow and the explicit statement that the application never handles a password, the claims contract (`sub`, `preferred_username`, `email`, `tenant`, roles, groups), the principal identifier format, the issuer swap recipe as an escape hatch, the service-token rotation procedure, and dev-profile usage including the two synthesized principals. Link it from the root README documentation map
  - verify: the document names every configuration key this change introduces, and a reader following the issuer swap recipe against a second Keycloak realm reaches a working token without reading any other file
- [ ] 12.2 Add the administrator runbook to `docs/SECURITY.md`: creating an account, the password policy, creating a realm group, the group-name character constraint the principal factory enforces, assigning membership, and how a group becomes a principal on the next token
  - verify: an operator following the runbook creates a group, assigns a person, and observes the corresponding `local:group:*` principal on that person's next resolved identity, without reading any other document
- [ ] 12.3 Add the optional brokering runbook to `docs/SECURITY.md`: what the customer hands over, creating the brokered provider from the template, the tenant stamp, the email-domain registration, the verification sign-in that closes the onboarding, and the statement that group membership is assigned separately in Keycloak and no group data crosses the broker
  - verify: an operator following the runbook against the second Keycloak realm from task 6.2 onboards it end to end and reaches a verification sign-in resolving the expected tenant, without reading any other document
- [ ] 12.4 Record the named limitation in `docs/SECURITY.md`: no principal this version mints matches a directory group identifier, so per-document permissions apply to directly-uploaded documents and connector-synced documents are visible tenant-wide, together with what would have to be built to lift it
  - verify: the section states both halves of the consequence and names the deferred work, and it does not describe the limitation as a defect
- [ ] 12.5 Record the staleness window in `docs/SECURITY.md` as a product disclosure: a group membership change becomes visible at the caller's next token, bounded by the access token lifetime and the SSO session lifetime
  - verify: the stated numbers match the lifetimes actually set in the realm export from task 1.3, and the section states that ascend-ai-agent adds no cache of its own
- [ ] 12.6 Record the operating cost of self-hosted Keycloak in `docs/SECURITY.md`: the database, certificates, backup with a restore that has been exercised, the absence of a long-term support release upstream, the roughly monthly patch and quarterly minor cadence, breaking changes having shipped inside patch releases, and the requirement to re-verify sign-in after an upgrade
  - verify: the section exists, names the upgrade verification step, and the restore procedure has been performed once against a non-production realm with the result recorded
- [ ] 12.7 Update the root `AGENTS.md` and the per-module `AGENTS.md` files (ascend-ai-agent, AscendMemory, ascend-audio-scribe, ascend-web-hunter, ascend-ocr, ascend-weather-mcp) with the new environment variables, the secured-by-default posture, and the dev-profile note
  - verify: `grep` for `SERVICE_AUTH_TOKEN` and `issuer-uri` finds them documented in every module whose service consumes them
- [ ] 12.8 Install the decision records drafted in `openspec/changes/add-auth-and-identity/decisions/` into `apps/ascend-ai-agent/docs/architecture/decisions/`, taking the next free numbers at that moment, flipping each active record's Status line from proposed to accepted with the merge date, and carrying the deferred records across with their deferred status intact
  - verify: the files exist under `apps/ascend-ai-agent/docs/architecture/decisions/` with unique sequential numbers, no number collides with an existing record, every relative link inside them resolves, and each deferred record states plainly that it is not implemented by this change
- [ ] 12.9 Update `apps/ascend-ai-agent/docs/architecture/` diagrams and arc42 sections for the resource-server posture and the principal resolution path
  - verify: the component diagram shows Keycloak as the issuer and the principal resolution step in the request path, and shows no directory adapter and no principal cache
- [ ] 12.10 Keep `openspec/changes/add-auth-and-identity/tasks.md` checkboxes current as work proceeds
  - verify: `openspec instructions apply --change add-auth-and-identity --json` reports a completion count matching the checked boxes at every review point
- [ ] 12.11 Amend `docs/architecture/permission-aware-retrieval.md` and `docs/architecture/decisions/ADR-M007-group-principals-membership-at-login.md` to match what this version actually delivers: group membership resolved from Keycloak realm groups, no directory lookup and no principal cache, the ownership table split into what lands and what is deferred, and the named limitation that a directory group identifier matches no principal
  - verify: neither document still states that this change delivers the directory object id, the principal cache, the identity link, or the identity-link administrator API, the staleness section names the token lifetime as the only window, and every cross-reference between those two documents and this change's decisions resolves
