## 1. Keycloak identity provider (additive, nothing consumes it yet)

- [ ] 1.1 Author `keycloak/realm-ascend-ai.json` realm export: realm `ascend-ai`, realm roles `USER` + `ADMIN`, public client `ascend-flutter` (authorization-code + PKCE `S256`, no secret, loopback placeholder redirect URIs), `tenant` protocol mapper emitting `default`, seeded test user carrying both roles
- [ ] 1.2 Add `keycloak` service to `docker-compose.yaml`: `quay.io/keycloak/keycloak` with `start-dev --import-realm`, realm export mounted into `/opt/keycloak/data/import/`, backed by the external PostgreSQL (dedicated `keycloak` database), healthcheck exposed, non-conflicting host port
- [ ] 1.3 Smoke test: fresh `docker compose up keycloak`, confirm `/realms/ascend-ai/.well-known/openid-configuration` returns 200 with a JWKS URI and a password-grant token for the seeded user contains `sub`, `preferred_username`, `tenant=default`, and `realm_access.roles` = [`USER`, `ADMIN`]

## 2. Downstream service auth — Python services (warn-only when token unset)

- [ ] 2.1 AscendMemory: add a FastAPI bearer-token dependency (HTTPBearer + `secrets.compare_digest` against `SERVICE_AUTH_TOKEN`) applied to all `/api/v1/memory/*` routes; `/health` stays open; startup WARN when token unset, fail-fast when unset and `DOCKER_POSTURE`-style flag indicates compose
- [ ] 2.2 AscendMemory: enforce the same check on the FastMCP surface (FastMCP auth/middleware hook) so `/mcp` rejects tokenless calls with 401
- [ ] 2.3 AudioScribe: same REST dependency on `/api/v1/transcribe/*` + same FastMCP enforcement; `/health` open
- [ ] 2.4 AscendWebSearch: same REST dependency + FastMCP enforcement; `/health` open
- [ ] 2.5 PaddleOCR: same REST dependency on `/v1/ocr` + FastMCP enforcement; `/health` and `/ready` open
- [ ] 2.6 Tests per Python service (pytest): 401 without token, 401 with wrong token, 200 with correct token, `/health` open without token, one MCP-surface test proving tokenless `tools/call` is rejected
- [ ] 2.7 Test per Python service: startup fail-fast when compose posture is signalled and `SERVICE_AUTH_TOKEN` is unset; WARN-and-open on bare local run

## 3. Downstream service auth — WeatherMCP

- [ ] 3.1 Add a `OncePerRequestFilter` to WeatherMCP performing a constant-time bearer compare against `SERVICE_AUTH_TOKEN` on the MCP endpoints; health excluded; WARN-and-open when unset locally, fail-fast in docker posture
- [ ] 3.2 Tests: MockMvc 401 without/with-wrong token on the MCP path, 200 pass-through with the token, health open

## 4. AscendAgent resource server

- [ ] 4.1 `AscendAgent/build.gradle.kts`: replace `spring-boot-starter-oauth2-client` with `spring-boot-starter-oauth2-resource-server`; add `spring-security-test` to test scope
- [ ] 4.2 Rewrite `SecurityConfig.java`: JWT resource-server chain with the D4 authorization matrix (`/api/v1/ai/prompt` + `/api/v1/ingestion/upload` → `USER` or `ADMIN`; `/api/v1/ingestion/run` → `ADMIN`; `/actuator/health`, `/actuator/prometheus`, Swagger/OpenAPI paths → permitAll; anything else authenticated); CSRF stays disabled, sessions stateless; delete the HTTP Basic branch, `UserDetailsService`, and `PasswordEncoder` beans
- [ ] 4.3 Add the tolerant role-claim converter (custom `JwtAuthenticationConverter`): `realm_access.roles` when present, else top-level `roles`, mapped to `ROLE_USER` / `ROLE_ADMIN`
- [ ] 4.4 Delete `SecurityProperties.java` and the `app.security` block from `application.yaml`; add `spring.security.oauth2.resourceserver.jwt.issuer-uri` (env-overridable, docker default pointing at the compose Keycloak)
- [ ] 4.5 Add the `dev` profile chain: permitAll + startup WARN; verify default and `docker` postures require JWTs
- [ ] 4.6 Security slice tests with `SecurityMockMvcRequestPostProcessors.jwt()`: 401 tokenless, 403 for `USER` on `/ingestion/run`, 200 for `ADMIN` on `/ingestion/run`, 200 for `USER` on prompt + upload, health/prometheus/Swagger open, other actuator endpoints closed

## 5. Identity from claims

- [ ] 5.1 Create the `AuthenticatedUser` value object (userId, username, tenant, roles) and a resolver component mapping `Jwt` → `AuthenticatedUser` (`sub` → userId, `preferred_username` → username, `tenant` claim → tenant defaulting to `default`)
- [ ] 5.2 `PromptController.java`: remove the `X-User-Id` `@RequestHeader` parameter and the `defaultUserId` fallback; take identity from the resolved `AuthenticatedUser`; update the OpenAPI annotations accordingly
- [ ] 5.3 `IngestionController.java`: same identity switch for any user-attributed operation
- [ ] 5.4 Dev profile: synthesize `AuthenticatedUser(app.user.default-id, "dev", "default", [USER, ADMIN])` so downstream services see one identity code path; `app.user.default-id` survives only for this
- [ ] 5.5 Tests: identity comes from `sub` not headers; request with `X-User-Id: bob` authenticated as `alice-sub` reads/writes only `alice-sub` data; missing `tenant` claim resolves to `default`; `tenant: acme` surfaces on the identity object

## 6. AscendAgent outbound token attachment

- [ ] 6.1 Bind `SERVICE_AUTH_TOKEN` via a `@ConfigurationProperties` class (never logged, no checked-in default); attach `Authorization: Bearer` as a default header on the `SemanticMemoryClient` RestClient builder when configured, no header when absent
- [ ] 6.2 Attach the same header on the PaddleOCR ingestion client
- [ ] 6.3 Attach the header on all three MCP client connections (audioscribe, weather, ascend-web-search) via Spring AI MCP connection header config, with a WebClient customizer fallback if the connection type lacks header support
- [ ] 6.4 Tests: assert the bearer header on `SemanticMemoryClient` requests (search + wipe) via MockRestServiceServer; assert no header when the token is unset; integration test pinning the header on an MCP connection request

## 7. Secured compose posture end-to-end

- [ ] 7.1 Wire `SERVICE_AUTH_TOKEN` and issuer env vars through `docker-compose.yaml` for all six services; agent `depends_on` Keycloak healthcheck; confirm docker posture defaults to secured
- [ ] 7.2 Integration test (Testcontainers Keycloak): boot the agent against a real issuer, obtain a token, exercise the authorization matrix over HTTP
- [ ] 7.3 Full-stack smoke: one secured chat turn exercising semantic memory and one MCP tool completes with no downstream 401; tokenless `POST /api/v1/memory/wipe` against AscendMemory returns 401 and deletes nothing

## 8. e2e and Bruno migration

- [ ] 8.1 Add a token-acquisition request (password grant against the seeded realm user) to the Bruno collection at `docs/api/request/AscendAI/` and thread the bearer token through the existing requests via environment variable
- [ ] 8.2 Update the five e2e specs and tasks-templates in `AscendAgent/e2e/` for the secured posture (token step in setup, remove `X-User-Id` usage); keep the dev-profile path documented for ad-hoc manual runs
- [ ] 8.3 Run the e2e sweep against the secured stack and confirm all five specs pass

## 9. Documentation

- [ ] 9.1 Author `docs/SECURITY.md`: auth architecture, token flow diagram, claims contract (`sub` / `preferred_username` / `tenant` / roles), IdP swap recipe, service-token rotation procedure, dev-profile usage; link it from the root README documentation map
- [ ] 9.2 Update root `AGENTS.md` and per-module `AGENTS.md` files (AscendAgent, AscendMemory, AudioScribe, AscendWebSearch, PaddleOCR, WeatherMCP): new env vars (`SERVICE_AUTH_TOKEN`, issuer-uri), secured-by-default posture, dev-profile note
- [ ] 9.3 Update `AscendAgent/docs/architecture/`: ADR for the resource-server + static-service-token decision (including the client-credentials upgrade path) and refresh affected diagrams
- [ ] 9.4 Update `openspec/changes/add-auth-and-identity/tasks.md` checkboxes as work proceeds
