## ADDED Requirements

### Requirement: Tenant lifecycle API restricted to platform operators

ascend-ai-agent SHALL expose `/api/v1/admin/tenants` supporting create, list, get, suspend, resume, and delete, restricted to the `PLATFORM_ADMIN` realm role. A caller lacking `PLATFORM_ADMIN` (including a tenant `ADMIN`) SHALL receive HTTP 403. Tenant ids SHALL match the slug format `[a-z0-9-]{1,64}` defined by `add-tenant-isolation`; a create request with an invalid or already-used id SHALL be rejected with HTTP 400 or 409 respectively.

#### Scenario: Non-platform-admin refused

- **WHEN** a caller holding only tenant `ADMIN` sends `POST /api/v1/admin/tenants`
- **THEN** the response is HTTP 403 and no tenant is created

#### Scenario: Create with a valid id

- **WHEN** a `PLATFORM_ADMIN` creates a tenant with id `acme`
- **THEN** the response is HTTP 201 with a `Location` header for the new tenant
- **AND** a `tenants` row exists with id `acme` and status `ACTIVE`

#### Scenario: Duplicate id rejected

- **WHEN** a `PLATFORM_ADMIN` creates a tenant whose id already exists
- **THEN** the response is HTTP 409 and no second tenant is created

### Requirement: The tenant claim has one source and creates no tenant group

The `tenant` claim SHALL come only from the Keycloak user attribute `tenant`, copied by the protocol mapper that `add-auth-and-identity` ships, or stamped by a brokered provider's hardcoded-attribute mapper. Creating a tenant SHALL create the `tenants` row only and SHALL NOT create any Keycloak group, so no tenant value ever appears in the group claim or becomes a `local:group:*` retrieval principal. The realm's user profile SHALL make the `tenant` attribute viewable and editable by administrators only.

#### Scenario: Tenant create leaves Keycloak groups unchanged

- **WHEN** a `PLATFORM_ADMIN` creates tenant `acme`
- **THEN** the set of Keycloak groups in realm `ascend-ai` is the same as before the call

#### Scenario: A user cannot edit their own tenant

- **WHEN** a user of tenant `acme` updates their own `tenant` attribute to `globex` through the Keycloak account API
- **THEN** the update is refused and their next token still carries `tenant` = `acme`

### Requirement: Suspended tenant is refused fail-closed

A tenant's status SHALL be `ACTIVE` or `SUSPENDED`. When the resolved tenant for a request is `SUSPENDED`, every data-plane operation (chat, ingestion, RAG retrieval, memory, source download) SHALL be refused with HTTP 403 at tenant-context resolution - a single enforcement point layered onto the fail-closed resolver from `add-tenant-isolation`. Suspending a tenant SHALL also disable its Keycloak users, found by their `tenant` attribute, so new logins fail. Resuming SHALL restore both.

#### Scenario: Suspended tenant cannot use the data plane

- **WHEN** tenant `acme` is suspended and one of its users sends `POST /api/v1/ai/prompt`
- **THEN** the response is HTTP 403
- **AND** the same is true for ingestion and RAG-backed requests

#### Scenario: Resume restores access

- **WHEN** a suspended tenant `acme` is resumed
- **THEN** its users can again chat, ingest, and retrieve

### Requirement: Tenant deletion is erase-then-deprovision

Deleting a tenant SHALL proceed in order: suspend the tenant, run the per-tenant erasure job owned by `add-audit-and-gdpr-compliance` to zero residue, disable the Keycloak users whose `tenant` attribute equals the tenant id and clear their personal attributes without deleting them, then remove the `tenants` row. If the erasure job ends `PARTIAL` or `FAILED`, the delete SHALL stop before removing users or the row and report the job id. Each step SHALL emit an `ADMIN_OPERATION` audit event.

#### Scenario: Delete erases before deprovisioning

- **WHEN** a `PLATFORM_ADMIN` deletes tenant `acme` while erasure is available
- **THEN** the tenant is suspended, its data is erased across all stores, its Keycloak users are disabled and not deleted, and the `tenants` row is deleted
- **AND** audit rows record the suspend, erasure, and deprovision steps

#### Scenario: Delete stops on incomplete erasure

- **WHEN** the erasure job for tenant `acme` ends with status `PARTIAL`
- **THEN** the Keycloak users and the `tenants` row of `acme` remain
- **AND** the response names the erasure job id

### Requirement: Platform operators read the audit log across tenants

`GET /api/v1/audit` from `add-audit-and-gdpr-compliance` SHALL return rows of every tenant to a caller holding `PLATFORM_ADMIN`, with an optional `tenant` filter. A tenant `ADMIN` SHALL still receive only rows of their own tenant, whatever `tenant` value they pass.

#### Scenario: Platform admin filters by tenant

- **WHEN** a `PLATFORM_ADMIN` calls `GET /api/v1/audit?tenant=acme`
- **THEN** the response contains only rows of tenant `acme`

#### Scenario: Tenant admin cannot widen the query

- **WHEN** an `ADMIN` of tenant `acme` calls `GET /api/v1/audit?tenant=globex`
- **THEN** the response contains only rows of tenant `acme`
