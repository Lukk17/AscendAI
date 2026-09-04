## ADDED Requirements

### Requirement: Principals use one namespaced format produced by a typed factory

Every principal SHALL be a string of the form `namespace:type:id`, at most 128 characters long, restricted to lowercase letters, digits, and the characters `.`, `-`, `_`, `@`. The namespace SHALL come from the closed set `entra`, `google`, `local`, `tenant`, and the type SHALL come from the closed set `group`, `everyone`. Principals SHALL be produced only by a single typed factory that validates length, character set, namespace, and type; the factory SHALL reject an invalid value by throwing rather than by returning a truncated or best-effort one. Filter expressions carrying principals SHALL be built through Spring AI's `FilterExpressionBuilder` and never by string concatenation. Groups originating from Keycloak SHALL mint into the `local` namespace, because Keycloak is the application's own identity provider and not a corporate directory.

#### Scenario: Well-formed principals are produced for each namespace

- **WHEN** the factory is asked for an Entra ID group with object id `8f4a1b2c-3d5e-4f60-9a1b-2c3d4e5f6071`, a Google group with address `engineering@acme.example`, a local group with slug `policy-readers`, and the tenant pseudo-group for tenant `acme`
- **THEN** the produced values are exactly `entra:group:8f4a1b2c-3d5e-4f60-9a1b-2c3d4e5f6071`, `google:group:engineering@acme.example`, `local:group:policy-readers`, and `tenant:everyone:acme`

#### Scenario: An unrecognised namespace fails rather than being stored

- **WHEN** the factory is asked to produce a principal in a namespace outside the closed set, or with a value containing an uppercase letter, a space, or any character outside the permitted set, or longer than 128 characters
- **THEN** the call fails with an error naming the offending constraint
- **AND** no principal value is produced and nothing is written to the vector store or to the principal set

#### Scenario: Keycloak groups mint into the local namespace

- **WHEN** a token issued by the local Keycloak realm carries group `policy-readers`
- **THEN** the resolved principal is `local:group:policy-readers`

### Requirement: Group membership resolves from a complete token claim, otherwise from the provider's transitive endpoint

AscendAgent SHALL resolve the caller's group identifiers per token in this order: read the configured group claim and use it only when it is complete; otherwise call the configured directory provider's transitive membership endpoint against the caller's directory subject. A group claim SHALL be treated as complete only when the claim is present AND neither `_claim_names` nor `_claim_sources` appears on the token. An absent group claim SHALL mean fall through to the directory call and SHALL NEVER be treated as an empty group set. Nested groups SHALL be flattened by the provider's transitive endpoint and SHALL NOT be walked by AscendAgent.

#### Scenario: A complete group claim avoids the directory call

- **WHEN** a valid token carries a `groups` claim listing two group identifiers and carries neither `_claim_names` nor `_claim_sources`
- **THEN** the resolved principal set contains a principal for each of those two groups
- **AND** no call is made to the directory provider

#### Scenario: An overflow-marked token falls through to the directory

- **WHEN** a valid token carries no `groups` claim and does carry `_claim_names` and `_claim_sources`
- **THEN** the directory provider's transitive membership endpoint is called with the caller's directory subject
- **AND** the resolved principal set contains a principal for every group that endpoint returned

#### Scenario: Directory lookups use the directory subject, never the token subject

- **WHEN** membership is resolved for a token whose `sub` and `oid` claims differ
- **THEN** the value sent to the directory provider is the `oid` value
- **AND** the `sub` value is not sent to the directory provider

### Requirement: Resolved principal sets are cached in Redis under issuer and subject

AscendAgent SHALL cache the resolved principal set in Redis under a key incorporating both a stable hash of the token issuer and the token subject, with a time to live equal to the shorter of the remaining token lifetime and five minutes. A cache hit SHALL skip both the directory call and principal construction. Redis being unavailable SHALL degrade latency only: the request SHALL proceed by resolving membership directly, and the resulting principal set SHALL be identical to the one a cache hit would have produced.

#### Scenario: A second request inside the time to live makes no directory call

- **WHEN** two requests carrying the same token arrive within the cache time to live and the first one resolved membership through the directory
- **THEN** the second request makes no directory call
- **AND** both requests resolve the same principal set

#### Scenario: Tokens from different issuers do not share a cache entry

- **WHEN** two tokens carrying the same `sub` value but issued by two different issuers are presented
- **THEN** each resolves its own principal set
- **AND** neither reads the other's cached entry

#### Scenario: A short-lived token expires the cache entry with it

- **WHEN** a token with two minutes of remaining lifetime is presented
- **THEN** the cache entry for that principal set expires no later than two minutes after it was written

### Requirement: The principal set is assembled once per request and is immutable

AscendAgent SHALL assemble the caller's principal set during authentication, before any controller method executes, and SHALL attach it to the resolved identity. The set SHALL be immutable for the life of the request: no component SHALL add to it, remove from it, or replace it after resolution. The set SHALL contain `tenant:everyone:{tenantId}` for the caller's tenant, one principal per resolved group, and any application-local group assignments. Roles SHALL contribute no principals.

#### Scenario: The set cannot be modified after resolution

- **WHEN** any component attempts to add a principal to, or remove a principal from, the resolved identity's principal set during request processing
- **THEN** the attempt fails
- **AND** the set observed later in the same request is identical to the set observed at authentication time

#### Scenario: The tenant pseudo-group is always present

- **WHEN** a caller in tenant `acme` resolves a principal set, whether or not any group was resolved
- **THEN** the set contains `tenant:everyone:acme`

#### Scenario: An administrative role adds no principals

- **WHEN** two callers in the same tenant with identical group membership resolve principal sets, and one holds only `USER` while the other holds `ADMIN`
- **THEN** both principal sets are equal

### Requirement: The principal set is capped and never truncated

The resolved principal set SHALL be subject to a configurable cap defaulting to 256 principals. A caller whose resolved set exceeds the cap SHALL receive HTTP 403 with an `application/problem+json` body naming the cap and the resolved size, and no vector search SHALL be executed for that request. The set SHALL NEVER be truncated to fit the cap.

#### Scenario: An over-cap caller is refused rather than trimmed

- **WHEN** membership resolution yields more principals than the configured cap
- **THEN** the response status is 403 with an `application/problem+json` body stating the cap and the resolved size
- **AND** no vector search is executed and no partially-populated principal set reaches any filter

### Requirement: A failed directory resolution fails the request

When group membership cannot be resolved because the directory provider is unreachable, throttling, or rejecting the agent's credentials, AscendAgent SHALL reject the request with HTTP 503 and a `Retry-After` header. It SHALL NOT fall back to a principal set containing only `tenant:everyone:{tenantId}`, and it SHALL NOT serve a cached principal set past its time to live.

#### Scenario: A directory outage is a visible failure, not a quiet narrowing

- **WHEN** the directory provider returns an error or times out during membership resolution on a cache miss
- **THEN** the response status is 503 with a `Retry-After` header
- **AND** no vector search is executed
- **AND** the response is not a 200 carrying an answer produced from a reduced principal set

### Requirement: The dev profile synthesises a usable principal set

When the Spring profile `dev` is active, the synthesized identity SHALL carry a principal set containing `tenant:everyone:default` and `local:group:dev-all`, so that a locally-ingested corpus carrying either principal is retrievable without an identity provider. The dev profile SHALL NOT synthesize an empty principal set.

#### Scenario: A developer retrieves seeded documents

- **WHEN** the agent runs under profile `dev` and a chunk is stored carrying `local:group:dev-all` in its access list
- **THEN** a tokenless prompt request retrieves that chunk

#### Scenario: Deny by default still holds under the dev profile

- **WHEN** the agent runs under profile `dev` and a chunk is stored with no access list
- **THEN** that chunk is not retrieved
