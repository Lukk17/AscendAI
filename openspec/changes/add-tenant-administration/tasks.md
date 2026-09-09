# Tasks — add-tenant-administration

## 1. Tenant status schema and Keycloak export

- [ ] 1.1 Add a Liquibase changelog adding `status` (`ACTIVE` / `SUSPENDED`, default `ACTIVE`) to the `tenants` table from `add-tenant-isolation`, with rollback
- [ ] 1.2 Extend the `add-auth-and-identity` realm export: add the `PLATFORM_ADMIN` realm role, the group-membership → `tenant` claim protocol mapper, and a confidential service-account client for the Admin API (least-privilege realm-management roles)
- [ ] 1.3 Add `@ConfigurationProperties` for the Keycloak Admin base URL and admin-client id/secret (env-driven, secret per `harden-cloud-deployment` conventions)

## 2. Keycloak Admin client

- [ ] 2.1 Create `service/identity/KeycloakAdminClient.java`: client-credentials token acquisition + refresh, create/delete group `/tenants/{tenantId}`, create/enable/disable/delete user, add-to-group, assign/remove realm role, trigger `execute-actions-email` (UPDATE_PASSWORD, VERIFY_EMAIL)
- [ ] 2.2 Unit tests (WireMock Keycloak Admin API): each operation issues the correct request; token refresh on 401; secret never logged

## 3. Tenant lifecycle service and API

- [ ] 3.1 Create `service/admin/TenantAdminService.java`: create (saga — Keycloak group first, then `tenants` row, rollback group on Postgres failure, idempotent by id), list, get, suspend, resume; validate the slug format from `add-tenant-isolation`
- [ ] 3.2 Implement delete as ordered erase-then-deprovision (design D5): suspend → per-tenant erasure job (`add-audit-and-gdpr-compliance`) → delete Keycloak group + users → delete `tenants` row; refuse delete with a clear error if the erasure capability is not present
- [ ] 3.3 Create `controller/admin/TenantAdminController.java` under `/api/v1/admin/tenants`: create (201 + Location), list (paginated), get (404 unknown), suspend/resume (200), delete (202 job or 204); restrict all to `PLATFORM_ADMIN`
- [ ] 3.4 Emit audit events (`add-audit-and-gdpr-compliance`) for tenant create / suspend / resume / delete
- [ ] 3.5 MockMvc tests: PLATFORM_ADMIN required (USER/ADMIN → 403); create provisions a Keycloak group; delete follows the erase-then-deprovision order

## 4. Suspension enforcement

- [ ] 4.1 In `add-tenant-isolation`'s tenant-context resolver, add: resolved tenant with `status = SUSPENDED` → 403 (fail-closed), covering every data-plane operation at one point
- [ ] 4.2 On suspend, disable the tenant's Keycloak users so new logins fail; document that already-issued tokens are backstopped by the Postgres status check until expiry
- [ ] 4.3 Integration test: a user of a suspended tenant is refused (403) on chat, ingest, and RAG; resume restores access

## 5. User management service and API

- [ ] 5.1 Create `service/admin/UserManagementService.java`: invite (create Keycloak user in the caller's tenant group, default role `USER`, trigger set-password email), list users of the caller's tenant, assign/revoke `ADMIN`/`USER`, enable/disable, remove (optionally chaining per-user erasure)
- [ ] 5.2 Create `controller/admin/UserAdminController.java` under `/api/v1/admin/users`: restrict to tenant `ADMIN`; derive the tenant from the caller's token, never from the path/body; 403 on any attempt to act on another tenant
- [ ] 5.3 Emit audit events for invite / role-change / enable-disable / remove
- [ ] 5.4 MockMvc + integration tests: invite creates a Keycloak user with `USER` and sends the email; a tenant ADMIN cannot list or mutate another tenant's users (403); role promotion/demotion reflected in Keycloak; remove disables/erases per option

## 6. Documentation and API collection

- [ ] 6.1 Extend `docs/SECURITY.md` (from `add-auth-and-identity`) with tenant and user administration: role model (`PLATFORM_ADMIN` vs tenant `ADMIN`), onboarding a tenant, inviting users, suspension and deletion semantics
- [ ] 6.2 Add Bruno requests under `docs/api/request/AscendAI/` for the tenant and user admin endpoints (with a PLATFORM_ADMIN token variant)
- [ ] 6.3 Note the admin endpoints and role model in `apps/ascend-agent/AGENTS.md`
- [ ] 6.4 Run `./gradlew test integrationTest`; all green
