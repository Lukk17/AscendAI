## ADDED Requirements

### Requirement: User identity is derived from validated token claims

AscendAgent SHALL resolve the request identity exclusively from the validated JWT: the user identifier used for chat history, semantic memory, and RAG scoping SHALL be the `sub` claim; `preferred_username` SHALL be carried for logging and display only and SHALL NOT be used as a storage key. The resolved identity SHALL be exposed to controllers and services as a single immutable value object carrying `userId`, `directorySubject`, `username`, `email`, `tenant`, `roles`, `groupIds`, and `principals`, so there is exactly one identity code path in secured and dev postures.

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

### Requirement: The resolved identity carries a directory subject distinct from the storage subject

The resolved identity SHALL carry a `directorySubject` field, populated from a per-provider claim configured for the issuer, alongside the `userId` field populated from `sub`. `directorySubject` SHALL be the only value used for directory membership calls and for comparison against a provider's permission entries. `userId` SHALL be the only value used to partition stored data. Neither SHALL be used in the other's place. For Microsoft Entra ID the configured directory-subject claim SHALL be `oid`, because Entra issues a pairwise `sub` that is unique per application and unknown to Microsoft Graph. For Google the configured directory-subject claim SHALL be `sub`.

#### Scenario: Both subjects are resolved from their own claims

- **WHEN** a valid Entra ID token carries `sub` of `pairwise-abc` and `oid` of `8f4a1b2c-3d5e-4f60-9a1b-2c3d4e5f6071`
- **THEN** the resolved identity reports `userId` of `pairwise-abc` and `directorySubject` of `8f4a1b2c-3d5e-4f60-9a1b-2c3d4e5f6071`
- **AND** chat history and semantic memory are partitioned under `pairwise-abc`
- **AND** the value sent to Microsoft Graph is `8f4a1b2c-3d5e-4f60-9a1b-2c3d4e5f6071`

#### Scenario: A missing directory-subject claim is an authentication failure, not a silent fallback

- **WHEN** a token arrives with no claim under the configured directory-subject claim name and the deployment has at least one directory adapter configured
- **THEN** the request is rejected
- **AND** `sub` is not substituted for the missing directory subject

### Requirement: The resolved identity carries group identifiers and a principal set

The resolved identity SHALL carry `groupIds`, the raw group identifiers resolved for the caller, and `principals`, the set of `namespace:type:id` values produced from them. Both SHALL be populated during authentication and SHALL be immutable for the life of the request. The `email` field SHALL carry the normalized email address used as the identity-link join key.

#### Scenario: Group identifiers and principals both surface on the identity

- **WHEN** a caller in tenant `acme` authenticates with two resolved Entra ID groups
- **THEN** the resolved identity's `groupIds` lists both raw group object ids
- **AND** its `principals` contains the corresponding `entra:group:*` values plus `tenant:everyone:acme`

### Requirement: Roles do not widen retrieval

Roles SHALL affect endpoint authorization only. A role SHALL NEVER appear in a retrieval filter, SHALL NEVER be converted into a principal, and SHALL NEVER widen the set of chunks a caller can retrieve.

#### Scenario: An administrator retrieves no more than their groups allow

- **WHEN** a chunk carries an access list naming a group the caller does not belong to, and the caller holds the `ADMIN` role
- **THEN** that chunk is not retrieved
- **AND** the caller's answer is grounded only in chunks their principal set matches

### Requirement: Tenant claim is defined and propagated but not enforced

The resolved identity SHALL include a `tenant` field read from the token's custom `tenant` claim, defaulting to `default` when the claim is absent. This change SHALL NOT enforce any tenant-based filtering; the claim exists so the sibling `add-tenant-isolation` change can consume it without a token-format migration. The claim name and default value SHALL be treated as a stable contract.

#### Scenario: Tenant claim surfaces on the identity object

- **WHEN** a valid JWT carries claim `tenant: acme`
- **THEN** the resolved identity object reports tenant `acme`
- **AND** request processing is otherwise identical to a token without the claim

#### Scenario: Missing tenant claim defaults

- **WHEN** a valid JWT carries no `tenant` claim
- **THEN** the resolved identity object reports tenant `default`
