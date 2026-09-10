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

### Requirement: Creating a tenant provisions its Keycloak group

Creating a tenant SHALL provision a Keycloak group `/tenants/{tenantId}` carrying a `tenant` attribute equal to the tenant id, so that the realm's group-membership protocol mapper populates the `tenant` claim for that tenant's users. Tenant creation SHALL be a saga: the Keycloak group is created before the `tenants` row, and a failure persisting the row SHALL roll back the group; retrying the create with the same id SHALL be idempotent.

#### Scenario: Group created with the tenant attribute

- **WHEN** a `PLATFORM_ADMIN` creates tenant `acme`
- **THEN** a Keycloak group `/tenants/acme` exists with a `tenant` attribute of `acme`

#### Scenario: Rollback on persistence failure

- **WHEN** the Keycloak group is created but persisting the `tenants` row fails
- **THEN** the Keycloak group is removed
- **AND** the create can be retried with the same id without leaving a duplicate group

### Requirement: Suspended tenant is refused fail-closed

A tenant's status SHALL be `ACTIVE` or `SUSPENDED`. When the resolved tenant for a request is `SUSPENDED`, every data-plane operation (chat, ingestion, RAG retrieval, memory, source download) SHALL be refused with HTTP 403 at tenant-context resolution — a single enforcement point layered onto the fail-closed resolver from `add-tenant-isolation`. Suspending a tenant SHALL also disable its Keycloak users so new logins fail; resuming SHALL restore both.

#### Scenario: Suspended tenant cannot use the data plane

- **WHEN** tenant `acme` is suspended and one of its users sends `POST /api/v1/ai/prompt`
- **THEN** the response is HTTP 403
- **AND** the same is true for ingestion and RAG-backed requests

#### Scenario: Resume restores access

- **WHEN** a suspended tenant `acme` is resumed
- **THEN** its users can again chat, ingest, and retrieve

### Requirement: Tenant deletion is erase-then-deprovision

Deleting a tenant SHALL proceed in order: suspend the tenant, run the per-tenant erasure job owned by `add-audit-and-gdpr-compliance` to zero residue, delete the Keycloak group and its users, then remove the `tenants` row. If the erasure capability is not present in the deployment, delete SHALL be refused with a clear error rather than orphaning data. Each step SHALL emit an audit event.

#### Scenario: Delete erases before deprovisioning

- **WHEN** a `PLATFORM_ADMIN` deletes tenant `acme` while erasure is available
- **THEN** the tenant is suspended, its data is erased across all stores, its Keycloak group and users are removed, and the `tenants` row is deleted
- **AND** audit rows record the suspend, erasure, and deprovision steps

#### Scenario: Delete refused without erasure

- **WHEN** a delete is requested but the erasure capability is not present
- **THEN** the delete is refused with an explanatory error and no data is orphaned
