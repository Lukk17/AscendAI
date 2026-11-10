## ADDED Requirements

### Requirement: The tenant is read from the tenant claim in a company deployment

This change SHALL register a `TenantResolver` that replaces the default resolver of `add-keycloak-login`. It SHALL read the `tenant` claim of a validated token and the `tenant` attribute of the Keycloak user representation of a resolution without a token, and SHALL answer `default` when the claim or the attribute is absent. This change SHALL NOT enforce any tenant-based filtering. The claim exists so `add-tenant-isolation` can consume it without a token-format migration. The claim name and default value SHALL be treated as a stable contract. No class of `add-keycloak-login` SHALL be edited to read the claim.

#### Scenario: Tenant claim surfaces on the identity object

- **WHEN** a valid JWT carries claim `tenant: acme`
- **THEN** the resolved identity object reports tenant `acme`
- **AND** request processing is otherwise identical to a token without the claim

#### Scenario: Missing tenant claim defaults

- **WHEN** a valid JWT carries no `tenant` claim
- **THEN** the resolved identity object reports tenant `default`

#### Scenario: A linked user carries the tenant of their attribute

- **WHEN** a user whose `tenant` attribute is `acme` is resolved without a token
- **THEN** the resolved identity reports tenant `acme`

### Requirement: The resolved identity carries a principal set as an extension

This change SHALL register an `IdentityContributor` that adds `PrincipalSet`, the set of `namespace:type:id` values produced from the caller's group names, to the extensions of the resolved identity of `add-keycloak-login`, on the token path, the dev path and the path without a token. It SHALL NOT store the raw group names next to the set. The set SHALL be populated during authentication and SHALL be immutable for the life of the request. `PrincipalContext.currentPrincipals()` SHALL return an empty `Optional` when no principal set was resolved and a present set otherwise, and SHALL throw outside a request with a resolved identity.

#### Scenario: Principals surface on the identity

- **WHEN** a caller in tenant `acme` authenticates with a token whose group claim lists `policy-readers` and `finance`
- **THEN** the resolved identity's `PrincipalSet` contains `local:group:policy-readers`, `local:group:finance` and `tenant:everyone:acme`

#### Scenario: Without this change there is no principal set

- **WHEN** an identity is resolved in a deployment that runs `add-keycloak-login` without this change
- **THEN** `extensions` holds no `PrincipalSet`
- **AND** every personal feature behaves as before

### Requirement: Roles do not widen retrieval

Roles SHALL affect endpoint authorization only. A role SHALL NEVER appear in a retrieval filter, SHALL NEVER be converted into a principal, and SHALL NEVER widen the set of chunks a caller can retrieve.

#### Scenario: An administrator retrieves no more than their groups allow

- **WHEN** a chunk carries an access list naming a group the caller does not belong to, and the caller holds the `ADMIN` role
- **THEN** that chunk is not retrieved
- **AND** the caller's answer is grounded only in chunks their principal set matches
