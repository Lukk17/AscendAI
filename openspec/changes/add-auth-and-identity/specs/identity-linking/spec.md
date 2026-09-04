## ADDED Requirements

### Requirement: An identity link joins two provider identities and keeps both stable identifiers

AscendAgent SHALL maintain a durable `identity_link` record per person per tenant, created by a Liquibase changelog against the existing PostgreSQL database. The record SHALL hold the normalized email address, the login issuer, the login provider's directory subject, the file provider's directory subject where one is known, a status, the creation and last-confirmation timestamps, and the conflicting subject recorded when a conflict is detected. The email address SHALL be the join key and each provider's own stable identifier SHALL be stored alongside it rather than instead of it. The record SHALL be queryable by normalized email and by either provider subject.

#### Scenario: First login creates the link

- **WHEN** a caller authenticates and no identity link exists for their normalized email in their tenant
- **THEN** a link is created recording the normalized email, the login issuer, and the login provider's directory subject
- **AND** its status is `ACTIVE`

#### Scenario: Repeat login confirms the link

- **WHEN** a caller authenticates and a link exists whose stored provider subjects all match the ones presented
- **THEN** the link's last-confirmation timestamp is updated
- **AND** its status remains `ACTIVE`

#### Scenario: The link survives a Redis flush

- **WHEN** Redis is flushed and the same caller authenticates again
- **THEN** the existing link is found and confirmed rather than recreated

### Requirement: Email normalization is one deterministic function applied everywhere

AscendAgent SHALL normalize email addresses through a single function applied identically at login and at any later reconciliation: trim surrounding whitespace, apply Unicode NFKC, lowercase, IDNA-encode the domain, and strip a `+tag` suffix from the local part. The function SHALL NOT remove dots from the local part, because dot-insensitivity is a single provider's behaviour and applying it generally would merge two distinct corporate addresses into one person.

#### Scenario: Equivalent forms normalize to one value

- **WHEN** the addresses `  Alice.Smith+reports@ACME.example `, `alice.smith@acme.example`, and `ALICE.SMITH+ci@acme.example` are normalized
- **THEN** all three produce `alice.smith@acme.example`

#### Scenario: Dots are significant

- **WHEN** the addresses `alice.smith@acme.example` and `alicesmith@acme.example` are normalized
- **THEN** the two results differ
- **AND** the two addresses resolve to two separate identity links

### Requirement: A conflicting provider subject marks the link SUSPECT

When a caller presents a normalized email that matches an existing link but a provider subject that differs from the one stored for that provider, AscendAgent SHALL move the link to status `SUSPECT`, record both the stored subject and the presented one, and SHALL NOT overwrite the stored subject automatically. The link SHALL remain `SUSPECT` until an administrator corrects it.

#### Scenario: A reissued address is detected rather than inherited

- **WHEN** a caller presents a token whose normalized email matches an existing `ACTIVE` link but whose directory subject differs from the one on file
- **THEN** the link status becomes `SUSPECT`
- **AND** both the stored subject and the presented subject are recorded on the link
- **AND** the request still authenticates successfully

### Requirement: A SUSPECT or DISABLED link contributes no group principals

A link in status `SUSPECT` or `DISABLED` SHALL contribute no group principals from any provider. The caller's resolved principal set SHALL contain `tenant:everyone:{tenantId}` and nothing else, and the caller SHALL remain able to sign in and use the product against tenant-wide material.

#### Scenario: A suspect link collapses the principal set to the tenant floor

- **WHEN** a caller whose link is `SUSPECT` resolves a principal set
- **THEN** the set contains exactly `tenant:everyone:{tenantId}`
- **AND** it contains no `entra:group:*`, `google:group:*`, or `local:group:*` principal

#### Scenario: A suspect link does not lock the person out

- **WHEN** the same caller sends a prompt request
- **THEN** the response status is 200
- **AND** the answer is grounded only in chunks whose access list contains `tenant:everyone:{tenantId}`

#### Scenario: A disabled link behaves the same way

- **WHEN** an administrator sets a link's status to `DISABLED` and that caller resolves a principal set
- **THEN** the set contains exactly `tenant:everyone:{tenantId}`

### Requirement: Administrators can list and inspect identity links

AscendAgent SHALL expose `GET /api/v1/admin/identity-links` and `GET /api/v1/admin/identity-links/{id}`, both requiring the `ADMIN` role. The list endpoint SHALL be cursor-paginated and filterable by status and by normalized email. The single-link response SHALL include the conflicting subject recorded at detection time, so an administrator can see why a link went `SUSPECT` without reading the database. Errors SHALL use `application/problem+json`. These endpoints expose email addresses and SHALL NOT be reachable by a caller holding only `USER`.

#### Scenario: An administrator finds the broken link

- **WHEN** an `ADMIN` calls `GET /api/v1/admin/identity-links?status=SUSPECT`
- **THEN** the response lists the suspect links with their normalized email, both recorded subjects, and their last-confirmation timestamp

#### Scenario: A user cannot enumerate links

- **WHEN** a caller holding only the `USER` role calls either identity-link read endpoint
- **THEN** the response status is 403
- **AND** no email address appears in the response body

### Requirement: Administrators can correct an identity link

AscendAgent SHALL expose `PATCH /api/v1/admin/identity-links/{id}`, requiring the `ADMIN` role, allowing a provider subject to be corrected and the status to be moved between `ACTIVE`, `SUSPECT`, and `DISABLED`. A successful correction SHALL delete that person's cached principal set, so the correction takes effect on their next request rather than after the cache time to live expires.

#### Scenario: Correcting a suspect link restores group principals

- **WHEN** an `ADMIN` corrects the stored provider subject on a `SUSPECT` link and sets its status to `ACTIVE`
- **THEN** the response status is 200
- **AND** the affected person's next request resolves a principal set containing their group principals again

#### Scenario: A correction invalidates the cached set immediately

- **WHEN** a correction succeeds while a cached principal set exists for that person
- **THEN** their next request resolves membership afresh rather than reading the pre-correction cached set

#### Scenario: A user cannot correct a link

- **WHEN** a caller holding only the `USER` role calls the correction endpoint
- **THEN** the response status is 403
- **AND** the link is unchanged
