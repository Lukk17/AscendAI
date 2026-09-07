## Context

AscendAgent's security surface today is a placeholder. `SecurityConfig.java` is a two-branch filter chain: with `app.security.enabled=false` (the default) every request is permitAll; with it enabled, a single in-memory HTTP Basic user (`admin`/`admin` defaults from `SecurityProperties.java`) guards everything except `/actuator/health` and the Swagger paths. CSRF is disabled, sessions are stateless. User identity, the partitioning key for Redis chat history, Postgres persistence, Qdrant memory, and RAG scoping, comes from an `X-User-Id` request header (`PromptController.java:86-88`) that any client can set to any value, falling back to `app.user.default-id=user1`.

The five downstream services have zero inbound auth. Their only middleware is request-id propagation and security response headers (for example `AscendMemory/src/observability/request_context.py`). AscendMemory's `POST /api/v1/memory/wipe` and `DELETE /api/v1/memory` are destructive and reachable by anyone on the docker network or exposed port. AscendAgent talks to them via a `RestClient` in `SemanticMemoryClient`, via ingestion REST clients (PaddleOCR), and via Spring AI's MCP client (`spring.ai.mcp.client.streamable-http.connections` in `application.yaml` lines 381-388: audioscribe, weather, ascend-web-hunter).

Useful groundwork already exists: `spring-boot-starter-security` and `spring-boot-starter-oauth2-client` are on the classpath (`build.gradle.kts` lines 76, 46), and the `SecurityConfig` Javadoc explicitly earmarks the OAuth2/Keycloak swap as a separate change. This is that change.

`docs/architecture/permission-aware-retrieval.md` describes how AscendAI decides which chunks a person may read, and its ownership table assigns six elements of that mechanism here. This version delivers two: the principal identifier format with its typed factory, and group membership resolution. The other four belong to the directory work and are deferred with their analysis intact, in the Deferred section below. The supporting monorepo records are `ADR-M004` through `ADR-M009` under `docs/architecture/decisions/`.

The platform decision is settled and the scope of this change has been cut to match it. Keycloak, self-hosted, is the identity layer in production, not a local convenience with a real provider assumed behind it later. The normal shape of the product is a Keycloak account with a password: the person signs in on Keycloak's own login page and the application receives an authorization code. Groups are Keycloak realm groups, created by an administrator, assigned by an administrator, and emitted into the token by a protocol mapper. Nothing is read from a customer's Microsoft or Google directory in this version, and nothing carrying authorization meaning is imported across the broker.

Identity brokering survives as optional configuration for a customer who wants corporate single sign-on. It decides where a person authenticates. It does not decide what they may read, because that comes from the Keycloak groups an administrator put them in. Nothing on the password path depends on a brokered provider existing, and the password path is built and proven first.

Constraints:

- Sibling changes depend on this one's contract: `add-tenant-isolation` consumes the `tenant` claim defined here, and `add-usage-metering-and-quotas` and `add-audit-and-gdpr-compliance` key on the authenticated principal. The claim names must be stable before those changes land.
- The e2e suite and Bruno collection (`docs/api/request/AscendAI/`) currently send `X-User-Id` and no credentials. Local single-user workflows must keep working without a Keycloak round-trip.
- `harden-cloud-deployment` owns network and TLS. This change is app-level auth only, and tokens travel over plain HTTP inside the compose network, which is accepted here.
- `add-tenant-isolation` composes the access-list predicate into the same `SearchRequest` filter that carries the tenant predicate, and it can only do that if a principal set already exists on the request. `add-document-connectors` writes access lists that name principals, and those lists mean nothing until the principal format is fixed. Both are blocked on the identity work here, so the principal contract has to be frozen before either of them starts.
- The principal namespaces this version can actually mint are `local` and `tenant`. A directory group identifier matches nothing, which is a real limitation with a real consequence for connector-synced documents, and it has its own section below rather than a footnote.
- Keycloak is now a service the platform operates. If it is down, nobody signs in. It needs a database, certificates, backups, and a standing upgrade habit, and the upstream release cadence does not make that habit optional. This is a cost of the decision rather than a footnote to it, and it is priced in the risk list.

## Goals / Non-Goals

Goals:

- Verified user identity: every request to a protected AscendAgent endpoint carries a JWT validated against a configurable OIDC issuer, and identity fields are read from claims, never from client-controlled headers.
- Role-based authorization: `USER` (chat, upload) and `ADMIN` (ingestion run, future admin surface) mapped from realm roles.
- Closed downstream perimeter: no unauthenticated call reaches any Python service or WeatherMCP, on either the REST or the MCP surface.
- Keycloak as the product's identity layer: one self-hosted realm is the issuer in development and in production, provisioned from a checked-in export, with `docker compose up` yielding the same realm shape an operator deploys. The export is provisioning, not a test fixture.
- Password sign-in that works on its own: an administrator creates an account, sets a password policy, creates groups, and puts people in them, and that is a complete, usable product with no identity provider of the customer's involved anywhere.
- Optional corporate single sign-on: a customer's own identity provider can be brokered inside that realm as a configured entry, and adding one is an administrative procedure rather than a code change or a release.
- Issuer portability kept as an escape hatch rather than sold as the plan: the resource server still validates against a configurable `issuer-uri`, so a deployment that validates a provider's tokens directly is possible.
- Group principals on every request: the resolved identity carries the caller's Keycloak groups converted into `namespace:type:id` principals, assembled once into an immutable set that `add-tenant-isolation` composes into the search filter.

Non-Goals:

- Tenant enforcement (row filtering, collection scoping), which is `add-tenant-isolation`. This change only defines and propagates the claim.
- TLS, network segmentation, secret-manager integration, which are `harden-cloud-deployment`.
- Login UI. The Flutter app does the authorization-code and PKCE dance itself against Keycloak's own login page, and we provision its client and nothing more.
- Per-user rate limits or quotas, which are `add-usage-metering-and-quotas`.
- Audit logging of auth events, which is `add-audit-and-gdpr-compliance`.
- Enforcement of the access-list predicate inside the vector search, the `acl` payload keys, and the `tenant:everyone:{tenantId}` pseudo-group. Those belong to `add-tenant-isolation`, which composes the predicate that this change's principal set feeds.
- Capturing access lists from SharePoint or Google Drive item permissions at sync. That belongs to `add-document-connectors`, and the Named limitation section below says what this version can and cannot match.
- Reading group membership from a customer's directory, importing group identifiers across the broker, the cross-provider identity link, and the administrator API that corrects one. All deferred, with their analysis preserved below.
- Roles beyond `USER` and `ADMIN`. The role model stays at two on purpose, and that is not a statement about document permissions. Roles gate endpoints, principals gate documents. Per-document permission is expressed entirely through group principals, and an `ADMIN` token widens the endpoint matrix while widening retrieval by exactly nothing (ADR-M006).

## Decisions

Decision numbers are stable. A decision that has been deferred keeps its number and moves to the Deferred section, so a cross-reference from a sibling change or a decision record still lands on the right text.

### D1 - OAuth2 resource server with issuer-uri, not oauth2-client or a Keycloak adapter

AscendAgent validates tokens and never initiates a login. So the correct Spring artifact is `spring-boot-starter-oauth2-resource-server` (Nimbus JWT decoder plus `issuer-uri` discovery), replacing the currently unused `spring-boot-starter-oauth2-client` dependency in `build.gradle.kts`. Configuration is the standard `spring.security.oauth2.resourceserver.jwt.issuer-uri`. The decoder pulls JWKS from the issuer's discovery document. Under D2 that issuer is our own Keycloak realm and it stays the same across every customer, so the property is not a customer-onboarding lever. It remains the escape hatch for a deployment that validates a provider's tokens directly. The deprecated Keycloak Spring adapter is not an option (end of life), and rolling our own JWT filter would re-implement what Nimbus already does.

Alternatives considered: keep HTTP Basic and harden it, which has no identity claims, no roles, and no mobile-app story; session-based `oauth2Login` in the agent, which is the wrong topology, because the Flutter app is the OAuth client and the agent is a pure API.

### D2 - Keycloak is the identity layer, one realm, one issuer, and the realm export provisions it

Keycloak is the product's identity provider in production as well as locally. It is not a stand-in for a real provider that arrives later.

One realm, `ascend-ai`, serves every customer, and it is the only token issuer AscendAgent validates against. Customers are not realms. A customer is a `tenant` value, optionally plus a brokered identity provider (D15) if they want corporate sign-on. Tenant separation is enforced by the tenant claim and the search filter that `add-tenant-isolation` composes, not by a realm boundary.

That is the whole answer to the question this change previously left open about whether a multi-customer deployment needs an issuer registry. It does not. One issuer is strictly simpler than a per-customer issuer with per-customer JWKS, per-customer discovery, and a resolution step in front of token validation. The resource-server configuration in D1 stays a single `issuer-uri`, and every sibling change that assumed one issuer keeps that assumption intact.

Realm-per-customer was the alternative and it was rejected. It buys blast-radius isolation on realm configuration and per-customer session lifetimes, and it costs an issuer registry, a per-request issuer resolution before validation, N JWKS caches, and a migration for every sibling change that currently treats the issuer as fixed. The isolation it buys is isolation we already get from the tenant claim, so it is paid twice.

The compose service is `quay.io/keycloak/keycloak` with the export at `keycloak/realm-ascend-ai.json` mounted into `/opt/keycloak/data/import/`, backed by the external PostgreSQL on a dedicated `keycloak` database. Development uses `start-dev`. A production deployment uses `start` with a hostname and TLS supplied by `harden-cloud-deployment`, and the difference between the two is a command and an environment block, not a different realm.

The export is the provisioning of a real system, so what it must contain is a contract rather than a convenience:

| Element | Why it is in the export |
| :--- | :--- |
| Realm `ascend-ai`, realm roles `USER` and `ADMIN`, with `USER` as the realm default role | The role model D4 maps from, and the reason a new account has a role at all on its first sign-in |
| Public client `ascend-flutter`, authorization code with PKCE `S256`, no secret, no direct access grants | The application client. Direct access grants stay off, because a password grant is prohibited by the security standard this repo follows, and it is not what password sign-in means (D2a) |
| A realm password policy: minimum length, and brute-force detection enabled | Password sign-in is the default path, so the policy that protects it is part of the provisioning rather than something an operator remembers |
| Realm groups, and the group protocol mapper emitting them into the access token as an array of group names | The only source of group principals in this version (D9) |
| Protocol mappers emitting `tenant` and `email` into the access token | The rest of the claims contract every AscendAgent deployment reads. A mapper missing here is an empty field there |
| Realm SSO session and access token lifetimes | The staleness bound for a group change (D18). They are a product disclosure, so they are checked in rather than left at whatever the default happens to be |
| A brokered-provider template entry, disabled, carrying the tenant stamp mapper from D15 and nothing that imports an upstream authorization claim | Onboarding a customer who wants corporate sign-on becomes copying a shape that has been reviewed |
| Nothing else | No seeded human user, no direct access grants, no stored provider tokens |

The seeded test user, the `dev-all` realm group, and the direct-access-grant client that the Bruno collection and the e2e suite need are a development overlay, imported only in the development compose posture. They are not in the production export, because a seeded account with both roles is a backdoor and a password grant is one the standard forbids outright.

Why an export rather than Terraform or keycloak-config-cli: one file, no extra tooling, and the same provisioning shape this repo already uses for Grafana dashboards. The export is the source of truth. A console edit that is not reflected back into it is lost at the next clean deploy, and the runbook in `docs/SECURITY.md` says so.

Beyond role mapping (D4) and the group mapper (D9), nothing in the agent depends on a Keycloak-specific token shape.

### D2a - Password sign-in is the default, and it is not the direct access grant

The default and primary way a person signs in is with a Keycloak account and a password. The application redirects to Keycloak's own login page, the person types their password there, Keycloak returns an authorization code, and the application exchanges that code for tokens using PKCE. The application never sees, holds, or forwards the password. This is the authorization code flow, and it is what the `ascend-flutter` client is provisioned for.

The direct access grant, commonly called the resource owner password credentials grant or just the password grant, is a different mechanism. There the application itself collects the password and posts it to Keycloak's token endpoint. It looks like the same feature because both involve a password, and it is not: it puts the customer's credential inside our application, it defeats any interactive step Keycloak might add later such as a second factor or a forced password reset, and OAuth 2.1 removes it outright. The repo's security standard prohibits it.

So the two statements below are both true at once, and neither weakens the other:

- Password sign-in is the default path and must work end to end without any brokered provider.
- Direct access grants are disabled on `ascend-flutter` and on every client a customer touches.

The one place a password grant survives is the development overlay's own client, so the e2e suite and the Bruno collection can obtain a token without driving a browser. That client is not in the production export (D2), and importing the production export alone yields no client that accepts a password grant. The realm-export verification asserts exactly that.

This is written out at length because the two mechanisms are one word apart. A future reader asked to "turn on password login" could reasonably reach for `directAccessGrantsEnabled`, which would undo a defect already caught and fixed in this change.

### D3 - Identity claims

The user identifier used for Redis, Postgres, and Qdrant partitioning is the token's `sub` claim: stable, unique inside one application, never reassigned, which is everything a partition key needs. `preferred_username` is carried for logging and display only, because it can change and storage must never be keyed on it. A custom `tenant` claim is defined here and exposed on the resolved identity, but nothing in this change enforces it. Its value is `default` for a realm user who arrived through no brokered provider, which is the normal case, and for a person who arrived through a brokered provider it is the value that provider's hardcoded-attribute mapper stamped (D15). `add-tenant-isolation` owns enforcement, and defining the claim here means that sibling needs no token-format migration.

The resolved identity carries:

| Field | Source | Job |
| :--- | :--- | :--- |
| `userId` | `sub` | Storage partition key for chat history, semantic memory, RAG scoping, and log attribution |
| `username` | `preferred_username` | Display and logging only |
| `email` | `email` | Display and logging only in this version |
| `tenant` | `tenant`, defaulting to `default` | Propagated here, enforced by `add-tenant-isolation` |
| `roles` | role claim through the D4 converter | Endpoint authorization only, never retrieval breadth |
| `groupIds` | the configured group claim (D9) | The raw Keycloak group names the caller holds |
| `principals` | typed factory over `groupIds` (D8) | The immutable set the search filter is composed from (D10) |

Which claim carries the group names and which carries the email are configuration under `app.identity.claims`, not a branch in code. The value object is a Java record, resolved once per request by a dedicated resolver component and injected into controllers in place of the `userIdHeader` parameter in `PromptController` and its equivalent in `IngestionController`.

The second subject this document previously carried, a directory object id used for Microsoft Graph lookups, is deferred with the directory work. The analysis behind it is preserved in the Deferred section, because the Entra ID pairwise-subject trap it exists to avoid is real and will be needed the moment directory lookups return.

Existing `user1`-keyed local data belongs to the dev-profile identity (D5), so there is no data migration. Pre-auth data was single-user by construction.

Trade-off acknowledged and unchanged: switching identity providers later changes `sub` values and orphans per-user data. Accepted, because user data migration tooling is out of scope and `sub` is still the only claim with a stability guarantee inside one issuer. Under D2 that risk shrinks, because `sub` is Keycloak's own subject and survives a customer changing what they broker.

### D4 - Role mapping via a converter, tolerant of both Keycloak and generic shapes

Keycloak puts realm roles at `realm_access.roles`, Entra ID uses `roles`, and others use `scope`. A single `JwtAuthenticationConverter` with a custom granted-authorities converter reads `realm_access.roles` when present, else a top-level `roles` claim, and maps entries to `ROLE_USER` and `ROLE_ADMIN`. That keeps role mapping issuer-agnostic and already handles the common shapes.

The converter's job stops at roles. Group claims are not its input: the group claim is read by the membership resolver (D9) directly from the `Jwt`, under a configured claim name. Keeping the two apart is load-bearing. The converter deliberately drops role values it does not recognise, and a converter that also owned groups would drop those the same way, which is how a design ends up with a correct role model and an empty principal set.

Two roles is the entire role model and it stays that way. Roles decide which endpoints a caller may call, principals decide which chunks a caller may retrieve. `ADMIN` appears nowhere in a retrieval filter, so an administrator retrieves exactly what their group principals allow and not one chunk more.

`USER` is the realm's default role in the export, granted to every new account including every brokered one, so a person who has just signed in for the first time can use the product. `ADMIN` is assigned deliberately and never by a mapper reading a customer's claim. A customer's own directory must not be able to mint an administrator of our platform by naming a group, which is what a role mapper on a brokered provider would allow.

Authorization matrix (enforced in the filter chain, not method security, to keep one visible source of truth in `SecurityConfig`):

| Path | Rule |
|---|---|
| `/actuator/health`, `/actuator/prometheus` | permitAll (infra scrapes, no token) |
| `/v3/api-docs/**`, `/swagger-ui/**`, `/swagger-ui.html` | permitAll (docs readable, "Try it out" still needs a token) |
| `POST /api/v1/ai/prompt` | `USER` or `ADMIN` |
| `POST /api/v1/ingestion/upload` | `USER` or `ADMIN` |
| `POST /api/v1/ingestion/run` | `ADMIN` only |
| everything else | authenticated |

All other actuator endpoints stay behind authentication (the observability change already keeps them 404 or localhost-only, and this change does not widen them). CSRF remains disabled, which is correct for a stateless bearer-token API with no cookies.

### D5 - Dev profile keeps permitAll; docker defaults to secured

Spring profile `dev`: permitAll chain plus a synthetic `AuthenticatedUser(app.user.default-id, "dev", "default", [USER, ADMIN])` so every service layer downstream sees a fully-populated identity and there is exactly one identity code path. The Bruno collection and quick local runs use this. The default (no profile) and `docker` profiles require JWTs. The boolean `app.security.enabled` toggle and the `app.security.user` block are deleted, so posture is a profile decision rather than a flag, which prevents the "flag accidentally false in production" failure mode. A startup WARN fires when the `dev` chain is active.

The dev identity also carries a principal set, and it has to be a usable one. Under the deny-by-default rule from ADR-M006 a chunk matches nobody unless one of its principals appears in the caller's set, so a dev profile that synthesises an empty set hands a developer a knowledge base that answers nothing, with no way to tell that apart from a broken search. The dev identity therefore holds `tenant:everyone:default` and `local:group:dev-all`. `docs/SECURITY.md` records that a locally-ingested corpus has to carry at least one of those two principals to be retrievable under the dev profile, which is a consequence of deny-by-default rather than an exception to it.

### D6 - Service-to-service auth: static bearer token now, client-credentials as upgrade path

Baseline: one shared secret, `SERVICE_AUTH_TOKEN`, injected via env into all five downstream services and into AscendAgent. Downstream enforcement:

- Python services: a FastAPI dependency (HTTPBearer plus constant-time compare) applied to every REST router, and the same check on the FastMCP surface via its middleware or auth hook, so `/mcp` is not a bypass. `/health` (and `/ready`, `/metrics` where present) stay open for compose healthchecks and Prometheus. The same pattern in all four services, implemented per service (they share no code package, so the spec pins identical behaviour instead).
- WeatherMCP: a `OncePerRequestFilter` doing the same compare ahead of the MCP endpoints, health excluded.
- An unset or blank `SERVICE_AUTH_TOKEN` in a service means fail-fast at startup in the docker posture (refuse to boot open). A dev or local run without the env var logs a WARN and stays open, to preserve today's uvicorn and bootRun workflow.

AscendAgent attaches `Authorization: Bearer ${SERVICE_AUTH_TOKEN}` on the `SemanticMemoryClient` RestClient (default header on the builder), the PaddleOCR and ingestion clients, and the MCP client connections. Spring AI's MCP client properties support per-connection custom headers, and where a connection type lacks header support, a customizer bean on the underlying WebClient supplies it.

Why not client-credentials from day one: it doubles the moving parts (every Python service becomes a resource server needing a JWKS fetch and clock sync against Keycloak, and the agent needs a token-refresh loop) for a perimeter that is compose-internal. The upgrade path is real and cheap later: Keycloak already runs, so add a confidential client per service, switch the FastAPI dependency from string compare to JWT validation against the same issuer, and swap the static header for `client_credentials` acquisition in the agent. The spec requirements are written against "a valid bearer token" so the upgrade does not change observable contracts. Known trade-offs of the baseline: one shared secret means no per-service identity or revocation granularity, and rotation is a coordinated env change plus restart, accepted for the current single-operator deployment and revisited by `harden-cloud-deployment`.

### D7 - Test strategy

- AscendAgent: `spring-security-test` with `SecurityMockMvcRequestPostProcessors.jwt()`, so no Keycloak is needed in unit or slice tests. Cases: 401 without a token, 403 for `USER` on `/ingestion/run`, 200 with proper roles, identity resolved from `sub` and not from any header, `X-User-Id` ignored when sent.
- Python services: pytest against the FastAPI dependency, covering 401 on a missing or wrong token, 200 with the token, and `/health` open, plus one MCP-surface test proving `/mcp` rejects tokenless calls.
- Outbound: assert the bearer header on `SemanticMemoryClient` requests (MockRestServiceServer-style) and on MCP connection config.
- Realm export: the production export imports into a clean Keycloak and yields no human user and no client accepting a password grant, and the `ascend-flutter` client is public, PKCE `S256`, with direct access grants disabled. This is the assertion that keeps D2a from being undone.
- Password sign-in end to end: an authorization code obtained against Keycloak's own login page for a seeded account, exchanged with PKCE, produces a token the agent accepts on a protected endpoint. No brokered provider exists in this test.
- e2e: the Bruno collection gains a token request against the seeded test user, issued through the development overlay's client rather than the application client, because the application client has direct access grants disabled (D2, D2a). Specs run secured. The dev-profile path remains for ad-hoc manual runs.
- Membership: a token carrying two realm groups resolves two `local:group:*` principals plus the tenant pseudo-group, a token carrying no group claim resolves the tenant pseudo-group alone, and an administrator removing a person from a group results in that principal being absent from the next token they obtain.
- Principal set: assembled once and immutable, so an attempt to add to it after resolution fails; a resolved set over the cap returns 403 with the cap named and no search executed.
- Roles contribute nothing: two callers with identical group membership, one `USER` and one `ADMIN`, resolve equal principal sets.
- Brokering, which is optional and therefore tested as a separate section rather than as a precondition of anything above: a second Keycloak realm stands in for a customer's identity provider, a person signing in through the broker reaches a token stamped with the brokered provider's tenant, an upstream token claiming a different tenant does not override it, an upstream group named `ADMIN` yields no `ROLE_ADMIN`, and a brokered person's principals are exactly the Keycloak groups an administrator assigned.

### D8 - Principal identifiers: one format, one typed factory

Every principal is `namespace:type:id`, at most 128 characters, restricted to lowercase letters, digits, and `.`, `-`, `_`, `@`, so a principal is safe as a Qdrant keyword payload value and as a Redis set member with no escaping layer anywhere.

The namespaces this version mints are `local` and `tenant`. Types come from a closed set: `group`, and `everyone` for the tenant pseudo-group.

A group defined in our own Keycloak realm mints into `local:group:<slug>`, and every group in this version is such a group. The `entra` and `google` namespaces, and the rule that a directory-sourced group keeps its own directory's namespace, are deferred with the directory work below. They are recorded there rather than dropped, because an access list written from SharePoint item permissions names `entra:group:*` and minting a directory group into `local` would be the wrong answer when that work returns.

| Example | What it names |
| :--- | :--- |
| `local:group:policy-readers` | An application-local group, meaning a Keycloak realm group |
| `tenant:everyone:acme` | The pseudo-group every member of tenant `acme` belongs to |

One typed factory is the only way to construct one. It validates length, character set, namespace, and type, and it throws on anything else rather than returning a best-effort value: an unrecognised namespace is a capture bug, and it fails instead of being stored. Filters are assembled through Spring AI's `FilterExpressionBuilder` and never by string concatenation, which is the rule `add-tenant-isolation` already applies to the tenant predicate, here for the same reason.

Why a factory and not a formatting helper: the format constraints only hold if exactly one place can produce a value. A helper anybody may bypass with string concatenation is a convention, and this has to be an invariant, because a malformed principal is not an error at retrieval time. It simply matches nothing, and the symptom is missing documents.

`tenant:everyone:{tenantId}` is minted by this factory. When it is written onto a chunk is `add-tenant-isolation`'s decision, not this one's.

The namespace enum is a closed set the factory rejects outside of. Adding `entra` and `google` to it later is an additive change to one enum and one configuration key, and the Deferred section records what has to come with them.

### D9 - Group membership comes from the Keycloak group claim

An administrator creates realm groups in Keycloak, puts people in them, and a group protocol mapper in the realm export emits the group names into the access token as an array claim. AscendAgent reads that claim under a configured name and mints one `local:group:<name>` principal per entry through the D8 factory.

That is the whole mechanism. There is no directory call, no second source, and no fallback, so there is no resolution order to get wrong and no completeness test to apply. An absent group claim means the caller is in no groups, which under Keycloak-only membership is a true statement about an administrator's decision rather than a suspicious silence. That is exactly the property that made the previous design's absent claim dangerous, and it is the reason removing the directory removes an entire class of failure along with a capability.

The group names an administrator chooses have to satisfy the D8 character set, since the factory throws rather than mangling. The onboarding runbook says so and the realm export's seeded group demonstrates it.

There is no principal cache in this version. The previous design cached the resolved set in Redis for the shorter of the remaining token lifetime and five minutes, and it did that to avoid paying a directory round trip per request. Reading a claim off an already-validated token costs nothing worth caching, and a cache here would only add a second staleness window on top of the token's own. The cache design is preserved in the Deferred section, because it returns with the directory call it exists for.

### D10 - The principal set is assembled once, immutable, and capped

The set is assembled during authentication, before any controller method runs, and attached to the resolved identity. It does not change for the life of the request.

Two reasons it is immutable rather than merely computed early. A set that can grow mid-request means the filter composed for the search and the check the presigner runs can disagree, and that gap is exactly where a source reference gets a download link its chunk did not earn. And an immutable set is what makes a request explainable afterwards: one set, one filter, one answer to "why did this person see this".

Contents: `tenant:everyone:{tenantId}` for the caller's tenant, and one principal per Keycloak group the caller holds. Roles contribute nothing.

The cap is 256 principals. A caller whose resolved set exceeds it fails the request with 403 and an RFC 7807 `application/problem+json` body naming the cap, and no search runs on a truncated set. This is the same refusal ADR-M007 applies to an over-long access list, for the same reason: truncating an allow list silently denies people access they genuinely have, and that symptom is indistinguishable from a bug in retrieval, embedding, chunking, or the model.

The number is a decision this change makes, because the design document caps the set without naming a value. 256 is far above any plausible realm-group count for one person, and it keeps the `IN` clause handed to Qdrant to a size the filter evaluates without trouble. It is configurable.

### D14 - A principal set is never silently narrowed

Two paths could produce a set smaller than the truth, and neither may do it quietly.

A caller whose resolved set exceeds the cap fails the request with 403, per D10, rather than searching on a truncated set.

The dev profile synthesises a deliberate, documented set rather than an empty one, per D5.

The third path this decision used to cover, a directory call that fails and tempts a fallback to the tenant floor, does not exist in this version because there is no directory call. It returns with the directory work, and its reasoning is preserved in the Deferred section, because the reasoning is the expensive part and it will be needed again.

What remains true and worth stating: the symptom of a narrowed set is not an error. It is a 200 response, a fluent answer, and no sources, and the person who reports it says search is broken. That is why the cap refuses rather than trims, and why the dev profile is not allowed to be empty.

### D15 - Identity brokering is optional configuration for corporate sign-on

A customer who wants their people to sign in with their existing corporate account can have their identity provider brokered inside the `ascend-ai` realm. The mechanism is Keycloak's generic OpenID Connect provider pointed at the customer's own discovery document, or the SAML provider where the customer only offers SAML. AscendAgent never speaks to the customer's provider.

This is optional, and everything else in this change works without it. A customer with no brokered provider has accounts, passwords, groups, and an administrator, which is the normal shape of the product. A customer with a brokered provider has the same thing plus a different front door.

There is no Microsoft-specific provider to reach for and none is needed. Keycloak does ship social and vendor-branded provider types, and the temptation during an onboarding is to pick the one with the familiar logo. The generic OpenID Connect entry pointed at the customer's tenant-specific discovery document is the supported mechanism for a corporate directory, it is what the customer's administrator can actually hand over, and it is what the runbook says to use.

One provider per customer. Not one per person, not one shared entry with per-customer overrides. The alias of that provider is the customer's identifier inside the realm, and one thing hangs off it: the `tenant` value. A hardcoded-attribute mapper on the brokered provider stamps the customer's tenant onto every user who arrives through it, and a protocol mapper puts that attribute into the access token as the `tenant` claim D3 defines.

What does not hang off it, and this is the scope cut stated plainly: nothing about authorization. A person who arrives through a brokered provider is a realm user like any other. Their groups are the Keycloak groups an administrator put them in, and their roles are realm roles assigned on our side. No group claim, and no other attribute carrying authorization meaning, is imported from the upstream token. The upstream provider decides who the person is. It does not decide what they may read.

Two things follow directly, and both are requirements rather than observations. An upstream token that carries its own `tenant` claim naming a different customer has no effect, because the value on the issued token is the one the brokered provider stamped. And an upstream group named `ADMIN` grants no platform role, because no role mapper reads a customer's claim.

How a customer is matched to their provider at sign-in, when one exists. Two mechanisms, and both are in scope: the client application passes the provider alias as a login hint on the authorization request, which is the deterministic path a customer-specific entry URL makes possible; otherwise the realm matches the email domain the person types on the login page to the provider registered for that domain. An unmatched person must not be silently dropped into a default provider, because that is how somebody ends up authenticated into the wrong tenant. A person with no matching domain and a local account signs in with their password, which is the default path and not a failure.

Onboarding a customer onto brokering is an administrative procedure with a written runbook in `docs/SECURITY.md`: the customer hands over their discovery document and client credentials, the operator creates the brokered provider from the disabled template entry in the realm export, sets the hardcoded tenant mapper, registers the email domain, and verifies with a real sign-in that a test person reaches a token carrying the expected tenant. Group assignment is a separate administrative step in Keycloak and is not part of the brokering configuration at all.

### D18 - Membership is as fresh as the token, and the realm sets that bound

Group membership travels in the access token, so a change an administrator makes in Keycloak reaches AscendAgent when the caller next obtains a token. The staleness bound is the access token lifetime, and the realm's SSO session lifetime bounds how long a person can keep refreshing without signing in again. Both are set explicitly in the realm export rather than left at whatever the default happens to be, because they are the number a customer is told.

There is exactly one such window in this version, and it is worth saying so, because the previous design had two that were easy to conflate. Nothing in AscendAgent caches a resolved set (D9), so there is no second window on top of the token's own. An administrator who needs a removal to take effect immediately ends that person's sessions in Keycloak, which is an administrative action with an immediate effect rather than a configuration change.

`docs/SECURITY.md` records the number as a product disclosure, and the number it records is the one the export actually sets.

### D19 - Brokered providers do not store upstream tokens

No brokered provider is configured to store the token it received from the customer's identity provider, and AscendAgent does not retrieve upstream provider tokens through the broker.

In this version there is nothing to use one for, and storing one would put a third party's live credentials in our database, turning an identity store into a credential store and pulling every one of those tokens into the erasure and breach scope that `add-audit-and-gdpr-compliance` inherits. Stored tokens stay off in the realm export and off in the onboarding template.

The case that would make this a real question, a customer who will not consent to an application identity reading their directory but will consent to their own people reading their own membership, only arises when directory lookups exist. It is recorded in the Deferred section with the rest of that work.

## Named limitation: connector-synced documents are company-visible in this version

This is the one place where the scope cut changes what a customer gets, rather than only what we build, and it is written out here rather than softened into a caveat.

A document synced from a customer's own storage carries that source's group identifiers in its access list. SharePoint names an Entra ID security group by its directory object id. Google Drive names a Workspace group by its address. This version mints principals only from Keycloak realm groups, in the `local` namespace, and a Keycloak group name will never equal an Entra directory object id. So an access list captured from a customer's storage matches nobody, for everybody, always.

The consequence has two halves and both matter:

- Per-document permissions do work for documents uploaded directly into the product, where an administrator assigns Keycloak groups to a document and the caller's principal set contains those same groups. That is a complete, correct, useful mechanism and it is the one the product ships with.
- Per-document permissions match nothing at all for documents synced from a customer's own storage. Under deny-by-default (ADR-M006) that would make every synced document invisible to everybody, which is the worst possible reading of a scope cut: the feature appears to work, the sync reports success, and nobody can retrieve anything.

For this version, therefore, a connector-synced document is visible to everyone in the company. It carries `tenant:everyone:{tenantId}` and nothing else, which is the behaviour `add-document-connectors` described before it was amended to capture source access lists. That is an honest coarse answer rather than a silent denial, and it is stated to a customer as a product fact rather than left for them to discover.

What would have to be built to lift it, which is analysis this change already did and which survives in the Deferred section below rather than being deleted:

- Directory group identifiers have to reach the agent, either by a directory lookup against the customer's provider or by import across the broker. Both routes were designed here, with their failure modes, and both are deferred.
- The principal namespaces `entra` and `google` have to be added to the D8 closed set, so a directory group mints into its own directory's namespace rather than into `local`.
- A person's Keycloak identity has to be connected to their identity at the directory whose groups the access lists name, which is the cross-provider identity link, deferred as D11 and D12.
- And a decision has to be taken that this change deliberately does not take: how a directory's groups relate to Keycloak's, whether they are imported, mirrored, mapped by an administrator, or bypassed entirely by resolving membership at the directory. That is the owner's decision when the time comes, and inventing a mechanism here would be guessing at it.

Until then, the honest statement to a customer is that synced documents are company-wide and directly-uploaded documents can be restricted to groups.

## Deferred

Everything in this section was designed, checked against primary sources, and then taken out of scope by the decision that groups live in Keycloak only. None of it is wrong. It is not needed until directory-sourced groups are, and it is kept here because re-deriving it would cost more than reading it.

### Deferred D3a - The directory subject, and the Entra ID pairwise-subject trap

The resolved identity used to carry two subjects. `sub` partitions storage. A second field, `directorySubject`, was the only value used for directory calls and for comparison against a provider's permission entries, and the two never substituted for one another.

The reason is specific and it is a trap rather than a preference. Microsoft Entra ID issues a pairwise `sub`: unique per user per application, so two applications receive two different values for the same person, and Microsoft Graph has no concept of it at all. Graph expresses group membership and item permissions against `oid`, the immutable directory object id. A resolver that calls Graph with `sub` gets an empty group list back. Every token still validates, every request still returns 200, and every caller ends up holding nothing but the tenant floor. The failure is invisible at the authentication layer and total at the authorization layer.

On a directly-issued token the directory subject is `oid` for Entra and `sub` for Google. On a brokered token it is whatever the realm's protocol mapper emits from the imported attribute. The test that catches this by construction rather than by review is the one where a token carries different values in `sub` and `oid`, and swapping the two claim values swaps the two identity fields.

Also deferred with it: rejecting a token that carries no value under the configured directory-subject claim when at least one directory adapter is configured, rather than substituting `sub`.

### Deferred D9a - Directory lookup as the primary membership path, and the group emission cap

Where a directory adapter is configured, it was to be called on every cache miss and its answer used, with the token group claim read only when no adapter was configured. The directory was the primary path and the claim was the small-tenant fast path, and the ordering was the consequential part.

The reason is a cap. Microsoft limits the groups claim to 200 group identifiers for the token protocols and 150 for SAML, counting nested groups. Above the cap it does not truncate the list. It emits no groups claim at all and substitutes a pointer to a Graph endpoint, which is what the `_claim_names` and `_claim_sources` overage markers describe. That is not rare in a company of any size, and it lands on precisely the people who belong to the most groups.

Brokering makes it worse. The agent reads a Keycloak token, and the only group data in it is whatever an Attribute Importer copied across. That importer copies a JSON array of textual elements. The overage markers are not an array of strings, so they cannot cross the broker, and under force synchronisation mode the attribute is correctly removed when the upstream claim is absent. The result for an over-cap person is an empty group claim carrying no marker of any kind, which is byte-for-byte what a person who genuinely belongs to no groups looks like. On the brokered path the completeness test is not merely unreliable, it is unimplementable, because there is nothing in the token to test.

Where the agent validates a directly-issued token the completeness test still works and still earns its place: a group claim is complete only when it is present and neither `_claim_names` nor `_claim_sources` appears, and an absent claim means fall through to the directory rather than an empty group set.

Nested groups are flattened by the provider's transitive endpoint on both paths. Both vendors publish one precisely so nobody reimplements their nesting semantics, cycle handling, and limits in order to reach the same answer more slowly and more wrongly.

### Deferred D9b - The Redis principal-set cache

The resolved principal set was cached in Redis under `principals:v1:{issuerHash}:{subject}`, with a time to live of the shorter of the remaining token lifetime and five minutes, to avoid a directory round trip per request.

The key shape is load-bearing and worth keeping. The subject alone is not safe: Entra issues a pairwise `sub`, so the same string can belong to different people under different issuers, and a deployment that repoints its issuer would otherwise serve the previous issuer's cached sets. The `v1` segment lets the cached shape change without a flush. The cached value is the resolved principal set rather than the raw group list, so a hit skips the factory as well as the call. Redis being unavailable degrades latency and not correctness, because every request then pays the directory call and arrives at the same answer.

### Deferred D13 - The login issuer and the directory are configured separately

Configuration separated two axes. `spring.security.oauth2.resourceserver.jwt.issuer-uri` is the single issuer whose tokens are validated. `app.identity.directories` was a list of directory adapters, each with a provider kind (`microsoft-graph`, `google-directory`), the brokered-provider alias it serves, the principal namespace its groups mint into, and its own credentials. An empty list was valid and meant the token claim was the only source of groups.

The customer this exists for is the split-provider one: login through Microsoft Entra ID, files in Google Drive, so the groups that decide retrieval come from a directory that never issued the token being validated. A configuration model with one provider slot cannot express that customer at all.

The two provider paths are not symmetric, and a document that treats them as a pair produces a Google onboarding that waits for a claim that will never arrive:

| | Microsoft Entra ID | Google Workspace |
| :--- | :--- | :--- |
| Group identifiers in the sign-in token | Emitted only when the customer's administrator configures the optional claim on the application registration, and then only below the emission cap | Never, at any tenant size, under any configuration |
| Group identifiers across the broker | Attribute Importer copies the array when it is present | Nothing to import |
| Primary membership path | Microsoft Graph transitive `memberOf` against the directory subject | Google Workspace Directory API group listing. There is no other path |
| Claim fast path available | Yes, for a small tenant that has configured the optional claim | No |
| Directory credentials | An application registration in the customer's tenant, consented by their administrator, able to read transitive group membership | A service identity authorized by the customer's Workspace administrator to read the Directory API for their domain |

What is configuration and what is code, so a portability claim stays honest: validating a token, mapping claims onto identity fields, and mapping role claims onto authorities are configuration. Brokering a customer's provider is configuration. Calling a directory is an adapter, one class per provider behind one interface, and a third vendor is new code.

### Deferred D11 and D12 - The cross-provider identity link and its administrator API

A customer who signs in through one vendor and stores files at another has each person represented twice, by two identifiers that share nothing. The only value both systems hold is the email address, so that is the join key, and ADR-M008 is blunt that it is a weak one. The defence is to store each provider's own stable identifier alongside the address rather than instead of it, so a reissued address presents as a conflict instead of as a silent inheritance.

The store was a PostgreSQL table `identity_link` created by a Liquibase changelog, holding the normalized email, the login issuer, each provider's directory subject, the status, created and last-confirmed timestamps, and the conflicting subject recorded at detection. Unique on normalized email within a tenant, indexed on each subject. PostgreSQL rather than Redis because a link is durable state an administrator corrects and an auditor asks about, and it has to survive a flush.

Email normalization was one function applied identically everywhere: trim, Unicode NFKC, lowercase, IDNA-encode the domain, strip a `+tag` suffix from the local part. It does not strip dots. Dot-insensitivity is one provider's local-part behaviour rather than an email rule, and applying it generally would merge two genuinely different corporate addresses into one person, which is the same silent-inheritance failure arrived at from the other direction.

Three states: `ACTIVE` contributes all groups from both providers, `SUSPECT` is a detected discrepancy whose correct side has not been established and contributes none, `DISABLED` is an administrator's deliberate switch-off and contributes none. A `SUSPECT` or `DISABLED` person keeps the tenant floor, can still sign in and chat, and never inherits somebody else's access.

The administrator API was three `ADMIN`-only endpoints under `/api/v1/admin/identity-links`: a cursor-paginated list filterable by status and email, a single-link read including the conflicting subject, and a `PATCH` correcting a subject or moving the status. A successful correction deletes that person's cached principal set, so the fix takes effect on their next request rather than after the cache expires. Without that deletion the administrator fixes a link, the person still finds nothing for minutes, and the obvious conclusion is that the fix did not take.

This is deferred rather than removed because it has no consumer in a Keycloak-only world. There is one provider, one subject, and nothing to join.

### Deferred D14a - A failed directory resolution fails the request

A directory call that fails, whether by Graph throttling, an expired client secret, or an outage, was to fail the request with 503 and a `Retry-After`. It does not fall back to the tenant floor, and it does not serve a cached set past its time to live. Both of those produce a caller who is authenticated, receives 200, and cannot find documents they can open in SharePoint, which is the most expensive symptom in the whole design because it is indistinguishable from a retrieval bug.

The trade-off was stated rather than hidden: this makes directory availability into product availability on the cache-miss path. A 503 is a page for the operator. A narrowed set is somebody's week spent debugging embeddings.

### Deferred D16 - Carrying group identifiers across the broker, force mode, and the user profile declaration

Where a customer's group identifiers were to be taken from their sign-in token, the route was single and documented: an Attribute Importer mapper on the brokered provider copies the array claim element by element into a multivalued user attribute, and a protocol mapper puts that attribute into the access token as an array. Attributes written this way are administrator-context by default, so the signed-in person cannot write their own group list, which is the property that makes trusting the resulting claim defensible at all.

Three configuration points, each with a wrong setting that produces an authorization bug rather than an error:

- The synchronisation mode must be force. Under force the attribute is refreshed on every login and actively removed when the claim is absent, so a person removed from every group genuinely loses those principals at their next login. Under import it is written once at first login and never updated, freezing permissions at the moment somebody first signed in. The default is not force. A mapper created by clicking through the console and accepting defaults produces the frozen-permissions build, and nothing about it looks wrong.
- Every imported attribute must be declared in the realm's declarative user profile, administrator-writable and not user-writable. Since Keycloak 24 the user profile is enabled by default and an undeclared imported attribute is dropped silently. That default flipped in a minor release and turned working configurations into silently failing ones.
- The imported claim must be an array of textual elements. An array of objects is dropped with a warning, and a customer whose provider emits group objects needs the claim reshaped on their side. This is also why the Entra overage markers cannot cross the broker.

All three failures are silent, so configuration review is not the control. The control is a test that no code review substitutes for: remove a person from a group at the customer's directory, have them sign in again, and assert that the principal disappears from their resolved set and that chunks granted by that group only are no longer retrieved for them. It is the only test that tells force mode from import mode from outside.

### Deferred D17 - The customer's administrator has work to do

Microsoft does not emit a groups claim by default, and there is no configuration on our side that changes that. Every enterprise onboarding therefore had a step belonging to the customer, whichever product had been chosen, and a runbook that does not name it produces an onboarding that stalls with each side waiting for the other.

The customer's side, before anything is created in our realm: an application registration in their tenant carrying the broker's redirect URI, with its client credentials handed over; the optional groups claim configured on that registration with the group kinds chosen, if and only if the claim fast path is wanted; consent for the directory adapter to read transitive group membership in their tenant; and for a Google Workspace customer, a service identity authorized to read the Directory API for their domain, because for them there is no claim path at all. The exact Graph application permission constant was to be filled in during implementation against current vendor documentation rather than asserted from memory.

Under the current scope the customer-side prerequisite for brokering is only the application registration and its credentials. Everything about groups is our administrator's job in Keycloak.

### Deferred D18a - Membership is only as fresh as the last brokered login

Nothing refreshed group attributes between logins. A brokered provider writes its attributes at login and at no other time, so a group change at the customer's directory reached Keycloak when the person next signed in through the broker and not before. On the claim membership path the real staleness bound was therefore the realm's SSO session lifetime plus the access token lifetime, set by realm configuration rather than by anything in AscendAgent.

That is a second window alongside the principal cache, and the two bound different things. The cache bounds how long AscendAgent keeps its own copy of a resolved set. The session bounds how long the source of that set stays stale. Expiring the cache faster does not help on the claim path, because a fresh resolution reads the same stale attribute out of the same unchanged token. This was one of the arguments for the directory being the primary path: it is the only one of the two whose revocation window is bounded by something we set.

### Deferred D19a - Stored provider tokens as an escape hatch

Keycloak can store the token it received from the brokered provider and expose it to the application, which would let AscendAgent call the customer's directory as the signed-in person rather than as a configured application identity. It costs an extra call per request and puts a third party's live credentials in our database.

It answers one real problem: the customer who will not consent to an application identity with directory read permission but will consent to their own people reading their own membership. If that customer arrives once directory lookups exist, this is the mechanism, switched on per brokered provider as a deliberate decision with a named cost.

## Risks / Trade-offs

The first risk is not a bullet, because it is the standing cost of the platform decision rather than a hazard with a mitigation. Choosing self-hosted Keycloak is choosing to operate it. If it is down, nobody signs in, and there is no degraded mode where the product half works. It needs a database, certificates, backups with a restore that has actually been tested, and an upgrade habit that does not slip.

That habit is not optional, and the upstream release cadence is why. There is no long-term support release to sit on. Minor releases land roughly quarterly and patches roughly monthly, breaking changes have shipped inside patch releases rather than only at minor boundaries, and sixteen security advisories were published this year through August. So the operator is patching frequently, cannot treat a patch release as safe to apply blind, and cannot skip a cycle to avoid the reading. The mitigations that exist are ordinary ones: a staging realm on the same version as production, the export as the source of truth so a rebuild is deterministic, and release notes read before every upgrade. None of them removes the cost.

- Connector-synced documents are company-visible in this version, so a customer whose SharePoint has genuinely restricted material gets coarser access in AscendAI than they have at the source. This is the Named limitation section above rather than a bullet with a mitigation, it is a product disclosure, and the alternative under deny-by-default was that every synced document became invisible to everybody.
- Somebody reads "password sign-in is the default" and enables the direct access grant on the customer-facing client, undoing a defect this change already fixed. D2a states the distinction at length, the realm export asserts `directAccessGrantsEnabled` false on `ascend-flutter`, and the export verification is a task rather than a review item.
- A shared static service token is a single secret with no rotation story. Mitigated by a constant-time compare, env injection only (never in YAML defaults or logs), fail-fast when unset in the docker posture, a documented rotation procedure, and D6's client-credentials upgrade path. Secret-manager sourcing belongs to `harden-cloud-deployment`.
- Keycloak adds a boot-order dependency, so the agent fails a JWKS fetch if the issuer is down. Mitigated by compose `depends_on` with a healthcheck on Keycloak, and by the resource server's JWKS fetch being lazy and cached, so brief outages do not kill a running agent.
- Group membership is only as fresh as the token that carries it, bounded by the access token lifetime that the realm export sets explicitly. An administrator removing somebody from a group takes effect at their next token refresh, not instantly. This is a product disclosure in `docs/SECURITY.md` and the reason the lifetimes are checked in rather than defaulted.
- An administrator creating a group whose name breaks the D8 character set gets a factory that throws rather than a principal that silently matches nothing. That is the right failure, and it is a failure a person can hit while doing an ordinary administrative task, so the runbook names the constraint and the export ships a group that demonstrates it.
- Bruno and e2e breakage, because every existing request lacks credentials. Mitigated by a dedicated migration task, token acquisition scripted in the collection against the development overlay's client, a seeded realm user to make it deterministic, and the dev profile as the manual escape hatch.
- `sub` re-keys user data if the issuer is ever swapped. Accepted (D3) and documented in `docs/SECURITY.md`. Under D2 this shrinks, because `sub` is Keycloak's own subject and a customer changing what they broker keeps their people's stored data as long as the federated link is preserved.
- MCP client header injection depends on the Spring AI 1.1.5 connection config surface. Verified approach with a fallback customizer bean (D6), and an integration test pins the header actually leaving the agent.
- Sibling changes racing on claim names. This change is the declared owner of `sub`, `preferred_username`, and `tenant` semantics, and `add-tenant-isolation` consumes rather than redefines them.
- Tokens over plain HTTP inside compose. Accepted at this layer, since TLS is `harden-cloud-deployment` scope.
- The principal-set cap of 256 is a number this change picked rather than one the design fixed. It is far above any plausible realm-group count for one person, it is configurable, and any breach fails loudly with the cap named in the response body.
- Two sibling changes are blocked on this one. The principal format (D8) and the identity object shape (D3) are frozen by the tasks marked as blocking in `tasks.md`, and both land before either sibling starts.
- `add-document-connectors` is now written against a principal namespace this version does not mint. That contradiction is reported to the owner rather than resolved here, and the Named limitation section states what this change can guarantee.

## Migration Plan

Identity lands before anything that reads it, and the password path lands before brokering, because brokering is optional and nothing may depend on it.

1. Land the Keycloak compose service and the production realm export: roles with `USER` as the default, the application client with PKCE and direct access grants off, the password policy, realm groups and the group protocol mapper, the `tenant` and `email` mappers, and the session and token lifetimes D18 turns into a disclosure. Land the development overlay separately, carrying the seeded user, the `dev-all` group, and the direct-access-grant client the e2e suite uses. Nothing consumes any of it yet, so this is additive and carries no risk.
2. Prove password sign-in end to end against that realm: an account, a password, Keycloak's own login page, an authorization code exchanged with PKCE, and a token. This is the path the rest of the change is built on.
3. Land the AscendAgent resource server, the resolved identity (D3), and the principal identifier factory (D8). This is the step `add-tenant-isolation` and `add-document-connectors` are blocked on, and the contract freezes here.
4. Land group membership from the Keycloak group claim and the principal set with its cap (D9, D10, D14). Retrieval does not read the set yet, so correctness is observable through tests and through the principal-set-size metric before anything depends on it.
5. Land optional brokering: the disabled template entry proven end to end against a second Keycloak realm standing in for a customer's provider, the hardcoded tenant mapper, the proof that an upstream token cannot override the tenant or mint a role, and the brokering runbook. Nothing earlier in this list depends on this step.
6. Land downstream service auth in warn-only-when-unset mode (D6). With `SERVICE_AUTH_TOKEN` set in compose the services enforce, local bare runs keep working, and the agent does not have to be sending the token yet.
7. Land AscendAgent outbound token attachment. This has to ship before compose sets `SERVICE_AUTH_TOKEN` for every service, or the agent starts getting 401s from its own downstream calls.
8. Flip compose to the secured posture end to end, migrate the Bruno collection and the e2e suite to token acquisition, and verify the full authorization matrix.
9. Rollback: revert to the previous image tags and unset `SERVICE_AUTH_TOKEN` and the issuer environment variables. The dev profile is the operational escape hatch for a broken identity provider.

## Open Questions

- Redirect URIs for the Flutter client are finalized when the app exists. The realm export ships a placeholder loopback pattern (`http://localhost:*`) that the app change updates. Not blocking.
- The administrator assignment surface for direct uploads stays open, exactly as the design document leaves it. This change ships `local:group:*` as a principal namespace and the factory that mints it, but not the screen or API that assigns those groups to an uploaded document. Whether that lands in `add-tenant-administration` or `add-document-management-api` is a scoping decision outside these three changes. It matters more under this scope cut than it did before, because directly-uploaded documents are now the only ones per-document permissions apply to at all.
- How a customer's directory groups relate to Keycloak groups, when directory-sourced groups return. Import, mirror, administrator-authored mapping, or resolve at the directory and bypass Keycloak groups entirely are all defensible, and this change deliberately does not pick one. It is the owner's decision, and the Named limitation section names it as the thing that unlocks per-document permissions for connector-synced documents.
- Which Keycloak construct expresses the mapping from an email domain to a customer's brokered provider. More than one supported shape exists, they differ between versions, and the choice is a login-page concern rather than an authorization one. It is settled during implementation against the version actually deployed, and the requirement it has to satisfy is fixed in D15: a person whose domain matches nothing must not be dropped into a default provider.
- Whether SAML brokering is in scope for the first customer who asks for corporate sign-on. The mechanism is available and the identity-brokering capability is written to cover it, and since no group data crosses the broker in this version, the SAML and OpenID Connect paths differ in nothing that affects authorization.
