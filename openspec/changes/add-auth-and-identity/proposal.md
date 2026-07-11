## Why

AscendAI has no real authentication. `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/SecurityConfig.java` ships with `app.security.enabled=false` (permitAll on every request); flipping the flag only buys a single in-memory HTTP Basic user whose defaults are `admin`/`admin` (`config/properties/SecurityProperties.java`, `application.yaml` lines 68-74), with CSRF disabled. Worse, user identity — the key for chat history, RAG scoping, and semantic memory — is a client-supplied `X-User-Id` header (`controller/PromptController.java` lines 86-88) falling back to `app.user.default-id=user1`. Anyone who can reach port 9917 can read or write any user's conversation and memories by typing a header.

The downstream services are fully open: AscendMemory (:7020), AudioScribe (:7017), AscendWebSearch (:7021), PaddleOCR (:7022), and WeatherMCP (:9998) accept unauthenticated REST and MCP calls — including AscendMemory's destructive `POST /api/v1/memory/wipe` and `DELETE /api/v1/memory`. And the sibling changes now in flight (`add-tenant-isolation`, `add-usage-metering-and-quotas`, `add-audit-and-gdpr-compliance`) all presuppose a trustworthy identity; none of them can be built on a spoofable header. The Javadoc in `SecurityConfig` already names the destination — "swap for OAuth2 resource-server, JWT, or Keycloak" — and `spring-boot-starter-oauth2-client` plus `spring-boot-starter-security` are already on the classpath (`build.gradle.kts` lines 46, 76). This change is that swap.

## What Changes

- **AscendAgent becomes an OAuth2 resource server.** JWT validation against a configurable `issuer-uri`. Keycloak is the default identity provider, added as a docker-compose service with a checked-in realm export: realm `ascend-ai`, a public client for the future Flutter app (authorization-code + PKCE), and realm roles `USER` and `ADMIN`. Any OIDC-compliant identity provider (Entra ID, Google, Auth0) works by swapping the issuer-uri — no code change.
- **BREAKING: `X-User-Id` header trust is removed.** User identity is derived from validated token claims (`sub`, `preferred_username`), and a `tenant` claim is defined and propagated but not yet enforced — it is reserved for the sibling `add-tenant-isolation` change. `app.user.default-id` survives only in dev mode.
- **Role model.** `USER` may chat (`POST /api/v1/ai/prompt`) and upload documents (`POST /api/v1/ingestion/upload`); `ADMIN` additionally may trigger ingestion runs (`POST /api/v1/ingestion/run`) and any future admin endpoints. Roles map from Keycloak realm roles to Spring authorities.
- **Dev-mode escape hatch.** A `dev` profile keeps today's permitAll + default-user behaviour for local single-user work and the Bruno collection. The docker-compose posture defaults to secured.
- **Service-to-service authentication.** Every Python service (AscendMemory, AudioScribe, AscendWebSearch, PaddleOCR) and WeatherMCP requires a bearer token on both REST and MCP surfaces — a static service token injected via env var as the baseline (design discusses OAuth2 client-credentials as the upgrade path). AscendAgent attaches the token on all outbound calls: the `SemanticMemoryClient` RestClient, the ingestion clients that call PaddleOCR, and the Spring AI MCP client connections.
- **Swagger UI and actuator exposure rules** under the secured posture: health/prometheus stay reachable for infra, OpenAPI docs stay readable, everything else authenticated.
- The old `app.security.*` HTTP Basic block and in-memory user are **removed** (superseded, not deprecated — nothing external depends on them).

## Capabilities

### New Capabilities

- `agent-authentication`: AscendAgent validates JWTs as an OAuth2 resource server; endpoint authorization matrix (USER/ADMIN roles, public infra endpoints, Swagger/actuator rules); dev-profile fallback.
- `user-identity`: user identity resolved from validated token claims (`sub` / `preferred_username` / reserved `tenant`), `X-User-Id` header no longer trusted.
- `service-authentication`: bearer-token enforcement on the REST and MCP surfaces of all five downstream services, plus AscendAgent attaching the token on every outbound call.
- `identity-provider`: Keycloak as a provisioned docker-compose service with a checked-in realm export (realm, PKCE client, USER/ADMIN roles), swappable for any OIDC-compliant identity provider via issuer-uri.

### Modified Capabilities

- `semantic-memory-client`: outbound requests to AscendMemory gain a mandatory `Authorization: Bearer` header carrying the service token.

(`ingestion-security` was reviewed and left unchanged — its requirements cover upload hygiene (filename sanitization, MIME allowlist, size limits), not authentication posture. The authorization matrix for ingestion endpoints lives in `agent-authentication` to keep one source of truth.)

## Impact

- **AscendAgent**: `SecurityConfig.java` rewritten (resource server + role rules, HTTP Basic path deleted); `SecurityProperties.java` replaced; `PromptController.java` and `IngestionController.java` switch from header/param identity to the authenticated principal; new outbound token propagation on `SemanticMemoryClient`, ingestion clients, and MCP client config; `build.gradle.kts` swaps `oauth2-client` for `oauth2-resource-server`; `application.yaml` + `application-docker.yaml` gain issuer-uri and service-token config, lose the `app.security.user` block.
- **Python services** (AscendMemory, AudioScribe, AscendWebSearch, PaddleOCR): one shared-pattern FastAPI auth dependency per service checking the bearer token on REST routes, plus the equivalent check on the FastMCP surface; new `SERVICE_AUTH_TOKEN` env var.
- **WeatherMCP**: a Spring filter enforcing the same bearer token.
- **docker-compose.yaml**: new `keycloak` service + realm import volume; `SERVICE_AUTH_TOKEN` and issuer env wiring for all services.
- **e2e / Bruno**: the collection at `docs/api/request/AscendAI/` needs a token-acquisition step or must run against the dev profile — called out in tasks.
- **Docs**: root `AGENTS.md`, per-module `AGENTS.md` files, and a new `docs/SECURITY.md` (auth setup, token flow, IdP swap recipe).
- **Depends on / enables**: defines the `tenant` claim consumed by `add-tenant-isolation`; provides the identity primitive assumed by `add-usage-metering-and-quotas` and `add-audit-and-gdpr-compliance`. Network-level TLS stays with `harden-cloud-deployment`.

## Relevant Skills

- `/springboot-security`
- `/springboot-patterns`
- `/java-coding-standards`
- `/python-patterns`
- `/api-design`
- `/docker-patterns`
- `/springboot-tdd`
- `/python-testing`
