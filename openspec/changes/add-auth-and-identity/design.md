## Context

AscendAgent's security surface today is a placeholder. `SecurityConfig.java` is a two-branch filter chain: with `app.security.enabled=false` (the default) every request is permitAll; with it enabled, a single in-memory HTTP Basic user (`admin`/`admin` defaults from `SecurityProperties.java`) guards everything except `/actuator/health` and the Swagger paths. CSRF is disabled, sessions are stateless. User identity — the partitioning key for Redis chat history, Postgres persistence, Qdrant memory, and RAG scoping — comes from an `X-User-Id` request header (`PromptController.java:86-88`) that any client can set to any value, falling back to `app.user.default-id=user1`.

The five downstream services have zero inbound auth. Their only middleware is request-id propagation and security response headers (e.g. `AscendMemory/src/observability/request_context.py`). AscendMemory's `POST /api/v1/memory/wipe` and `DELETE /api/v1/memory` are destructive and reachable by anyone on the docker network or exposed port. AscendAgent talks to them via a `RestClient` in `SemanticMemoryClient`, via ingestion REST clients (PaddleOCR), and via Spring AI's MCP client (`spring.ai.mcp.client.streamable-http.connections` in `application.yaml` lines 381-388 — audioscribe, weather, ascend-web-search).

Useful groundwork already exists: `spring-boot-starter-security` and `spring-boot-starter-oauth2-client` are on the classpath (`build.gradle.kts` lines 76, 46), and the `SecurityConfig` Javadoc explicitly earmarks the OAuth2/Keycloak swap as a separate change. This is that change.

Constraints:

- Sibling changes depend on this one's contract: `add-tenant-isolation` consumes the `tenant` claim defined here; `add-usage-metering-and-quotas` and `add-audit-and-gdpr-compliance` key on the authenticated principal. The claim names must be stable before those changes land.
- The e2e suite and Bruno collection (`docs/api/request/AscendAI/`) currently send `X-User-Id` and no credentials. Local single-user workflows must keep working without a Keycloak round-trip.
- `harden-cloud-deployment` owns network/TLS. This change is app-level auth only; tokens travel over plain HTTP inside the compose network and that is accepted here.

## Goals / Non-Goals

**Goals:**

- Verified user identity: every request to a protected AscendAgent endpoint carries a JWT validated against a configurable OIDC issuer; identity fields are read from claims, never from client-controlled headers.
- Role-based authorization: `USER` (chat, upload) and `ADMIN` (ingestion run, future admin surface) mapped from IdP roles.
- Closed downstream perimeter: no unauthenticated call reaches any Python service or WeatherMCP, on either the REST or the MCP surface.
- Turnkey local IdP: `docker compose up` yields a working Keycloak with realm, client, and roles provisioned from a checked-in export — no manual clicking.
- IdP portability: switching to Entra ID, Google, or Auth0 is a config change (issuer-uri + client registration), not a code change.

**Non-Goals:**

- Tenant enforcement (row filtering, collection scoping) — `add-tenant-isolation`. This change only defines and propagates the claim.
- TLS, network segmentation, secret-manager integration — `harden-cloud-deployment`.
- Login UI. The Flutter app does the authorization-code + PKCE dance itself; we provision its client and nothing more.
- Per-user rate limits or quotas — `add-usage-metering-and-quotas`.
- Audit logging of auth events — `add-audit-and-gdpr-compliance`.
- Fine-grained per-document permissions; the role model is deliberately two roles.

## Decisions

### D1 — OAuth2 resource server with issuer-uri, not oauth2-client or a Keycloak adapter

AscendAgent validates tokens; it never initiates a login. So the correct Spring artifact is `spring-boot-starter-oauth2-resource-server` (Nimbus JWT decoder + `issuer-uri` discovery), replacing the currently unused `spring-boot-starter-oauth2-client` dependency in `build.gradle.kts`. Configuration is the standard `spring.security.oauth2.resourceserver.jwt.issuer-uri`. The decoder pulls JWKS from the issuer's discovery document, which is exactly what makes the IdP swappable: Keycloak, Entra ID, and Google all publish OIDC discovery, so moving IdP means changing one property (plus re-registering the client in the new IdP). The deprecated Keycloak Spring adapter is not an option (EOL); rolling our own JWT filter would re-implement what Nimbus already does.

Alternatives considered: (a) keep HTTP Basic and harden it — no identity claims, no roles, no mobile-app story; (b) session-based `oauth2Login` in the agent — wrong topology, the Flutter app is the OAuth client, the agent is a pure API.

### D2 — Keycloak as default IdP, provisioned by realm export import

A `keycloak` compose service (`quay.io/keycloak/keycloak`, `start-dev --import-realm`) with a checked-in export at `keycloak/realm-ascend-ai.json` mounted into `/opt/keycloak/data/import/`. The export defines: realm `ascend-ai`; realm roles `USER` and `ADMIN`; a public client `ascend-flutter` with authorization-code + PKCE (`S256`), no client secret, redirect URIs parameterized for the future app; a seeded local test user carrying both roles for the e2e suite. Keycloak backs itself with the existing external PostgreSQL (separate `keycloak` database) so realm state survives container recreation beyond the import.

Why an export, not Terraform/keycloak-config-cli: one file, zero extra tooling, identical to how Grafana dashboards are provisioned in this repo — checked-in artifact, imported at boot. The export is the source of truth; manual console edits are not.

The design explicitly does not depend on any Keycloak-specific token shape except role mapping (D4). Everything else is plain OIDC.

### D3 — Identity claims: `sub` as the stable key, `preferred_username` as display, `tenant` reserved

The user identifier used for Redis/Postgres/Qdrant partitioning becomes the token's `sub` claim — stable, unique per IdP, never reassigned. `preferred_username` is carried for logging/display only (it can change; never key storage on it). A custom `tenant` claim is defined now (Keycloak client protocol mapper in the realm export, hardcoded to `default` for the local realm) and exposed on the resolved identity object, but nothing enforces it — `add-tenant-isolation` owns enforcement. Defining it here means that sibling change needs no token-format migration.

A small `AuthenticatedUser` value object (userId, username, tenant, roles) is resolved once from the `Jwt` principal by a dedicated resolver component and injected into controllers, replacing the `userIdHeader` parameter in `PromptController` and the equivalent in `IngestionController`. Existing `user1`-keyed local data simply belongs to the dev-profile identity (D5); no data migration — pre-auth data was single-user by construction.

Trade-off acknowledged: switching IdPs later changes `sub` values and orphans per-user data. Accepted — user data migration tooling is out of scope, and `sub` is still the only claim with a stability guarantee inside one IdP.

### D4 — Role mapping via a converter, tolerant of both Keycloak and generic shapes

Keycloak puts realm roles at `realm_access.roles`; Entra ID uses `roles`; others use `scope`. A single `JwtAuthenticationConverter` with a custom granted-authorities converter reads `realm_access.roles` when present, else a top-level `roles` claim, and maps entries to `ROLE_USER` / `ROLE_ADMIN`. This keeps the "any OIDC IdP via issuer-uri swap" promise honest: the only IdP-specific code in the agent is this one converter, and it already handles the common shapes.

Authorization matrix (enforced in the filter chain, not method security, to keep one visible source of truth in `SecurityConfig`):

| Path | Rule |
|---|---|
| `/actuator/health`, `/actuator/prometheus` | permitAll (infra scrapes, no token) |
| `/v3/api-docs/**`, `/swagger-ui/**`, `/swagger-ui.html` | permitAll (docs readable; "Try it out" still needs a token) |
| `POST /api/v1/ai/prompt` | `USER` or `ADMIN` |
| `POST /api/v1/ingestion/upload` | `USER` or `ADMIN` |
| `POST /api/v1/ingestion/run` | `ADMIN` only |
| everything else | authenticated |

All other actuator endpoints stay behind authentication (the observability change already keeps them 404/localhost; this change does not widen them). CSRF remains disabled — correct for a stateless bearer-token API with no cookies.

### D5 — Dev profile keeps permitAll; docker defaults to secured

Spring profile `dev`: permitAll chain plus a synthetic `AuthenticatedUser(app.user.default-id, "dev", "default", [USER, ADMIN])` so every service layer downstream sees a fully-populated identity and there is exactly one identity code path. The Bruno collection and quick local runs use this. The default (no profile) and `docker` profiles require JWTs. The boolean `app.security.enabled` toggle and the `app.security.user` block are deleted — posture is now a profile decision, not a flag, which prevents the "flag accidentally false in prod" failure mode. A startup WARN fires when the `dev` chain is active.

### D6 — Service-to-service auth: static bearer token now, client-credentials as upgrade path

Baseline: one shared secret, `SERVICE_AUTH_TOKEN`, injected via env into all five downstream services and into AscendAgent. Downstream enforcement:

- Python services: a FastAPI dependency (HTTPBearer + constant-time compare) applied to every REST router, and the same check on the FastMCP surface via its middleware/auth hook, so `/mcp` is not a bypass. `/health` (and `/ready`, `/metrics` where present) stay open for compose healthchecks and Prometheus. Same pattern in all four services, implemented per-service (they share no code package; the spec pins identical behaviour instead).
- WeatherMCP: a `OncePerRequestFilter` doing the same compare ahead of the MCP endpoints, health excluded.
- Unset/blank `SERVICE_AUTH_TOKEN` in a service ⇒ fail-fast at startup in docker posture (refuse to boot open); the dev/local run without the env var logs a WARN and stays open to preserve today's uvicorn/bootRun workflow.

AscendAgent attaches `Authorization: Bearer ${SERVICE_AUTH_TOKEN}` on: the `SemanticMemoryClient` RestClient (default header on the builder), the PaddleOCR/ingestion clients, and the MCP client connections — Spring AI's MCP client properties support per-connection custom headers; where a connection type lacks header support, a customizer bean on the underlying WebClient supplies it.

Why not client-credentials from day one: it doubles the moving parts (every Python service becomes a resource server needing JWKS fetch + clock sync against Keycloak, and the agent needs a token-refresh loop) for a perimeter that is compose-internal. The upgrade path is real and cheap later: Keycloak already runs; add a confidential client per service, switch the FastAPI dependency from string-compare to JWT validation (`python-jose`/`authlib` against the same issuer), and swap the static header for `client_credentials` acquisition in the agent. The spec requirements are written against "a valid bearer token" so the upgrade does not change observable contracts. Known trade-offs of the baseline: one shared secret means no per-service identity or revocation granularity, and rotation is a coordinated env change + restart — accepted for the current single-operator deployment, revisited by `harden-cloud-deployment`.

### D7 — Test strategy

- AscendAgent: `spring-security-test` with `SecurityMockMvcRequestPostProcessors.jwt()` — no Keycloak needed in unit/slice tests. Cases: 401 without token, 403 for `USER` on `/ingestion/run`, 200 with proper roles, identity resolved from `sub` not from any header, `X-User-Id` ignored when sent.
- Python services: pytest against the FastAPI dependency — 401 missing/wrong token, 200 with token, `/health` open; one MCP-surface test proving `/mcp` rejects tokenless calls.
- Outbound: assert the bearer header on `SemanticMemoryClient` requests (MockRestServiceServer-style) and on MCP connection config.
- e2e: the Bruno collection gains a Keycloak password-grant token request against the seeded test user; specs run secured. Dev-profile path remains for ad-hoc manual runs.

## Risks / Trade-offs

- [Shared static service token is a single secret with no rotation story] → Constant-time compare, env-injection only (never in YAML defaults or logs), fail-fast when unset in docker posture, documented rotation procedure, and D6's client-credentials upgrade path. Secret-manager sourcing belongs to `harden-cloud-deployment`.
- [Keycloak adds a boot-order dependency: agent fails JWKS fetch if issuer is down] → compose `depends_on` with healthcheck on Keycloak; resource-server JWKS fetch is lazy (first request) and cached, so brief IdP outages do not kill a running agent.
- [Bruno/e2e breakage — every existing request lacks credentials] → dedicated migration task; token acquisition scripted in the collection; seeded realm user makes it deterministic; dev profile keeps the manual escape hatch.
- [`sub` re-keys user data if the IdP is ever swapped] → accepted (D3); documented in `docs/SECURITY.md`.
- [MCP client header injection depends on Spring AI 1.1.5 connection config surface] → verified approach with fallback customizer bean (D6); an integration test pins the header actually leaving the agent.
- [Sibling changes racing on claim names] → this change is the declared owner of `sub`/`preferred_username`/`tenant` semantics; `add-tenant-isolation` consumes, never redefines.
- [Tokens over plain HTTP inside compose] → accepted at this layer; TLS is `harden-cloud-deployment` scope.

## Migration Plan

1. Land Keycloak compose service + realm export; nothing consumes it yet (additive, zero risk).
2. Land downstream service auth in warn-only-when-unset mode (D6): with `SERVICE_AUTH_TOKEN` set in compose they enforce; local bare runs keep working.
3. Land AscendAgent resource server + identity resolution + outbound token attachment in the same release (agent must send the token before downstream enforcement can be strict).
4. Flip compose to the secured posture end-to-end; migrate Bruno/e2e to token acquisition; verify the full matrix.
5. Rollback: revert to the previous image tags and unset `SERVICE_AUTH_TOKEN` / issuer env; the dev profile is the operational escape hatch for a broken IdP.

## Open Questions

- None blocking. Redirect URIs for the Flutter client will be finalized when the app exists; the realm export ships a placeholder (`http://localhost:*` loopback pattern) that the app change updates.
