## ADDED Requirements

### Requirement: Tenant lifecycle API restricted to platform operators

ascend-ai-agent SHALL expose `/api/v1/admin/tenants` supporting create, list, get, suspend and resume, restricted to the `PLATFORM_ADMIN` realm role. Tenant delete SHALL NOT exist before `add-audit-and-gdpr-compliance`, which owns erasure and adds it. A caller lacking `PLATFORM_ADMIN` (including a tenant `ADMIN`) SHALL receive HTTP 403. Tenant ids SHALL match the slug format `[a-z0-9-]{1,64}` defined by `add-tenant-isolation`; a create request with an invalid or already-used id SHALL be rejected with HTTP 400 or 409 respectively.

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

A tenant's status SHALL be `ACTIVE` or `SUSPENDED`. When the resolved tenant for a request is `SUSPENDED`, every data-plane operation (chat, ingestion, RAG retrieval, memory, source download) SHALL be refused with HTTP 403 right after the tenant is resolved - a single enforcement point, a request filter of this change placed after authentication, that reads the tenant from the fail-closed `TenantContext.currentTenantId()` of `add-keycloak-login`. The tenant status SHALL be the one suspension mechanism: suspend and resume SHALL change only the status and SHALL NOT disable or enable any Keycloak user, so resuming SHALL restore access for every user of the tenant except a user an administrator disabled one by one, who SHALL stay disabled. A token issued to a user of a suspended tenant, before or after the suspend, SHALL be refused on every data-plane operation. The filter SHALL read the status through a cache with a bounded time to live (setting `app.tenant.status-cache.ttl`, default 30 seconds) and a bounded size (setting `app.tenant.status-cache.max-size`, default 1000 entries), and a suspend or resume SHALL reach every agent instance through a Postgres `NOTIFY` on the channel `tenant_status_changed`, which every instance receives through the one Postgres listener of `add-keycloak-login` and answers by evicting the tenant's entry, and an instance that lost its listening connection SHALL clear its whole status cache once the connection is back.

#### Scenario: Suspended tenant cannot use the data plane

- **WHEN** tenant `acme` is suspended and one of its users sends `POST /api/v1/ai/prompt`
- **THEN** the response is HTTP 403
- **AND** the same is true for ingestion and RAG-backed requests

#### Scenario: Resume restores access

- **WHEN** a suspended tenant `acme` is resumed
- **THEN** its users can again chat, ingest, and retrieve

#### Scenario: Resume keeps a per-user disable

- **WHEN** a tenant `ADMIN` of `acme` disables one user, and tenant `acme` is then suspended and resumed
- **THEN** that user still cannot obtain a token
- **AND** the other users of `acme` can again chat, ingest, and retrieve

#### Scenario: A suspend reaches every agent instance

- **WHEN** two agent instances serve tenant `acme` and a `PLATFORM_ADMIN` suspends it through the first instance
- **THEN** the next request of a user of `acme` on the second instance is refused with 403
- **AND** it is refused before the time to live of the cached status ends

### Requirement: Administration operations are recorded through the audit port

Every tenant create, suspend and resume, every user invite, role change, enable, disable and removal, and every retrieval group operation SHALL record one `ADMIN_OPERATION` event through `AuditEventPort` of `add-deployment-modules`, naming the actor, the tenant, the operation and its target. The default of that port writes one structured log line, and `add-audit-and-gdpr-compliance` registers its implementation later, which stores the events as audit rows.

#### Scenario: A suspend is recorded

- **WHEN** a `PLATFORM_ADMIN` suspends tenant `acme`
- **THEN** one `ADMIN_OPERATION` event naming the suspend of `acme` reaches `AuditEventPort`

### Requirement: Tenant administration is covered by end-to-end tests against the live stack

The ascend-ai-agent e2e suite SHALL check the tenant lifecycle, user management and retrieval group APIs with deterministic Bruno tests that call no AI model, for every caller: no token, `USER`, tenant `ADMIN`, an `ADMIN` of another tenant and `PLATFORM_ADMIN`. The specs SHALL work on tenants and users of their own, SHALL read Keycloak state through the Keycloak admin command line, and SHALL assert statuses, response bodies, Keycloak state and delivered emails, never a log line. Tenant delete, user removal with erasure and the audit rows of these operations are checked by `add-audit-and-gdpr-compliance`, which lands after this change.

#### Scenario: Suspension is checked with a real user in the live stack

- **WHEN** the lifecycle spec suspends `e2e-lifecycle` while its administrator holds a token
- **THEN** that token and a newly issued token get 403 on chat, upload and conversation requests
- **AND** after resume a new token is issued and the authorization probe passes, while a user disabled one by one before the suspend still cannot obtain a token

#### Scenario: An invited user is checked in Keycloak, in the mail server and in the token

- **WHEN** the user management spec invites a user as `e2e-admin-acme`
- **THEN** Keycloak holds the user with `tenant` `e2e-acme`, role `USER` and no group, and the test mail server holds one set-password email
- **AND** an `ADMIN` of `e2e-globex` neither sees nor changes that user
