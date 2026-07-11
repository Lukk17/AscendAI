## Why

`add-tenant-isolation` creates the `tenants` table and enforces the `tenant` claim, and `add-auth-and-identity` ships Keycloak with realm roles `USER` / `ADMIN` and a reserved `tenant` claim. But nothing creates a tenant at runtime, invites a user, assigns a role, or provisions the Keycloak side that makes the `tenant` claim appear in a token. Today a tenant exists only because a Liquibase default-tenant migration inserted one row, and a user exists only if someone edited Keycloak by hand. That is not a product: onboarding a customer, adding a colleague, promoting someone to admin, or offboarding all require manual database and Keycloak surgery.

This change is the control plane. Under the single-tenant-per-customer go-to-market it is what lets a customer admin invite their colleagues and manage roles without operator involvement. Under later multi-tenancy it is what lets one operator create and suspend tenants across a shared deployment. It is deliberately scoped to lifecycle and membership: it does not touch data isolation (owned by `add-tenant-isolation`), quotas (owned by `add-usage-metering-and-quotas`), or per-tenant provider policy (owned by `add-tenant-policy`).

## What Changes

- **Tenant lifecycle API** under `/api/v1/admin/tenants`, restricted to a new platform-operator role `PLATFORM_ADMIN` (a realm role added to the `add-auth-and-identity` export): create, list, get, suspend/resume, and delete a tenant. Tenant ids remain the constrained slug (`[a-z0-9-]{1,64}`) defined by `add-tenant-isolation`.
- **Keycloak provisioning for tenants**: creating a tenant provisions a Keycloak group `/tenants/{tenantId}` carrying a `tenant` attribute, and the realm export's group-membership → `tenant` claim mapper populates the JWT from it. Deleting a tenant removes the group (after the tenant's data erasure, owned by `add-audit-and-gdpr-compliance`, is run). This makes the reserved `tenant` claim from `add-auth-and-identity` actually populated per user.
- **User management API** under `/api/v1/admin/users`, restricted to tenant `ADMIN` and always scoped to the caller's own tenant: invite a user (creates the Keycloak user in the tenant group and triggers Keycloak's built-in invitation / set-password email), list users, assign or revoke the `ADMIN` / `USER` role, enable/disable, and remove a user (with the option to hand off to per-user erasure).
- **Suspend semantics, fail-closed**: a suspended tenant's users are refused at tenant-context resolution — `add-tenant-isolation` already fails closed on an unresolved tenant; this change adds "resolved but suspended → 403" so a suspended customer cannot chat, ingest, or read, while their data is retained until an explicit delete.
- **Keycloak Admin client**: AscendAgent gains a Keycloak Admin REST client authenticated by a service-account (client-credentials) so it can create groups/users, assign roles, and trigger invitation emails. This is the one new outbound trust relationship; its client secret follows the deployment's secret conventions.

## Capabilities

### New Capabilities

- `tenant-administration`: platform-operator tenant lifecycle API (create/list/get/suspend/resume/delete), Keycloak group provisioning per tenant, fail-closed suspension, and the delete-after-erasure ordering.
- `user-management`: tenant-admin user lifecycle API (invite/list/role-assignment/enable-disable/remove) scoped to the caller's tenant, backed by Keycloak user provisioning and invitation emails.

### Modified Capabilities

(none as spec deltas — `agent-authentication` and `tenant-isolation` are defined only in their sibling changes, which are not yet archived, so their base specs are not in `openspec/specs/` to modify. The additive rules those capabilities need — the `PLATFORM_ADMIN` role and authorization matrix for the admin endpoints, and the suspended-tenant fail-closed 403 at tenant-context resolution — are stated as ADDED requirements in this change's `tenant-administration` capability, and the realm-export and resolver edits are coordinated into `add-auth-and-identity` and `add-tenant-isolation` via the tasks. When those changes archive first, the enforcement point is theirs; this change references it.)

## Impact

- **Depends on**: `add-auth-and-identity` (Keycloak, roles, `tenant` claim, resource-server posture) and `add-tenant-isolation` (tenants table, tenant-context holder, slug format). Both must land first. Coordinates with `add-audit-and-gdpr-compliance` (tenant delete runs its erasure job; admin actions emit its audit events).
- **AscendAgent (new code)**: `controller/admin/TenantAdminController.java`, `controller/admin/UserAdminController.java`; `service/admin/` package (tenant lifecycle service, user management service); `service/identity/KeycloakAdminClient.java` (Admin REST client); DTOs under `dto/`; JPA touch-points on the `tenants` entity from `add-tenant-isolation` (add `status` column via a Liquibase changelog: `ACTIVE` / `SUSPENDED`).
- **Keycloak realm export** (`add-auth-and-identity` artifact): add the `PLATFORM_ADMIN` role, the group-membership → `tenant` claim protocol mapper, and a service-account client for the Admin API; coordinated as an additive export edit.
- **Config**: Keycloak Admin base URL, admin-client id/secret via env following the secret conventions of `harden-cloud-deployment`.
- **Docs**: `docs/SECURITY.md` (from `add-auth-and-identity`) gains a tenant/user administration section; `AGENTS.md` endpoint notes; Bruno requests for the admin API.
- **Tests**: tenant create → Keycloak group asserted; invite → Keycloak user + role asserted (WireMock or a Keycloak Testcontainer); suspended-tenant request returns 403; tenant-admin cannot manage another tenant's users; PLATFORM_ADMIN required for tenant lifecycle.

## Relevant Skills

- `/springboot-security`
- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/jpa-patterns`
- `/database-migrations`
- `/docker-patterns`
- `/springboot-tdd`
