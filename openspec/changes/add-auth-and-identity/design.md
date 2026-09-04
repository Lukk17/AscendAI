## Context

AscendAgent's security surface today is a placeholder. `SecurityConfig.java` is a two-branch filter chain: with `app.security.enabled=false` (the default) every request is permitAll; with it enabled, a single in-memory HTTP Basic user (`admin`/`admin` defaults from `SecurityProperties.java`) guards everything except `/actuator/health` and the Swagger paths. CSRF is disabled, sessions are stateless. User identity — the partitioning key for Redis chat history, Postgres persistence, Qdrant memory, and RAG scoping — comes from an `X-User-Id` request header (`PromptController.java:86-88`) that any client can set to any value, falling back to `app.user.default-id=user1`.

The five downstream services have zero inbound auth. Their only middleware is request-id propagation and security response headers (e.g. `AscendMemory/src/observability/request_context.py`). AscendMemory's `POST /api/v1/memory/wipe` and `DELETE /api/v1/memory` are destructive and reachable by anyone on the docker network or exposed port. AscendAgent talks to them via a `RestClient` in `SemanticMemoryClient`, via ingestion REST clients (PaddleOCR), and via Spring AI's MCP client (`spring.ai.mcp.client.streamable-http.connections` in `application.yaml` lines 381-388 — audioscribe, weather, ascend-web-search).

Useful groundwork already exists: `spring-boot-starter-security` and `spring-boot-starter-oauth2-client` are on the classpath (`build.gradle.kts` lines 76, 46), and the `SecurityConfig` Javadoc explicitly earmarks the OAuth2/Keycloak swap as a separate change. This is that change.

A newer document has since fixed part of this change's contract. `docs/architecture/permission-aware-retrieval.md` describes how AscendAI decides which chunks a person may read, and its ownership table assigns six elements of that mechanism here: the directory object id carried alongside the token subject, group membership resolution, the Redis principal-set cache and its time to live, the principal identifier format and its typed factory, the cross-provider identity link with reused-address detection, and the administrator API that corrects a link. The supporting records are `ADR-M004` through `ADR-M009` under `docs/architecture/decisions/`. This change does not get to redesign any of them. It implements them.

Constraints:

- Sibling changes depend on this one's contract: `add-tenant-isolation` consumes the `tenant` claim defined here; `add-usage-metering-and-quotas` and `add-audit-and-gdpr-compliance` key on the authenticated principal. The claim names must be stable before those changes land.
- The e2e suite and Bruno collection (`docs/api/request/AscendAI/`) currently send `X-User-Id` and no credentials. Local single-user workflows must keep working without a Keycloak round-trip.
- `harden-cloud-deployment` owns network/TLS. This change is app-level auth only; tokens travel over plain HTTP inside the compose network and that is accepted here.
- `add-tenant-isolation` composes the access-list predicate into the same `SearchRequest` filter that carries the tenant predicate, and it can only do that if a principal set already exists on the request. `add-document-connectors` writes access lists that name principals, and those lists mean nothing until the principal format is fixed. Both changes are blocked on the identity work here, so the principal contract has to be frozen before either of them starts.
- Microsoft Entra ID issues a pairwise `sub`: unique per user per application, and unknown to Microsoft Graph. Group membership and item permissions in Graph are expressed against the `oid` claim instead. That single fact is why the resolved identity carries two subjects rather than one, and why a design that keys directory lookups on `sub` authenticates perfectly and authorizes nothing.

## Goals / Non-Goals

**Goals:**

- Verified user identity: every request to a protected AscendAgent endpoint carries a JWT validated against a configurable OIDC issuer; identity fields are read from claims, never from client-controlled headers.
- Role-based authorization: `USER` (chat, upload) and `ADMIN` (ingestion run, future admin surface) mapped from IdP roles.
- Closed downstream perimeter: no unauthenticated call reaches any Python service or WeatherMCP, on either the REST or the MCP surface.
- Turnkey local IdP: `docker compose up` yields a working Keycloak with realm, client, and roles provisioned from a checked-in export — no manual clicking.
- IdP portability for authentication: switching the token issuer to Entra ID, Google, or Auth0 is a configuration change (issuer-uri plus a client registration and a claim-name mapping), not a code change. Directory lookups are a separate axis and D13 states honestly what they cost.
- Group principals on every request: the resolved identity carries the caller's directory groups converted into `namespace:type:id` principals, assembled once into an immutable set that `add-tenant-isolation` composes into the search filter.
- Detectable cross-provider identity: a customer who signs in through one vendor and stores files at another gets one linked person, and a reissued email address surfaces as a conflict rather than as inherited access.
- Correctable mappings: an administrator can see why one person's principal set collapsed and fix it, without a database console.

**Non-Goals:**

- Tenant enforcement (row filtering, collection scoping) — `add-tenant-isolation`. This change only defines and propagates the claim.
- TLS, network segmentation, secret-manager integration — `harden-cloud-deployment`.
- Login UI. The Flutter app does the authorization-code + PKCE dance itself; we provision its client and nothing more.
- Per-user rate limits or quotas — `add-usage-metering-and-quotas`.
- Audit logging of auth events — `add-audit-and-gdpr-compliance`.
- Enforcement of the access-list predicate inside the vector search, the `acl` payload keys, and the `tenant:everyone:{tenantId}` pseudo-group. Those belong to `add-tenant-isolation`, which composes the predicate that this change's principal set feeds.
- Capturing access lists from SharePoint or Google Drive item permissions at sync. That belongs to `add-document-connectors`.
- Roles beyond `USER` and `ADMIN`. The role model stays at two on purpose, and that is not a statement about document permissions. Roles gate endpoints; principals gate documents. Per-document permission is expressed entirely through group principals, which this change does resolve, and an `ADMIN` token widens the endpoint matrix while widening retrieval by exactly nothing (ADR-M006).

## Decisions

### D1 — OAuth2 resource server with issuer-uri, not oauth2-client or a Keycloak adapter

AscendAgent validates tokens; it never initiates a login. So the correct Spring artifact is `spring-boot-starter-oauth2-resource-server` (Nimbus JWT decoder + `issuer-uri` discovery), replacing the currently unused `spring-boot-starter-oauth2-client` dependency in `build.gradle.kts`. Configuration is the standard `spring.security.oauth2.resourceserver.jwt.issuer-uri`. The decoder pulls JWKS from the issuer's discovery document, which is exactly what makes the IdP swappable: Keycloak, Entra ID, and Google all publish OIDC discovery, so moving IdP means changing one property (plus re-registering the client in the new IdP). The deprecated Keycloak Spring adapter is not an option (EOL); rolling our own JWT filter would re-implement what Nimbus already does.

Alternatives considered: (a) keep HTTP Basic and harden it — no identity claims, no roles, no mobile-app story; (b) session-based `oauth2Login` in the agent — wrong topology, the Flutter app is the OAuth client, the agent is a pure API.

### D2 — Keycloak as default IdP, provisioned by realm export import

A `keycloak` compose service (`quay.io/keycloak/keycloak`, `start-dev --import-realm`) with a checked-in export at `keycloak/realm-ascend-ai.json` mounted into `/opt/keycloak/data/import/`. The export defines: realm `ascend-ai`; realm roles `USER` and `ADMIN`; a public client `ascend-flutter` with authorization-code + PKCE (`S256`), no client secret, redirect URIs parameterized for the future app; a seeded local test user carrying both roles for the e2e suite. Keycloak backs itself with the existing external PostgreSQL (separate `keycloak` database) so realm state survives container recreation beyond the import.

Why an export, not Terraform/keycloak-config-cli: one file, zero extra tooling, identical to how Grafana dashboards are provisioned in this repo — checked-in artifact, imported at boot. The export is the source of truth; manual console edits are not.

The design explicitly does not depend on any Keycloak-specific token shape except role mapping (D4). Everything else is plain OIDC.

### D3 - Identity claims: `sub` partitions storage, a separate directory subject drives lookups

The user identifier used for Redis, Postgres, and Qdrant partitioning is the token's `sub` claim: stable, unique inside one application, never reassigned, which is everything a partition key needs. `preferred_username` is carried for logging and display only, because it can change and storage must never be keyed on it. A custom `tenant` claim is defined here (a Keycloak client protocol mapper in the realm export, emitting `default` for the local realm) and exposed on the resolved identity, but nothing in this change enforces it. `add-tenant-isolation` owns enforcement, and defining the claim here means that sibling needs no token-format migration.

`sub` is not sufficient for authorization, and on Microsoft Entra ID it is actively wrong for it. Entra issues a pairwise `sub`: unique per user per application, so two applications receive two different values for the same person, and Microsoft Graph has no concept of it at all. Graph expresses group membership and item permissions against `oid`, the immutable directory object id. A resolver that calls Graph with `sub` gets an empty group list back. Every token still validates, every request still returns 200, and every caller ends up holding nothing but `tenant:everyone`. The failure is invisible at the authentication layer and total at the authorization layer, which is why it gets its own paragraph rather than a footnote.

The resolved identity therefore carries both, as separately named fields that never substitute for one another:

| Field | Source | Job |
| :--- | :--- | :--- |
| `userId` | `sub` | Storage partition key for chat history, semantic memory, RAG scoping, and log attribution |
| `directorySubject` | per-provider claim: `oid` on Entra ID, `sub` on Google | The only value used for directory calls and for comparison against a provider's permission entries |
| `username` | `preferred_username` | Display and logging only |
| `email` | `email`, normalized by the D11 function | The join key for the cross-provider identity link |
| `tenant` | `tenant`, defaulting to `default` | Propagated here, enforced by `add-tenant-isolation` |
| `roles` | role claim through the D4 converter | Endpoint authorization only, never retrieval breadth |
| `groupIds` | group claim or directory lookup (D9) | The raw provider group identifiers the caller holds |
| `principals` | typed factory over `groupIds` (D8) | The immutable set the search filter is composed from (D10) |

Which claim fills `directorySubject` and which fills `groupIds` is a per-provider mapping in configuration (D13), not a branch in code. The value object is a Java record, resolved once per request by a dedicated resolver component and injected into controllers in place of the `userIdHeader` parameter in `PromptController` and its equivalent in `IngestionController`.

Existing `user1`-keyed local data belongs to the dev-profile identity (D5), so there is no data migration: pre-auth data was single-user by construction.

Trade-off acknowledged and unchanged: switching identity providers later changes `sub` values and orphans per-user data. Accepted, because user data migration tooling is out of scope and `sub` is still the only claim with a stability guarantee inside one issuer.

### D4 — Role mapping via a converter, tolerant of both Keycloak and generic shapes

Keycloak puts realm roles at `realm_access.roles`; Entra ID uses `roles`; others use `scope`. A single `JwtAuthenticationConverter` with a custom granted-authorities converter reads `realm_access.roles` when present, else a top-level `roles` claim, and maps entries to `ROLE_USER` / `ROLE_ADMIN`. That keeps role mapping issuer-agnostic, and it already handles the common shapes. It does not by itself make the whole identity provider swappable any more. Once group membership has to be resolved, a provider whose groups are not fully carried in the token needs a directory adapter as well, and that is provider-specific code by construction. D13 states which half is configuration and which half is code.

The converter's job stops at roles. It maps role claims to `ROLE_USER` and `ROLE_ADMIN`, and it discards nothing that matters, because group claims are not its input: the group claim is read by the membership resolver (D9) directly from the `Jwt`, under a configured claim name. Keeping the two apart is load-bearing. The converter deliberately drops role values it does not recognise, and a converter that also owned groups would drop those the same way, which is how a design ends up with a correct role model and an empty principal set.

Two roles is the entire role model and it stays that way. Roles decide which endpoints a caller may call. Principals decide which chunks a caller may retrieve. `ADMIN` appears nowhere in a retrieval filter, so an administrator retrieves exactly what their group principals allow and not one chunk more.

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

The dev identity also carries a principal set, and it has to be a usable one. Under the deny-by-default rule from ADR-M006 a chunk matches nobody unless one of its principals appears in the caller's set, so a dev profile that synthesises an empty set hands a developer a knowledge base that answers nothing, with no way to tell that apart from a broken search. The dev identity therefore holds `tenant:everyone:default` and `local:group:dev-all`. `docs/SECURITY.md` records that a locally-ingested corpus has to carry at least one of those two principals to be retrievable under the dev profile, which is a consequence of deny-by-default rather than an exception to it.

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
- Identity fields: a token carrying `sub` and `oid` resolves `userId` from `sub` and `directorySubject` from `oid`, and swapping the two values in the token swaps them on the resolved identity. This is the one test that catches the Entra ID trap by construction rather than by review.
- Membership resolution: a complete `groups` claim resolves without any directory call; a token with no `groups` and with `_claim_names` present triggers the directory call; a token with neither resolves to `tenant:everyone` only. All three assert on the directory client being called or not, against a stubbed adapter.
- Principal cache: a second request inside the time to live issues no directory call; a request after expiry issues one; a cache key built from a different issuer does not hit the first entry.
- Principal set: assembled once and immutable, so an attempt to add to it after resolution fails; a resolved set over the cap returns 403 with the cap named and no search executed.
- Identity link: a first login creates an `ACTIVE` link; a second login with matching identifiers confirms it; a login with the same normalized email and a different provider subject moves it to `SUSPECT` and resolves a principal set containing `tenant:everyone:{tenantId}` and no group from either provider. Email normalization is tested against the specific forms each provider emits, including the dot-bearing address that must not be merged.
- Administrator API: `USER` gets 403 on every identity-link endpoint; `ADMIN` lists, reads, and corrects; a successful correction removes that person's cached principal set, proven by the next resolution issuing a directory call.
- Directory failure: a directory adapter that throws produces 503 with `Retry-After` and no search, rather than a 200 with a narrow set.

### D8 - Principal identifiers: one format, one typed factory

Every principal is `namespace:type:id`, at most 128 characters, restricted to lowercase letters, digits, and `.`, `-`, `_`, `@`, so a principal is safe as a Qdrant keyword payload value and as a Redis set member with no escaping layer anywhere.

Namespaces come from a closed set: `entra`, `google`, `local`, `tenant`. Types come from a closed set: `group`, and `everyone` for the tenant pseudo-group. Keycloak, the default local identity provider, is not a corporate directory, so its groups mint into `local:group:<slug>`. That keeps the closed set closed and it describes what those groups actually are.

| Example | What it names |
| :--- | :--- |
| `entra:group:8f4a1b2c-3d5e-4f60-9a1b-2c3d4e5f6071` | A Microsoft Entra ID security group, named by its directory object id |
| `google:group:engineering@acme.example` | A Google Workspace group, named by its group address |
| `local:group:policy-readers` | An application-local group, including any Keycloak realm group |
| `tenant:everyone:acme` | The pseudo-group every member of tenant `acme` belongs to |

One typed factory is the only way to construct one. It validates length, character set, namespace, and type, and it throws on anything else rather than returning a best-effort value: an unrecognised namespace is a capture bug, and it fails instead of being stored. Filters are assembled through Spring AI's `FilterExpressionBuilder` and never by string concatenation, which is the rule `add-tenant-isolation` already applies to the tenant predicate, here for the same reason.

Why a factory and not a formatting helper: the format constraints only hold if exactly one place can produce a value. A helper anybody may bypass with string concatenation is a convention, and this has to be an invariant, because a malformed principal is not an error at retrieval time. It simply matches nothing, and the symptom is missing documents.

`tenant:everyone:{tenantId}` is minted by this factory. When it is written onto a chunk is `add-tenant-isolation`'s decision, not this one's.

### D9 - Membership resolution: token claim first, transitive endpoint second, Redis in front of both

Per token, in the order ADR-M007 fixes:

1. Read the configured group claim, and use it only when it is complete.
2. Otherwise call the provider's transitive membership endpoint against `directorySubject`. Microsoft Graph's transitive `memberOf` for Entra ID, the Directory API group listing for Google Workspace.
3. Cache the resolved principal set in Redis, keyed by issuer and subject, with a time to live of the shorter of the remaining token lifetime and five minutes.

Complete means the claim is present and the provider has not signalled an overflow. Microsoft Entra ID omits `groups` entirely when a user belongs to more group objects than the token can carry, and substitutes `_claim_names` and `_claim_sources` pointing at a Graph endpoint. So the completeness test is: the group claim is present and neither `_claim_names` nor `_claim_sources` is. An absent claim means fall through to step 2. It never means an empty group set. Reading absence as emptiness gives the most heavily-permissioned people in the company the least access, and it does it silently, which is why this is a named test rather than a null check.

Nested groups are flattened by the provider. Both vendors publish a transitive endpoint precisely so nobody reimplements their nesting semantics, their cycle handling, and their limits in order to reach the same answer more slowly and more wrongly.

The cache key is `principals:v1:{issuerHash}:{subject}`, where `issuerHash` is a short stable hash of the issuer URI. The subject alone is not a safe key: Entra issues a pairwise `sub`, so the same string can belong to different people under different issuers, and a deployment that repoints its issuer would otherwise serve the previous issuer's cached sets. The `v1` segment lets the cached shape change without a flush.

The cached value is the resolved principal set, not the raw group list, so a cache hit skips the factory as well as the directory call. Redis being unavailable degrades latency and not correctness: every request pays the directory call and arrives at the same answer.

### D10 - The principal set is assembled once, immutable, and capped

The set is assembled during authentication, before any controller method runs, and attached to the resolved identity. It does not change for the life of the request.

Two reasons it is immutable rather than merely computed early. A set that can grow mid-request means the filter composed for the search and the check the presigner runs can disagree, and that gap is exactly where a source reference gets a download link its chunk did not earn. And an immutable set is what makes a request explainable afterwards: one set, one filter, one answer to "why did this person see this".

Contents: `tenant:everyone:{tenantId}` for the caller's tenant, one principal per resolved group, and any application-local group assignments. Roles contribute nothing.

The cap is 256 principals. A caller whose resolved set exceeds it fails the request with 403 and an RFC 7807 `application/problem+json` body naming the cap, and no search runs on a truncated set. This is the same refusal ADR-M007 applies to an over-long access list, for the same reason: truncating an allow list silently denies people access they genuinely have, and that symptom is indistinguishable from a bug in retrieval, embedding, chunking, or the model.

The number is a decision this change makes, because the design document caps the set without naming a value. 256 sits above both of Entra ID's token group-emission limits, so anybody whose groups fit inside a token is never near it, and it keeps the `IN` clause handed to Qdrant to a size the filter evaluates without trouble. It is configurable, and setting it below the emission limits is a misconfiguration rather than a tuning choice.

### D11 - Cross-provider identity link: PostgreSQL, three states, email as the join key

A customer who signs in through Microsoft and stores files in Google Drive has each person represented twice, by two identifiers that share nothing. The only value both systems hold is the email address, so that is the join key, and ADR-M008 is blunt that it is a weak one. The defence is to store each provider's own stable identifier alongside the address rather than instead of it, so a reissued address presents as a conflict instead of as a silent inheritance.

Storage is a PostgreSQL table `identity_link`, created by a Liquibase changelog like every other schema change in this module. Columns: the normalized email, the login issuer, the login provider's directory subject, the file provider's directory subject, the status, created and last-confirmed timestamps, and the conflicting subject recorded at the moment a conflict was detected. Unique on the normalized email within a tenant, and indexed on each subject.

PostgreSQL rather than Redis because a link is durable state that an administrator corrects and an auditor asks about, not a cache. It has to survive a Redis flush and it has to be queryable by email and by either subject.

Email normalization is one function, applied identically at login and at any later reconciliation: trim, Unicode NFKC, lowercase, IDNA-encode the domain, and strip a `+tag` suffix from the local part. It does not strip dots. Dot-insensitivity is a Gmail behaviour rather than an email one, and applying it generally would merge two genuinely different corporate addresses into one person, which is this record's own failure mode arrived at from the other direction.

| Status | Meaning | Group principals contributed |
| :--- | :--- | :--- |
| `ACTIVE` | Created, or confirmed with both provider identifiers matching what is on file | All groups from both providers |
| `SUSPECT` | The same normalized email presented a different provider subject than the one on file, which is what a reissued address looks like | None |
| `DISABLED` | An administrator turned the link off | None |

The design document calls the conflict state broken. `SUSPECT` is that state under a name that says what is actually known: a discrepancy has been detected, and which side is wrong has not been established.

At login the agent normalizes the email, looks the link up, and creates it, confirms it, or moves it to `SUSPECT`. A `SUSPECT` or `DISABLED` link contributes no group principals from either provider, so the caller keeps `tenant:everyone:{tenantId}` and nothing else. They can still sign in, still chat, and still retrieve whatever is tenant-wide. They never inherit somebody else's access.

### D12 - Administrator API for identity links

A person can sit in `SUSPECT` without knowing why, and the visible symptom is a support ticket that says search finds nothing for one person. A mapping that is wrong and uncorrectable is a trap, so the correction surface is part of this change rather than an operational extra. ADR-M008 says the same.

| Endpoint | Rule |
| :--- | :--- |
| `GET /api/v1/admin/identity-links` | `ADMIN`. Cursor-paginated list, filterable by `status` and by normalized email. |
| `GET /api/v1/admin/identity-links/{id}` | `ADMIN`. One link, including the conflicting subject recorded at detection time. |
| `PATCH /api/v1/admin/identity-links/{id}` | `ADMIN`. Corrects a provider subject, or moves the status between `ACTIVE`, `SUSPECT`, and `DISABLED`. |

Errors are RFC 7807 `application/problem+json`, matching the rest of the API surface. A correction takes effect on that person's next principal resolution, which the D9 cache bounds at five minutes, so a successful write deletes their cached principal set rather than leaving the administrator to wait and wonder whether the fix worked.

These responses carry email addresses, which are personal data. They are `ADMIN` only, and this change ships no endpoint that lets a `USER` enumerate links or look one up by anybody else's address.

### D13 - The login issuer and the directory are configured separately

The original claim in this change was that any OIDC issuer works by repointing `issuer-uri`, with the role converter as the only provider-specific code. That was true while identity meant authentication. It stops being true the moment group membership has to be resolved, and it is exactly wrong for the split-provider customer the design document calls Shape 3: login through Microsoft Entra ID, files in Google Drive, so the groups that decide retrieval come from a directory that is not the token issuer.

Configuration separates the two axes:

- `spring.security.oauth2.resourceserver.jwt.issuer-uri` stays exactly what it is, the single issuer whose tokens are validated.
- `app.identity.claims` maps claim names for that issuer: which claim is the directory subject, which is the group claim, which is the email. Entra ID is `oid`, `groups`, `email`. Google is `sub`, none, `email`. Keycloak is `sub`, `groups`, `email`.
- `app.identity.directories` is a list of directory adapters, each with a provider kind (`microsoft-graph`, `google-directory`), the principal namespace its groups mint into, and its own credentials. An empty list is a valid configuration and it means the token claim is the only source of groups, which is Shape 2, the customer with no corporate directory at all.

What is configuration and what is code, stated plainly so the portability promise stays honest: validating a token, mapping claims onto identity fields, and mapping role claims onto authorities are configuration. Calling a directory is an adapter, one class per provider behind one interface, and a third vendor is new code. Two adapters ship here, Microsoft Graph and Google Directory, plus the no-directory case.

Shape 3 then falls out without a special case. The Entra token supplies `entra:group:*` principals, the identity link (D11) supplies the Google account id, the Google Directory adapter supplies `google:group:*` principals for that account, and both land in one set.

### D14 - A principal set is never silently narrowed

Three paths could produce a set smaller than the truth. None of them may do it quietly, and this decision exists because the cheap answer in each case is the silent one.

A directory call that fails, whether by Graph throttling, an expired client secret, or an outage, fails the request with 503 and a `Retry-After`. It does not fall back to `tenant:everyone`, and it does not serve a cached set past its time to live. Both of those produce a caller who is authenticated, receives 200, and cannot find documents they can open in SharePoint, which is the most expensive symptom in this entire design because it is indistinguishable from a retrieval bug. A 503 is a page for the operator. A narrowed set is somebody's week spent debugging embeddings.

The trade-off is real and it is stated rather than hidden: this makes directory availability into product availability on the cache-miss path. The five-minute cache absorbs a short outage for anyone recently active, and the design document already carries the open question of whether synchronous resolution is acceptable latency against a large directory. This decision does not close that question. It refuses to close it by degrading correctness.

A caller whose resolved set exceeds the cap fails the request, per D10, rather than searching on a truncated set.

The dev profile synthesises a deliberate, documented set rather than an empty one, per D5.

## Risks / Trade-offs

- [Shared static service token is a single secret with no rotation story] → Constant-time compare, env-injection only (never in YAML defaults or logs), fail-fast when unset in docker posture, documented rotation procedure, and D6's client-credentials upgrade path. Secret-manager sourcing belongs to `harden-cloud-deployment`.
- [Keycloak adds a boot-order dependency: agent fails JWKS fetch if issuer is down] → compose `depends_on` with healthcheck on Keycloak; resource-server JWKS fetch is lazy (first request) and cached, so brief IdP outages do not kill a running agent.
- [Bruno/e2e breakage — every existing request lacks credentials] → dedicated migration task; token acquisition scripted in the collection; seeded realm user makes it deterministic; dev profile keeps the manual escape hatch.
- [`sub` re-keys user data if the IdP is ever swapped] → accepted (D3); documented in `docs/SECURITY.md`.
- [MCP client header injection depends on Spring AI 1.1.5 connection config surface] → verified approach with fallback customizer bean (D6); an integration test pins the header actually leaving the agent.
- [Sibling changes racing on claim names] → this change is the declared owner of `sub`/`preferred_username`/`tenant` semantics; `add-tenant-isolation` consumes, never redefines.
- [Tokens over plain HTTP inside compose] → accepted at this layer; TLS is `harden-cloud-deployment` scope.
- [Directory availability becomes product availability on a cache miss] -> accepted deliberately in D14. The Redis cache absorbs short outages for active callers, and the alternative was silent under-retrieval that reads as a retrieval bug. Revisit if measurement against a large directory shows a high miss rate.
- [Email is a weak join key and this change does not make it strong] -> D11 makes the weakness observable instead of silent, and D12 is how it gets corrected. ADR-M008 records the full reasoning.
- [The principal-set cap of 256 is a number this change picked, not one the design fixed] -> chosen above both Entra ID token group-emission limits so nobody under them is affected, configurable, and any breach fails loudly with the cap named in the response body.
- [Entra ID `_claim_names` overflow read as an empty group set] -> the completeness test in D9 checks the overflow markers explicitly, and a slice test asserts that a token carrying `_claim_names` and no `groups` triggers the directory call rather than resolving to nothing.
- [Two sibling changes are blocked on this one] -> the principal format (D8) and the identity object shape (D3) are frozen by the tasks marked as blocking in `tasks.md`, and both land before either sibling starts.
- [The identity link table holds email addresses] -> personal data, so the administrator API is `ADMIN` only (D12), the value is stored normalized rather than raw, and `add-audit-and-gdpr-compliance` inherits the table in its erasure scope.

## Migration Plan

Identity lands before anything that reads it, because both sibling changes and the whole permission-aware retrieval design are waiting on the contract rather than on the plumbing.

1. Land the Keycloak compose service and realm export, including the group and email protocol mappers the claims contract now needs. Nothing consumes it yet, so this is additive and carries no risk.
2. Land the AscendAgent resource server, the resolved identity with both subjects (D3), and the principal identifier factory (D8). This is the step `add-tenant-isolation` and `add-document-connectors` are blocked on, and the contract freezes here.
3. Land membership resolution, the Redis principal cache, and the principal set with its cap (D9, D10, D14). Retrieval does not read the set yet, so correctness is observable through tests and through the principal-set-size metric before anything depends on it.
4. Land the identity link table, reused-address detection, and the administrator API (D11, D12).
5. Land downstream service auth in warn-only-when-unset mode (D6). With `SERVICE_AUTH_TOKEN` set in compose the services enforce; local bare runs keep working, and the agent does not have to be sending the token yet.
6. Land AscendAgent outbound token attachment. This has to ship before compose sets `SERVICE_AUTH_TOKEN` for every service, or the agent starts getting 401s from its own downstream calls.
7. Flip compose to the secured posture end to end, migrate the Bruno collection and the e2e suite to token acquisition, and verify the full authorization matrix.
8. Rollback: revert to the previous image tags and unset `SERVICE_AUTH_TOKEN` and the issuer environment variables. The dev profile is the operational escape hatch for a broken identity provider. The `identity_link` table is additive and is left in place on rollback, because dropping it would discard the reconciliation history an administrator needs on the way back in.

## Open Questions

- Redirect URIs for the Flutter client are finalized when the app exists. The realm export ships a placeholder loopback pattern (`http://localhost:*`) that the app change updates. Not blocking.
- The administrator assignment surface for direct uploads stays open, exactly as the design document leaves it. This change ships `local:group:*` as a principal namespace and the factory that mints it, but not the screen or API that assigns those groups to an uploaded document. Whether that lands in `add-tenant-administration` or `add-document-management-api` is a scoping decision outside these three changes. Not blocking here, because a customer with no corporate directory still gets `tenant:everyone:{tenantId}` and a correct, coarse system.
- Whether synchronous membership resolution is acceptable latency against a large directory. Carried over from the design document and still unmeasured, because nobody has a directory of the relevant size to measure against. D14 decides the part that can be decided now, which is that the failure is loud. The latency number stays open.
- Whether a customer with more than one login issuer needs more than one issuer configured at a time. D13 supports one issuer plus several directories, which covers all three deployment shapes the design document names. A customer merging two companies mid-migration would need more, and that is a change to make when somebody actually has it rather than a generalisation to build now.
