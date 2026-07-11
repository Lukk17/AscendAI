## ADDED Requirements

### Requirement: User identity is derived from validated token claims

AscendAgent SHALL resolve the request identity exclusively from the validated JWT: the user identifier used for chat history, semantic memory, and RAG scoping SHALL be the `sub` claim; `preferred_username` SHALL be carried for logging and display only and SHALL NOT be used as a storage key. The resolved identity SHALL be exposed to controllers and services as a single value object (userId, username, tenant, roles) so there is exactly one identity code path in secured and dev postures.

#### Scenario: Storage keys use the token subject

- **WHEN** a prompt request arrives with a valid JWT whose `sub` is `f81d4fae-7dec-11d0-a765-00a0c91e6bf6`
- **THEN** the chat history entry, memory operations, and log lines attribute the request to `f81d4fae-7dec-11d0-a765-00a0c91e6bf6`
- **AND** the value of `preferred_username` appears at most in logs, never as a Redis/Postgres/Qdrant key

### Requirement: X-User-Id header is no longer trusted

AscendAgent SHALL ignore the `X-User-Id` request header on all endpoints in the secured posture. A request carrying `X-User-Id` SHALL be processed under the token-derived identity, and the header value SHALL have no effect on which user's data is read or written. The `PromptController` fallback to `app.user.default-id` SHALL apply only in the `dev` profile.

#### Scenario: Spoofed header cannot switch identity

- **WHEN** a request authenticated as subject `alice-sub` includes header `X-User-Id: bob`
- **THEN** the request is processed as `alice-sub`
- **AND** no chat history or memory belonging to `bob` is read or written

#### Scenario: Header alone grants nothing

- **WHEN** an unauthenticated request includes `X-User-Id: user1` in the secured posture
- **THEN** the response status is 401

### Requirement: Tenant claim is defined and propagated but not enforced

The resolved identity SHALL include a `tenant` field read from the token's custom `tenant` claim, defaulting to `default` when the claim is absent. This change SHALL NOT enforce any tenant-based filtering; the claim exists so the sibling `add-tenant-isolation` change can consume it without a token-format migration. The claim name and default value SHALL be treated as a stable contract.

#### Scenario: Tenant claim surfaces on the identity object

- **WHEN** a valid JWT carries claim `tenant: acme`
- **THEN** the resolved identity object reports tenant `acme`
- **AND** request processing is otherwise identical to a token without the claim

#### Scenario: Missing tenant claim defaults

- **WHEN** a valid JWT carries no `tenant` claim
- **THEN** the resolved identity object reports tenant `default`
