# Design — add-tenant-administration

## Context

Two sibling changes lay the groundwork this one builds on. `add-auth-and-identity` makes ascend-ai-agent an OAuth2 resource server against Keycloak (realm `ascend-ai`, roles `USER` / `ADMIN`, a PKCE public client for Flutter, and a `tenant` claim that is defined and propagated but not yet populated per user). `add-tenant-isolation` adds the `tenants` table, a fail-closed tenant-context holder resolved from the `tenant` claim, the slug format `[a-z0-9-]{1,64}`, and a default-tenant migration. Neither creates tenants or users at runtime, and neither wires the Keycloak side that would make a real user's token carry a `tenant` claim.

The go-to-market is single-tenant-per-customer dedicated stacks first, multi-tenant later. The API must serve both: a `PLATFORM_ADMIN` who manages tenants (rare on a dedicated stack, central under multi-tenancy) and a tenant `ADMIN` who manages their own users (the common case on every stack).

## Goals / Non-Goals

**Goals:**

- Runtime tenant lifecycle (create / suspend / resume / delete) behind a platform-operator role.
- Runtime user management (invite / roles / enable-disable / remove) behind tenant admin, scoped to the caller's tenant.
- Provision the Keycloak side so a created tenant yields a populated `tenant` claim and an invited user can log in.
- Fail-closed suspension: a suspended tenant cannot use any data-plane operation.

**Non-Goals:**

- Data isolation enforcement (owned by `add-tenant-isolation`), quotas / BYOK (owned by `add-usage-metering-and-quotas`), per-tenant provider/tool policy (owned by `add-tenant-policy`).
- Self-service tenant signup / billing-driven provisioning (no public signup; tenants are operator-created).
- SSO / external IdP federation beyond the issuer-uri swap the auth change already allows.
- Any UI (Flutter client is a separate change).

## Decisions

### D1 — Keycloak group-per-tenant carries the `tenant` claim

Each tenant maps to a Keycloak group `/tenants/{tenantId}` with a group attribute `tenant = {tenantId}`. A group-membership protocol mapper (added to the realm export) copies that attribute into the `tenant` token claim. A user belongs to exactly one tenant group, so their token carries exactly one `tenant`. This keeps the claim source declarative in Keycloak rather than hand-managed per user, and makes "move a user to another tenant" a group change, not a claim edit.

- Alternative considered: a `tenant` user attribute set per user — rejected because it duplicates the value on every user and drifts; the group attribute is one source of truth per tenant.

### D2 — `PLATFORM_ADMIN` is a new realm role, additive to the export

Tenant lifecycle is a cross-tenant privilege, so it cannot be the tenant-scoped `ADMIN`. A new realm role `PLATFORM_ADMIN` gates `/api/v1/admin/tenants`. On a dedicated single-tenant stack it is held by the operator; under multi-tenancy it is the control-plane role. Tenant `ADMIN` (already defined by `add-auth-and-identity`) gates `/api/v1/admin/users` and is always constrained to the caller's own tenant server-side, never a path/body-supplied tenant.

### D3 — ascend-ai-agent talks to Keycloak through the Admin REST API with a service account

Provisioning (create group, create user, assign role, trigger invite email) happens through Keycloak's Admin REST API. ascend-ai-agent authenticates with a dedicated confidential client using client-credentials (service account with the `manage-users` / `manage-clients` realm-management roles it needs, nothing more). The secret follows the deployment secret conventions from `harden-cloud-deployment`.

- Invitation flow: create the user disabled-until-verified, then trigger Keycloak's `execute-actions-email` with `UPDATE_PASSWORD` (and `VERIFY_EMAIL`) so Keycloak sends the branded set-password email. ascend-ai-agent never handles the password.

### D4 — Tenant status lives in Postgres; suspension is enforced at tenant-context resolution

The `tenants` table (from `add-tenant-isolation`) gains a `status` column (`ACTIVE` / `SUSPENDED`). Suspension is enforced where the tenant is already resolved: `add-tenant-isolation`'s tenant-context resolver adds "resolved tenant is `SUSPENDED` → 403". This is one enforcement point covering every data-plane operation (chat, ingest, RAG, memory), rather than scattering checks per endpoint. Suspending also disables the tenant's Keycloak users so new logins fail and existing tokens stop being reissued; the Postgres check is the immediate backstop for already-issued tokens until they expire.

### D5 — Delete is erase-then-deprovision, ordered and audited

Deleting a tenant is destructive and ordered: (1) suspend, (2) run the per-tenant erasure job (`add-audit-and-gdpr-compliance`) to zero-residue, (3) delete the Keycloak group and its users, (4) remove the `tenants` row. Each step is audited. If erasure is not yet available (that change not implemented), delete is refused with a clear error rather than leaving orphaned data — delete depends on erasure being present.

## Risks / Trade-offs

- [Keycloak Admin API coupling] → the Admin client is isolated behind `KeycloakAdminClient` so an IdP swap replaces one class; the REST surface stays IdP-agnostic.
- [Suspended tenant with a still-valid token] → Postgres status check at context resolution is the immediate backstop; token lifetimes are kept short in the realm export.
- [Partial provisioning failure (Postgres row created, Keycloak group not)] → tenant create is a saga: create Keycloak group first, then the Postgres row; on Postgres failure the group is rolled back; create is idempotent on retry by tenant id.
- [PLATFORM_ADMIN on a single-tenant stack is heavy] → acceptable; on a dedicated stack the operator holds it and rarely uses it, and it is the exact primitive multi-tenancy needs later.

## Open Questions

- None blocking. Whether invited users default to `USER` only (yes, principle of least privilege; promotion to `ADMIN` is an explicit second call) is settled as least-privilege.
