## Why

AscendAI has no real authentication. `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/SecurityConfig.java` ships with `app.security.enabled=false` (permitAll on every request); flipping the flag only buys a single in-memory HTTP Basic user whose defaults are `admin`/`admin` (`config/properties/SecurityProperties.java`, `application.yaml` lines 68-74), with CSRF disabled. Worse, user identity — the key for chat history, RAG scoping, and semantic memory — is a client-supplied `X-User-Id` header (`controller/PromptController.java` lines 86-88) falling back to `app.user.default-id=user1`. Anyone who can reach port 9917 can read or write any user's conversation and memories by typing a header.

The downstream services are fully open: AscendMemory (:7020), AudioScribe (:7017), AscendWebSearch (:7021), PaddleOCR (:7022), and WeatherMCP (:9998) accept unauthenticated REST and MCP calls — including AscendMemory's destructive `POST /api/v1/memory/wipe` and `DELETE /api/v1/memory`. And the sibling changes now in flight (`add-tenant-isolation`, `add-usage-metering-and-quotas`, `add-audit-and-gdpr-compliance`) all presuppose a trustworthy identity; none of them can be built on a spoofable header. The Javadoc in `SecurityConfig` already names the destination — "swap for OAuth2 resource-server, JWT, or Keycloak" — and `spring-boot-starter-oauth2-client` plus `spring-boot-starter-security` are already on the classpath (`build.gradle.kts` lines 46, 76). This change is that swap.

There is a second reason this has to land first, and it is newer than everything above. `docs/architecture/permission-aware-retrieval.md` settles how AscendAI decides which chunks a person may read, and its ownership table assigns six pieces of that mechanism to this change: the directory object id carried alongside the token subject, group membership resolution, the Redis principal-set cache and its time to live, the principal identifier format and its typed factory, the cross-provider identity link with reused-address detection, and the administrator API that corrects a link. Without them `add-tenant-isolation` has a filter it cannot populate and `add-document-connectors` writes access lists nothing can be matched against. The specific trap that document names is Microsoft Entra ID: its `sub` claim is pairwise per application, Microsoft Graph expresses group membership and item permissions against the immutable `oid` claim instead, and a system keyed on `sub` validates every token, returns 200 on every request, and resolves an empty group set for everybody.

## What Changes

- **AscendAgent becomes an OAuth2 resource server.** JWT validation against a configurable `issuer-uri`. Keycloak is the default identity provider, added as a docker-compose service with a checked-in realm export: realm `ascend-ai`, a public client for the future Flutter app (authorization-code + PKCE), and realm roles `USER` and `ADMIN`. Any OIDC-compliant identity provider (Entra ID, Google, Auth0) works by swapping the issuer-uri — no code change.
- **BREAKING: `X-User-Id` header trust is removed.** User identity is derived from validated token claims (`sub`, `preferred_username`), and a `tenant` claim is defined and propagated but not yet enforced — it is reserved for the sibling `add-tenant-isolation` change. `app.user.default-id` survives only in dev mode.
- **Role model.** `USER` may chat (`POST /api/v1/ai/prompt`) and upload documents (`POST /api/v1/ingestion/upload`); `ADMIN` additionally may trigger ingestion runs (`POST /api/v1/ingestion/run`) and any future admin endpoints. Roles map from Keycloak realm roles to Spring authorities.
- **Dev-mode escape hatch.** A `dev` profile keeps today's permitAll + default-user behaviour for local single-user work and the Bruno collection. The docker-compose posture defaults to secured.
- **Service-to-service authentication.** Every Python service (AscendMemory, AudioScribe, AscendWebSearch, PaddleOCR) and WeatherMCP requires a bearer token on both REST and MCP surfaces — a static service token injected via env var as the baseline (design discusses OAuth2 client-credentials as the upgrade path). AscendAgent attaches the token on all outbound calls: the `SemanticMemoryClient` RestClient, the ingestion clients that call PaddleOCR, and the Spring AI MCP client connections.
- **Swagger UI and actuator exposure rules** under the secured posture: health/prometheus stay reachable for infra, OpenAPI docs stay readable, everything else authenticated.
- The old `app.security.*` HTTP Basic block and in-memory user are **removed** (superseded, not deprecated — nothing external depends on them).
- Two subjects on the resolved identity. `sub` stays the storage partition key for chat history, semantic memory, and RAG scoping. A separate directory subject, `oid` on Microsoft Entra ID and `sub` on Google, is carried alongside it and is the only value used for directory calls and for comparison against a provider's permission entries. Neither ever stands in for the other.
- Group membership resolves at login. The token's group claim is used when it is complete, otherwise the provider's transitive membership endpoint is called, and the resolved set is cached in Redis under the issuer and subject for the shorter of the remaining token lifetime and five minutes. Nested groups are flattened by the provider rather than walked locally, and an absent group claim means fall through to the directory, never an empty set.
- A principal set on every request. A typed factory produces `namespace:type:id` principals from the resolved groups, the set is assembled once during authentication, is immutable for the life of the request, and is capped at 256. A caller over the cap gets an error rather than a truncated set, because a truncated set denies people access they actually have and looks exactly like a retrieval bug.
- Cross-provider identity link. A PostgreSQL table joins one person's login identity to their file-store identity on the normalized email address while storing each provider's own stable identifier, so a reissued address presents as a conflict instead of as inherited access. A link in the `SUSPECT` or `DISABLED` state contributes no group principals from either provider.
- Administrator API for identity links: list, inspect, and correct mappings under `/api/v1/admin/identity-links`, `ADMIN` only, because a mapping that is wrong and uncorrectable is a trap whose only symptom is one person finding nothing.
- The login issuer and the directory are configured separately, so the customer who signs in through Microsoft and stores files in Google Drive is a configuration, not a fork. Claim names are configuration; a directory adapter is code, and two ship here.
- The dev profile synthesises a usable principal set rather than an empty one, so a developer running locally against a seeded corpus actually retrieves documents instead of concluding search is broken.
- Two roles stay two roles, and roles are not principals. Roles gate endpoints, principals gate documents, and an `ADMIN` token widens the endpoint matrix while widening retrieval by nothing at all.

## Capabilities

### New Capabilities

- `agent-authentication`: AscendAgent validates JWTs as an OAuth2 resource server; endpoint authorization matrix (USER/ADMIN roles, public infra endpoints, Swagger/actuator rules); dev-profile fallback.
- `user-identity`: user identity resolved from validated token claims (`sub` / `preferred_username` / reserved `tenant`), `X-User-Id` header no longer trusted.
- `service-authentication`: bearer-token enforcement on the REST and MCP surfaces of all five downstream services, plus AscendAgent attaching the token on every outbound call.
- `identity-provider`: Keycloak as a provisioned docker-compose service with a checked-in realm export (realm, PKCE client, USER/ADMIN roles, group and email mappers), swappable for any OIDC-compliant identity provider that satisfies the claims contract, with directory lookups configured on their own axis.
- `principal-resolution`: the `namespace:type:id` principal format and its typed factory, group membership resolution from the token claim or the provider's transitive endpoint, the Redis principal-set cache, and the immutable capped principal set the search filter is later composed from.
- `identity-linking`: the cross-provider identity link record, email normalization, reused-address detection with `ACTIVE` / `SUSPECT` / `DISABLED` statuses, and the `ADMIN`-only API that lists and corrects links.

### Modified Capabilities

- `semantic-memory-client`: outbound requests to AscendMemory gain a mandatory `Authorization: Bearer` header carrying the service token.

(`ingestion-security` was reviewed and left unchanged — its requirements cover upload hygiene (filename sanitization, MIME allowlist, size limits), not authentication posture. The authorization matrix for ingestion endpoints lives in `agent-authentication` to keep one source of truth.)

## Impact

- **AscendAgent (permission-aware retrieval groundwork)**: new principal factory and value type; a membership resolver with two directory adapters (Microsoft Graph, Google Directory) behind one interface; a Redis-backed principal-set cache; an `identity_link` JPA entity, repository, and Liquibase changelog; an `ADMIN`-only identity-link controller; `app.identity.*` configuration binding claim names, directory adapters, and the principal cap.
- **AscendAgent**: `SecurityConfig.java` rewritten (resource server + role rules, HTTP Basic path deleted); `SecurityProperties.java` replaced; `PromptController.java` and `IngestionController.java` switch from header/param identity to the authenticated principal; new outbound token propagation on `SemanticMemoryClient`, ingestion clients, and MCP client config; `build.gradle.kts` swaps `oauth2-client` for `oauth2-resource-server`; `application.yaml` + `application-docker.yaml` gain issuer-uri and service-token config, lose the `app.security.user` block.
- **Python services** (AscendMemory, AudioScribe, AscendWebSearch, PaddleOCR): one shared-pattern FastAPI auth dependency per service checking the bearer token on REST routes, plus the equivalent check on the FastMCP surface; new `SERVICE_AUTH_TOKEN` env var.
- **WeatherMCP**: a Spring filter enforcing the same bearer token.
- **docker-compose.yaml**: new `keycloak` service + realm import volume; `SERVICE_AUTH_TOKEN` and issuer env wiring for all services.
- **e2e / Bruno**: the collection at `docs/api/request/AscendAI/` needs a token-acquisition step or must run against the dev profile — called out in tasks.
- **Docs**: root `AGENTS.md`, per-module `AGENTS.md` files, and a new `docs/SECURITY.md` (auth setup, token flow, IdP swap recipe).
- **Blocks**: `add-tenant-isolation` cannot compose an access-list predicate without the principal set, and `add-document-connectors` cannot write access lists without the principal format. The tasks those two changes wait on are marked in `tasks.md`.
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
- `/security-review`
- `/database-migrations`
- `/jpa-patterns`
