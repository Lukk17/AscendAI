# Design - add-tenant-administration

## Context

Two sibling changes lay the groundwork this one builds on. `add-auth-and-identity` makes ascend-ai-agent an OAuth2 resource server against Keycloak (realm `ascend-ai`, roles `USER` / `ADMIN`, a PKCE public client for Flutter, and a `tenant` claim copied from the Keycloak user attribute `tenant` by a protocol mapper, `default` when the attribute is absent). `add-tenant-isolation` adds the `tenants` table, a fail-closed tenant-context holder resolved from the `tenant` claim, the slug format `[a-z0-9-]{1,64}`, and a default-tenant migration. Neither creates tenants or users at runtime, and nothing sets the `tenant` attribute on a directly invited user. `add-audit-and-gdpr-compliance`, built just before this change, supplies the erasure orchestrator, the `AuditRecorder` and a tenant-scoped audit query. Build order (owner, 2026-10-01): groups A, B, D, `harden-cloud-deployment`, `add-auth-and-identity`, `add-tenant-isolation`, `add-usage-metering-and-quotas`, `add-audit-and-gdpr-compliance`, this change, then `add-tenant-policy`.

The go-to-market is single-tenant-per-customer dedicated stacks first, multi-tenant later. The API must serve both: a `PLATFORM_ADMIN` who manages tenants (rare on a dedicated stack, central under multi-tenancy) and a tenant `ADMIN` who manages their own users (the common case on every stack).

## Goals / Non-Goals

**Goals:**

- Runtime tenant lifecycle (create / suspend / resume / delete) behind a platform-operator role.
- Runtime user management (invite / roles / enable-disable / remove) behind tenant admin, scoped to the caller's tenant.
- Set the Keycloak `tenant` user attribute on every invited user so their token carries the right `tenant` claim, and send the invitation email through the realm SMTP settings.
- Fail-closed suspension: a suspended tenant cannot use any data-plane operation.

**Non-Goals:**

- Data isolation enforcement (owned by `add-tenant-isolation`), quotas / BYOK (owned by `add-usage-metering-and-quotas`), per-tenant provider/tool policy (owned by `add-tenant-policy`).
- Self-service tenant signup / billing-driven provisioning (no public signup; tenants are operator-created).
- SSO / external IdP federation beyond the issuer-uri swap the auth change already allows.
- Any UI (Flutter client is a separate change).

## Decisions

### D1 - The Keycloak user attribute `tenant` is the one source of the `tenant` claim

`add-auth-and-identity` already decides where the claim comes from: a protocol mapper in the realm export copies the user attribute `tenant` into the `tenant` access-token claim, a realm user with no attribute gets `default`, and a brokered provider's hardcoded-attribute mapper stamps the attribute for every user who arrives through it (auth design D3 and D15). This change uses that same attribute and adds no second path.

- Invite sets the attribute. `UserManagementService` creates the Keycloak user with `attributes.tenant = [<caller's tenant>]`, where the tenant comes from the inviting admin's resolved tenant context, never from the request path or body.
- The attribute is admin-only. The realm export's user profile declares `tenant` with `view` and `edit` permission for `admin` only, so a user cannot change their own tenant through the account console or a self-service API. A brokered user's attribute is written by the provider's hardcoded-attribute mapper, which an end user cannot influence either.
- No tenant groups. A Keycloak group per tenant would be emitted by the D9 group mapper of `add-auth-and-identity` into the group claim, and every group in that claim becomes a `local:group:<name>` retrieval principal. A `/tenants/acme` group would therefore widen what a user can retrieve and would be a second, competing source of the tenant value. Tenant membership is the attribute, and groups stay purely for retrieval breadth as auth defines them.
- Moving a user to another tenant is an attribute change through the Admin API by a `PLATFORM_ADMIN`, followed by the user's next token. It is not part of the tenant `ADMIN` surface.

Alternative considered: a group per tenant with a group attribute and a group-membership mapper. Rejected for the two reasons above: it conflicts with auth's broker mapper, which stamps a user attribute, and it leaks a group into retrieval principals.

### D2 - `PLATFORM_ADMIN` is a new realm role, additive to the export

Tenant lifecycle is a cross-tenant privilege, so it cannot be the tenant-scoped `ADMIN`. A new realm role `PLATFORM_ADMIN` gates `/api/v1/admin/tenants`. On a dedicated single-tenant stack it is held by the operator; under multi-tenancy it is the control-plane role. Tenant `ADMIN` (already defined by `add-auth-and-identity`) gates `/api/v1/admin/users` and is always constrained to the caller's own tenant server-side, never a path/body-supplied tenant.

### D3 - ascend-ai-agent talks to Keycloak through the Admin REST API with a service account

Provisioning (create group, create user, assign role, trigger invite email) happens through Keycloak's Admin REST API. ascend-ai-agent authenticates with a dedicated confidential client using client-credentials (service account with the `manage-users` and `view-users` realm-management roles, nothing more, because no group or client is created). The secret follows the deployment secret conventions from `harden-cloud-deployment`.

- Invitation flow: create the user with the `tenant` attribute, then trigger Keycloak's `execute-actions-email` with `UPDATE_PASSWORD` and `VERIFY_EMAIL` so Keycloak sends the set-password email. ascend-ai-agent never handles the password.
- SMTP: `execute-actions-email` fails without a realm mail server. The realm export gains an `smtpServer` block (host, port, from address, `auth`, `starttls`, user, password) whose values are placeholders the Keycloak import resolves from the environment, so no mail secret is committed. Development points it at a local test mail server, production at the operator's relay. The variable names are chosen at implementation time and documented in `.env.example`.

### D4 - Tenant status lives in Postgres; suspension is enforced at tenant-context resolution

The `tenants` table (from `add-tenant-isolation`) gains a `status` column (`ACTIVE` / `SUSPENDED`). Suspension is enforced where the tenant is already resolved: `add-tenant-isolation`'s tenant-context resolver adds "resolved tenant is `SUSPENDED` → 403". This is one enforcement point covering every data-plane operation (chat, ingest, RAG, memory), rather than scattering checks per endpoint. Suspending also disables the tenant's Keycloak users (found by the Admin API user search on attribute `tenant`) so new logins fail and existing tokens stop being reissued; the Postgres check is the immediate backstop for already-issued tokens until they expire.

### D5 - Delete is erase-then-deprovision, ordered and audited

Deleting a tenant is destructive and ordered: (1) suspend, (2) run the per-tenant erasure job of `add-audit-and-gdpr-compliance` to zero residue by calling its `ErasureOrchestrator` directly (the HTTP endpoint there is for the tenant's own `ADMIN`), (3) disable the Keycloak users whose `tenant` attribute equals the tenant id and clear their personal attributes, never deleting them (owner decision, 2026-10-01, the same rule erasure follows), (4) remove the `tenants` row. Each step is audited as `ADMIN_OPERATION`. `add-audit-and-gdpr-compliance` is built before this change, so erasure is always present.

### D6 - `PLATFORM_ADMIN` reads the audit log across tenants

`add-audit-and-gdpr-compliance` filters `GET /api/v1/audit` to the caller's tenant for a tenant `ADMIN`. This change adds one rule: a caller holding `PLATFORM_ADMIN` sees every tenant's rows and may filter with an optional `tenant` parameter. A tenant `ADMIN` passing `tenant` is still filtered to their own tenant.

## Risks / Trade-offs

- [Keycloak Admin API coupling] → the Admin client is isolated behind `KeycloakAdminClient` so an IdP swap replaces one class; the REST surface stays IdP-agnostic.
- [Suspended tenant with a still-valid token] → Postgres status check at context resolution is the immediate backstop; token lifetimes are kept short in the realm export.
- [Partial invite failure (Keycloak user created, email not sent)] → invite is idempotent by email within the tenant: a retry finds the existing user and triggers the email again. Tenant create touches Postgres only, so it needs no saga.
- [PLATFORM_ADMIN on a single-tenant stack is heavy] → acceptable; on a dedicated stack the operator holds it and rarely uses it, and it is the exact primitive multi-tenancy needs later.

## Open Questions

- None blocking. Invited users default to `USER` only (least privilege, promotion to `ADMIN` is an explicit second call).
- Closed (owner, 2026-10-01): every administration endpoint lives under the one prefix `/api/v1/admin/`. This change owns `/api/v1/admin/tenants` and `/api/v1/admin/users`.
- Closed (owner, 2026-10-01): a Keycloak account is disabled and never deleted, on erasure, on user removal and in D5 step 3. Removing a user disables the account and clears its personal attributes.
