## ADDED Requirements

### Requirement: Principals use one namespaced format produced by a typed factory

Every principal SHALL be a string of the form `namespace:type:id`, at most 128 characters long, restricted to lowercase letters, digits, and the characters `.`, `-`, `_`, `@`. In this version the namespace SHALL come from the closed set `local`, `tenant`, and the type SHALL come from the closed set `group`, `everyone`. Principals SHALL be produced only by a single typed factory that validates length, character set, namespace, and type; the factory SHALL reject an invalid value by throwing rather than by returning a truncated or best-effort one. Filter expressions carrying principals SHALL be built through Spring AI's `FilterExpressionBuilder` and never by string concatenation.

Every group in this version is a Keycloak realm group and SHALL mint into `local:group:<group name>`. The namespace set SHALL be closed, so that adding a namespace for directory-sourced groups later is a deliberate change rather than an accident of string handling.

#### Scenario: Well-formed principals are produced for each namespace

- **WHEN** the factory is asked for a local group with slug `policy-readers` and for the tenant pseudo-group for tenant `acme`
- **THEN** the produced values are exactly `local:group:policy-readers` and `tenant:everyone:acme`

#### Scenario: An unrecognised namespace fails rather than being stored

- **WHEN** the factory is asked to produce a principal in a namespace outside the closed set, or with a value containing an uppercase letter, a space, or any character outside the permitted set, or longer than 128 characters
- **THEN** the call fails with an error naming the offending constraint
- **AND** no principal value is produced and nothing is written to the vector store or to the principal set

#### Scenario: A realm group mints into the local namespace

- **WHEN** a Keycloak token carries the group `policy-readers`
- **THEN** the resolved principal is `local:group:policy-readers`

### Requirement: Group membership is resolved from the Keycloak group claim

ascend-ai-agent SHALL resolve the caller's group identifiers from the configured group claim on the validated token, and from no other source. It SHALL NOT call any external directory, and SHALL NOT read group membership from any store of its own. Each group name in the claim SHALL be minted into one principal through the typed factory. A token carrying no group claim, or an empty one, SHALL resolve to no group principals, which SHALL be understood as a true statement that an administrator has placed the caller in no groups.

#### Scenario: Group names in the claim become principals

- **WHEN** a valid token carries a group claim listing `policy-readers` and `dev-all`
- **THEN** the resolved principal set contains `local:group:policy-readers` and `local:group:dev-all`
- **AND** no call is made to any external directory

#### Scenario: No group claim means no group principals

- **WHEN** a valid token carries no group claim
- **THEN** the resolved principal set is exactly `tenant:everyone:{tenantId}`
- **AND** the request is processed normally

#### Scenario: A group name that cannot be minted fails loudly

- **WHEN** a token carries a group name containing a character outside the permitted principal character set
- **THEN** the factory throws and the request fails with an error naming the constraint
- **AND** no partially-populated principal set reaches any filter

### Requirement: A directory group identifier matches no principal in this version

ascend-ai-agent SHALL NOT mint or match a principal naming a group in an external directory. An access list naming a group identifier from Microsoft Entra ID, Google Workspace, or any other external directory SHALL therefore match no caller, for every caller. Documents synced from a customer's own storage SHALL be made visible tenant-wide rather than left matching nobody, and this limitation SHALL be recorded as a product fact in `docs/SECURITY.md` rather than presented as a defect.

#### Scenario: An access list naming a directory group matches nobody

- **WHEN** a chunk carries an access list naming a Microsoft Entra ID security group by its directory object id, and any caller resolves a principal set
- **THEN** that principal is absent from every resolved principal set
- **AND** the chunk is retrieved by nobody on the strength of that entry

#### Scenario: A synced document is reachable through the tenant pseudo-group

- **WHEN** a document is synced from a customer's own storage and carries `tenant:everyone:{tenantId}` in its access list
- **THEN** every caller in that tenant retrieves it
- **AND** the coarser visibility is the documented behaviour for this version

### Requirement: Membership is only as fresh as the token that carries it

A change to a caller's group membership SHALL become visible to ascend-ai-agent when that caller next obtains an access token, bounded by the realm's access token lifetime and, for continued use without signing in again, by the realm's SSO session lifetime. Both lifetimes SHALL be set explicitly in the realm export and documented in `docs/SECURITY.md` as a product disclosure. ascend-ai-agent SHALL NOT introduce a second staleness window of its own by caching a resolved principal set.

#### Scenario: A group removal takes effect at the next token

- **WHEN** an administrator removes a caller from a realm group while that caller holds an unexpired access token
- **THEN** the principal is still present for requests made with that token
- **AND** it is absent from the principal set resolved for the next token they obtain

#### Scenario: No resolved set is cached across requests

- **WHEN** two requests carrying two different tokens for the same person arrive, and the caller's group membership changed between them
- **THEN** each request resolves its principal set from the token it carries
- **AND** the earlier result is not reused

### Requirement: The principal set is assembled once per request and is immutable

ascend-ai-agent SHALL assemble the caller's principal set during authentication, before any controller method executes, and SHALL attach it to the resolved identity. The set SHALL be immutable for the life of the request: no component SHALL add to it, remove from it, or replace it after resolution. The set SHALL contain `tenant:everyone:{tenantId}` for the caller's tenant and one principal per group the caller holds. Roles SHALL contribute no principals.

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

### Requirement: The dev profile synthesises a usable principal set

When the Spring profile `dev` is active, the synthesized identity SHALL carry a principal set containing `tenant:everyone:default` and `local:group:dev-all`, so that a locally-ingested corpus carrying either principal is retrievable without an identity provider. The dev profile SHALL NOT synthesize an empty principal set.

#### Scenario: A developer retrieves seeded documents

- **WHEN** the agent runs under profile `dev` and a chunk is stored carrying `local:group:dev-all` in its access list
- **THEN** a tokenless prompt request retrieves that chunk

#### Scenario: Deny by default still holds under the dev profile

- **WHEN** the agent runs under profile `dev` and a chunk is stored with no access list
- **THEN** that chunk is not retrieved
