## ADDED Requirements

### Requirement: User identity is derived from validated token claims

ascend-ai-agent SHALL resolve the identity of a request that carries a user token exclusively from the validated JWT, and the only other sources SHALL be the dev identity and the resolution without a token of the requirement below. The user identifier used for chat history, semantic memory and RAG scoping SHALL be the `sub` claim. `preferred_username` SHALL be carried for logging and display only and SHALL NOT be used as a storage key. The resolved identity SHALL be exposed to controllers and services as a single immutable value object carrying `userId`, `username`, `email`, `tenant`, `roles` and `extensions`, so there is exactly one identity code path in secured and dev postures.

#### Scenario: Storage keys use the token subject

- **WHEN** a prompt request arrives with a valid JWT whose `sub` is `f81d4fae-7dec-11d0-a765-00a0c91e6bf6`
- **THEN** the chat history entry, memory operations and log lines attribute the request to `f81d4fae-7dec-11d0-a765-00a0c91e6bf6`
- **AND** the value of `preferred_username` appears at most in logs, never as a Redis, Postgres or Qdrant key

### Requirement: One tenant through a replaceable tenant resolver

The tenant of every resolved identity SHALL come from a `TenantResolver` port, given either the validated token or the Keycloak user representation of a resolution without a token. The default implementation SHALL answer `default` for both and SHALL exist only while no other implementation is registered. This change SHALL NOT read a `tenant` claim. `TenantContext` SHALL be the one tenant seam every later change reads, and no later personal change SHALL name `TenantResolver`. `TenantContext.currentTenantId()` SHALL return the tenant bound to the current thread, which inside a request is the tenant of the resolved identity of that request, and SHALL throw when nothing is bound. `TenantContext.runAs(tenantId, action)` SHALL bind the given tenant on the calling thread for the duration of `action`, SHALL restore the previous binding afterwards also when `action` fails, and SHALL refuse a blank tenant id, so a background worker that acts for a stored row binds the tenant stored on that row.

#### Scenario: Every identity is in tenant default

- **WHEN** a valid JWT carries a claim `tenant` with the value `acme` and no other `TenantResolver` is registered
- **THEN** the resolved identity reports tenant `default`

#### Scenario: A background worker binds the tenant of its row

- **WHEN** a worker thread with nothing bound calls `TenantContext.runAs("default", action)` and `action` reads `TenantContext.currentTenantId()`
- **THEN** `action` reads `default`
- **AND** after `runAs` returns, `TenantContext.currentTenantId()` on that thread throws again, also when `action` failed

#### Scenario: Nothing bound fails closed

- **WHEN** code on a thread with no request identity and no `runAs` binding calls `TenantContext.currentTenantId()`
- **THEN** the call throws and no tenant is answered

#### Scenario: A registered resolver replaces the default

- **WHEN** a deployment registers its own `TenantResolver` bean
- **THEN** every token identity, dev identity and identity resolved without a token carries the tenant that resolver answers
- **AND** no class of this change was edited to make that happen

### Requirement: The resolved identity can be extended without editing it

ascend-ai-agent SHALL offer an `IdentityContributor` port. Every registered contributor SHALL be given the same input as the `TenantResolver` and SHALL add typed values to the immutable `extensions` of the resolved identity, on all three paths that build an identity. This change SHALL register no contributor, so `extensions` SHALL be empty in a deployment without company work. A contributor that fails SHALL fail the request or the resolution, and SHALL NOT leave a partly built identity. No personal feature SHALL read an extension value.

#### Scenario: No contributor means empty extensions

- **WHEN** a request is resolved in a deployment that registers no `IdentityContributor`
- **THEN** the resolved identity's `extensions` is empty

#### Scenario: A contributor adds a value on every path

- **WHEN** a test contributor that adds a value is registered and an identity is resolved from a token, from the dev profile and without a token
- **THEN** all three identities carry that value in `extensions`

### Requirement: An identity can be resolved without a token for a linked chat account or a scheduled firing

ascend-ai-agent SHALL provide one resolver that builds the identity of a known user without a token, used for a request on the channel host path of `add-openclaw-plugin-host` that names a chat platform account linked to a user, and for a firing of `add-scheduled-tasks`. It SHALL read the user's enabled flag and realm roles through Keycloak's admin API with the confidential client `ascend-agent-directory`, SHALL take the tenant from the `TenantResolver` and the extensions from the `IdentityContributor` beans, and SHALL produce the same immutable identity value object. A resolved identity SHALL be cached per user for at most the realm access token lifetime, in a cache bounded in size (a setting, 10000 entries by default, owner answer 98.4 of 2026-10-08). Because several agent instances run at once, a fresh lookup that finds a user's enabled flag or roles changed, or finds the user disabled or unknown, SHALL evict that user's cached identity on every instance through a Postgres notification, and any agent code that changes a user's roles or enabled flag SHALL be able to send the same eviction (owner answer 87 of 2026-10-08). The resolution SHALL fail closed when Keycloak cannot be reached or the user is disabled or unknown, and SHALL never return an older identity instead. Under the `dev` profile it SHALL resolve to the dev identity.

#### Scenario: A link and a token resolve the same identity

- **WHEN** a user's identity is resolved once from their access token and once without a token for the same user
- **THEN** both identities carry the same `userId`, tenant and roles

#### Scenario: A disabled user is refused

- **WHEN** the identity of a user whose Keycloak account is disabled is resolved without a token
- **THEN** the resolution fails and no identity is returned
- **AND** the caller refuses the message or the firing

#### Scenario: A refusal on one instance reaches every instance

- **WHEN** two agent instances have cached an identity of a user, the user is disabled in Keycloak, and a fresh lookup on the first instance finds the user disabled
- **THEN** the second instance drops its cached identity of that user
- **AND** its next resolution of that user fails closed

#### Scenario: Keycloak down is refused

- **WHEN** Keycloak cannot be reached during a resolution without a token and nothing valid is cached for that user
- **THEN** the resolution fails and no identity is returned

### Requirement: The administrators of a tenant can be looked up without a token

ascend-ai-agent SHALL provide an offline lookup, with no token, of the enabled users holding the `ADMIN` role in a given tenant, through the same `ascend-agent-directory` client and filtered through the `TenantResolver`, so a report of `add-self-improvement` can be addressed to each of them.

#### Scenario: Only enabled administrators are returned

- **WHEN** the realm has two enabled `ADMIN` users, one disabled `ADMIN` user and one `USER`, and the lookup runs for tenant `default`
- **THEN** it returns exactly the two enabled `ADMIN` users

### Requirement: X-User-Id header is no longer trusted

ascend-ai-agent SHALL ignore the `X-User-Id` request header on all endpoints in the secured posture. A request carrying `X-User-Id` SHALL be processed under the token-derived identity, and the header value SHALL have no effect on which user's data is read or written. The `PromptController` fallback to `app.user.default-id` SHALL apply only in the `dev` profile.

#### Scenario: Spoofed header cannot switch identity

- **WHEN** a request authenticated as subject `alice-sub` includes header `X-User-Id: bob`
- **THEN** the request is processed as `alice-sub`
- **AND** no chat history or memory belonging to `bob` is read or written

#### Scenario: Header alone grants nothing

- **WHEN** an unauthenticated request includes `X-User-Id: user1` in the secured posture
- **THEN** the response status is 401
