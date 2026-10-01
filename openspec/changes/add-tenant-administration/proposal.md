## Why

`add-tenant-isolation` creates the `tenants` table and enforces the `tenant` claim, and `add-auth-and-identity` ships Keycloak with realm roles `USER` / `ADMIN` and a reserved `tenant` claim. But nothing creates a tenant at runtime, invites a user, assigns a role, or sets the Keycloak user attribute that the realm's `tenant` protocol mapper turns into the `tenant` claim. Today a tenant exists only because a Liquibase default-tenant migration inserted one row, and a user exists only if someone edited Keycloak by hand. That is not a product: onboarding a customer, adding a colleague, promoting someone to admin, or offboarding all require manual database and Keycloak surgery.

This change is the control plane. Under the single-tenant-per-customer go-to-market it is what lets a customer admin invite their colleagues and manage roles without operator involvement. Under later multi-tenancy it is what lets one operator create and suspend tenants across a shared deployment. It is deliberately scoped to lifecycle and membership: it does not touch data isolation (owned by `add-tenant-isolation`), quotas (owned by `add-usage-metering-and-quotas`), or per-tenant provider policy (owned by `add-tenant-policy`).

## What Changes

- **Tenant lifecycle API** under `/api/v1/admin/tenants`, restricted to a new platform-operator role `PLATFORM_ADMIN` (a realm role added to the `add-auth-and-identity` export): create, list, get, suspend/resume, and delete a tenant. Tenant ids remain the constrained slug (`[a-z0-9-]{1,64}`) defined by `add-tenant-isolation`.
- Keycloak side of a tenant: one source of truth for the `tenant` claim, the Keycloak user attribute `tenant`. `add-auth-and-identity` already ships the protocol mapper that copies that attribute into the `tenant` claim, and for a brokered customer its hardcoded-attribute mapper stamps the same attribute. This change sets the attribute on every user it invites, server-side from the inviting admin's tenant, and makes the attribute admin-only in the realm's user profile so a user can never edit it in the account console. No `/tenants/...` Keycloak group is created, so no tenant group reaches the group claim and no `local:group:*` retrieval principal is minted for a tenant. Creating a tenant is a `tenants` row only. Deleting a tenant runs the per-tenant erasure job from `add-audit-and-gdpr-compliance` and then disables, never deletes, the Keycloak users whose `tenant` attribute equals the tenant id.
- **User management API** under `/api/v1/admin/users`, restricted to tenant `ADMIN` and always scoped to the caller's own tenant: invite a user (creates the Keycloak user with the `tenant` attribute set to the caller's tenant and triggers Keycloak's built-in set-password email, which needs the realm SMTP settings this change adds to the realm export), list users, assign or revoke the `ADMIN` / `USER` role, enable/disable, and remove a user, which disables the Keycloak account and never deletes it (with the option to hand off to per-user erasure).
- **Suspend semantics, fail-closed**: a suspended tenant's users are refused at tenant-context resolution - `add-tenant-isolation` already fails closed on an unresolved tenant; this change adds "resolved but suspended → 403" so a suspended customer cannot chat, ingest, or read, while their data is retained until an explicit delete.
- **Keycloak Admin client**: ascend-ai-agent gains a Keycloak Admin REST client authenticated by a service-account (client-credentials) so it can create groups/users, assign roles, and trigger invitation emails. This is the one new outbound trust relationship; its client secret follows the deployment's secret conventions.

## Capabilities

### New Capabilities

- `tenant-administration`: platform-operator tenant lifecycle API (create/list/get/suspend/resume/delete), fail-closed suspension, the delete-after-erasure ordering, and cross-tenant audit query for `PLATFORM_ADMIN`.
- `user-management`: tenant-admin user lifecycle API (invite/list/role-assignment/enable-disable/remove) scoped to the caller's tenant, backed by Keycloak user provisioning with the admin-only `tenant` attribute and invitation emails over the realm SMTP settings.

### Modified Capabilities

(none as spec deltas - `agent-authentication` and `tenant-isolation` are defined only in their sibling changes, which are not yet archived, so their base specs are not in `openspec/specs/` to modify. The additive rules those capabilities need - the `PLATFORM_ADMIN` role and authorization matrix for the admin endpoints, and the suspended-tenant fail-closed 403 at tenant-context resolution - are stated as ADDED requirements in this change's `tenant-administration` capability, and the realm-export and resolver edits are coordinated into `add-auth-and-identity` and `add-tenant-isolation` via the tasks. When those changes archive first, the enforcement point is theirs; this change references it.)

## Impact

- Depends on: `add-auth-and-identity` (Keycloak, roles, the `tenant` attribute mapper, resource-server posture), `add-tenant-isolation` (tenants table, tenant-context holder, slug format) and `add-audit-and-gdpr-compliance` (the erasure orchestrator that tenant delete calls, the `AuditRecorder` that admin actions emit through, and the tenant-scoped audit query this change widens for `PLATFORM_ADMIN`). All three land first, so every audit dependency is met. Build order (owner, 2026-10-01): groups A, B, D, `harden-cloud-deployment`, `add-auth-and-identity`, `add-tenant-isolation`, `add-usage-metering-and-quotas`, `add-audit-and-gdpr-compliance`, this change, then `add-tenant-policy`.
- **ascend-ai-agent (new code)**: `controller/admin/TenantAdminController.java`, `controller/admin/UserAdminController.java`; `service/admin/` package (tenant lifecycle service, user management service); `service/identity/KeycloakAdminClient.java` (Admin REST client); DTOs under `dto/`; Spring Data JDBC touch-points on the `tenants` aggregate from `add-tenant-isolation` (add a `status` column, `ACTIVE` / `SUSPENDED`, via a Liquibase changelog `<NN>-tenant-status.xml` numbered at implementation time).
- Keycloak realm export (`add-auth-and-identity` artifact): add the `PLATFORM_ADMIN` role, the user-profile rule that makes the `tenant` attribute admin-only, the realm `smtpServer` block for invitation email (values supplied at import from the deployment's secrets), and a service-account client for the Admin API. The `tenant` claim mapper itself is already in the export and is not changed.
- Config: Keycloak Admin base URL (the separate Keycloak service on host port 8180 in development), admin-client id/secret, and the SMTP host, port, sender, user and password for the realm, all via env following the secret conventions of `harden-cloud-deployment`. The variable names are chosen at implementation time and listed in `.env.example`.
- **Docs**: `docs/SECURITY.md` (from `add-auth-and-identity`) gains a tenant/user administration section; `AGENTS.md` endpoint notes; Bruno requests for the admin API.
- Tests: invite → Keycloak user with `tenant` attribute and `USER` role asserted, and the user's token carries `tenant` and no tenant group (Keycloak Testcontainer); invitation email captured by a test SMTP server; suspended-tenant request returns 403; tenant-admin cannot manage another tenant's users; PLATFORM_ADMIN required for tenant lifecycle.

## Relevant Skills

- `/springboot-patterns`
- `/java-coding-standards`
- `/api-design`
- `/postgres-patterns`
- `/database-migrations`
- `/docker-patterns`
- `/tdd-workflow`
