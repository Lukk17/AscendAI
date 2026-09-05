## ADDED Requirements

### Requirement: Identity brokering is optional and nothing depends on it

Identity brokering SHALL be optional configuration offered to a customer who wants their people to sign in with their existing corporate account. A deployment with no brokered identity provider configured SHALL be a complete and supported deployment: people sign in with a Keycloak account and a password, an administrator creates groups and assigns membership, and every requirement outside this capability SHALL hold unchanged.

No requirement, scenario, or behaviour on the password sign-in path SHALL depend on a brokered identity provider existing.

#### Scenario: A realm with no brokered provider is fully functional

- **WHEN** the realm contains no brokered identity provider and a person signs in with their Keycloak account and password
- **THEN** they reach AscendAgent with a valid token, a resolved identity, roles, and a principal set built from their Keycloak groups
- **AND** no behaviour of the product is degraded by the absence of a brokered provider

### Requirement: One brokered identity provider per customer, configured rather than coded

A customer who opts into corporate sign-on SHALL be represented in the `ascend-ai` realm by exactly one brokered identity provider, created as configuration through Keycloak's generic OpenID Connect provider pointed at the customer's own discovery document, or through its SAML provider where the customer offers only SAML. Onboarding a customer SHALL NOT require an AscendAgent code change or a release. AscendAgent SHALL never communicate with a customer's identity provider directly, and SHALL treat the brokered provider's alias as the customer's identifier inside the realm. There SHALL be no vendor-specific brokered provider type for Microsoft Entra ID: the generic OpenID Connect entry pointed at the customer's tenant discovery document is the supported mechanism, and the onboarding runbook SHALL name it.

#### Scenario: A customer is onboarded without a code change

- **WHEN** a customer's identity provider is brokered by creating a provider entry from the template in the realm export and configuring it per the runbook
- **THEN** people from that customer can sign in and reach AscendAgent with a valid token
- **AND** no AscendAgent source file changed and no release was cut

### Requirement: The brokered provider stamps the tenant

Each brokered identity provider SHALL carry a hardcoded-attribute mapper that stamps its customer's tenant value onto every user who arrives through it, and the realm SHALL carry a client protocol mapper that emits that attribute into the access token as the `tenant` claim. A realm user who arrived through no brokered provider SHALL carry the tenant `default`. The tenant value SHALL NOT be read from any claim the customer's identity provider controls.

#### Scenario: Tenant follows the brokered provider

- **WHEN** a person signs in through the brokered provider configured for tenant `acme`
- **THEN** their access token carries the claim `tenant` with value `acme`
- **AND** the resolved identity reports tenant `acme`

#### Scenario: A customer cannot choose their own tenant

- **WHEN** the upstream token from a customer's identity provider carries a claim named `tenant` with a value naming a different customer
- **THEN** the tenant on the issued access token is the one stamped by the brokered provider
- **AND** the upstream value has no effect

### Requirement: Brokering decides authentication only, never authorization

A person who signs in through a brokered identity provider SHALL be a realm user like any other for every authorization purpose. Their group principals SHALL come from the Keycloak realm groups an administrator assigned to them, and their roles SHALL be realm roles assigned on the platform's side. No brokered identity provider SHALL carry a mapper that imports a group claim, a role claim, or any other attribute the resolved identity derives authorization from. A customer's identity provider SHALL NOT be able to widen what a person may read or which endpoints they may call.

#### Scenario: A brokered person's principals come from Keycloak groups

- **WHEN** a person signs in through a brokered provider and an administrator has placed them in the realm group `policy-readers`
- **THEN** their resolved principal set contains `local:group:policy-readers` and the tenant pseudo-group
- **AND** it contains no principal derived from any claim the upstream token carried

#### Scenario: An upstream group cannot mint a platform role

- **WHEN** the upstream token carries a group or role named `ADMIN`
- **THEN** the issued access token grants no `ADMIN` realm role
- **AND** the caller receives 403 on an endpoint requiring `ADMIN`

#### Scenario: No importing mapper exists in the shipped configuration

- **WHEN** the realm export and the brokered-provider template are inspected
- **THEN** no identity-provider mapper imports a group claim or any other attribute the resolved identity derives authorization from

### Requirement: A person is matched to their customer's provider deterministically

Where brokered providers exist, the realm SHALL match a person to their customer's provider either by a provider hint the client application passes on the authorization request, or by mapping the email domain the person enters at the login page to the provider registered for that domain. A person whose domain matches no registered provider SHALL NOT be routed to a default or fallback provider, and SHALL be able to sign in with a local account and password instead.

#### Scenario: A client-supplied hint routes deterministically

- **WHEN** the application starts an authorization request carrying the alias of a customer's brokered provider
- **THEN** the person is taken to that customer's identity provider without being asked to choose

#### Scenario: An unmatched domain is not defaulted to a provider

- **WHEN** a person enters an email address whose domain is registered to no brokered provider
- **THEN** they are not signed in through any brokered provider
- **AND** no realm user is created carrying a tenant they do not belong to

### Requirement: Provider tokens are not stored

No brokered identity provider SHALL be configured to store the token it received from the customer's identity provider, and AscendAgent SHALL NOT retrieve upstream provider tokens through the broker. Enabling storage SHALL be understood as a deliberate per-provider exception with a named cost: third-party credentials held in our database, inside the erasure and breach scope of `add-audit-and-gdpr-compliance`.

#### Scenario: Stored tokens are off in the shipped configuration

- **WHEN** the realm export and the brokered-provider template are inspected
- **THEN** no provider has token storage enabled

### Requirement: An onboarding is complete only when a verification sign-in resolves the expected tenant

Onboarding a customer onto brokering SHALL be closed by a verification sign-in from a real person at that customer, asserting that the resolved identity carries the expected tenant. The runbook SHALL state that group membership is assigned separately in Keycloak and is not part of the brokering configuration.

#### Scenario: A passing verification records the tenant

- **WHEN** the verification sign-in resolves the tenant configured for that brokered provider
- **THEN** the onboarding is recorded as complete

#### Scenario: A sign-in resolving the default tenant fails the onboarding

- **WHEN** the verification sign-in succeeds but the resolved identity reports tenant `default`
- **THEN** the onboarding is recorded as failed
- **AND** the runbook directs the operator to the hardcoded-attribute mapper on the brokered provider as the cause
