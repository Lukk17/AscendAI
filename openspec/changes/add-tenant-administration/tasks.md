# Tasks - add-tenant-administration

## 1. Tenant status schema and Keycloak export

- [ ] 1.1 Add Liquibase changelog `apps/ascend-agent/src/main/resources/db/changelog/<NN>-tenant-status.xml` (NN is the next free number at implementation time) adding `status` (`ACTIVE` / `SUSPENDED`, default `ACTIVE`) to the `tenants` table from `add-tenant-isolation`, with rollback, and add the field to the Spring Data JDBC `Tenant` aggregate. Acceptance: `./gradlew integrationTest` applies it on Testcontainers Postgres and existing rows read `ACTIVE`
- [ ] 1.2 Extend the `add-auth-and-identity` realm export: add the `PLATFORM_ADMIN` realm role, a user-profile entry making the `tenant` attribute view and edit for `admin` only, and a confidential service-account client for the Admin API with `manage-users` and `view-users` only. Do not add a tenant group or a second `tenant` mapper. Acceptance: a Keycloak Testcontainer imports the export, the service account token holds exactly those two client roles, and a user's attempt to edit `tenant` through the account API is refused
- [ ] 1.3 Add `@ConfigurationProperties` for the Keycloak Admin base URL and admin-client id/secret (env-driven, secret per `harden-cloud-deployment` conventions). Acceptance: a `@SpringBootTest` binding test fails startup with a clear message when the secret is missing
- [ ] 1.4 Add the realm `smtpServer` block (host, port, from, `auth`, `starttls`, user, password) to the realm export as import-time environment placeholders, add the variables to the root `.env.example` (names chosen at implementation time), and add a local test mail server for development. Acceptance: an invite in the Keycloak Testcontainer test delivers one email to the test mail server

## 2. Keycloak Admin client

- [ ] 2.1 Create `service/identity/KeycloakAdminClient.java`: client-credentials token acquisition + refresh, create user with the `tenant` attribute, search users by attribute `tenant`, enable/disable user, clear a user's personal attributes (no delete operation), assign/remove realm role, trigger `execute-actions-email` (UPDATE_PASSWORD, VERIFY_EMAIL). No group operations. Acceptance: task 2.2 passes
- [ ] 2.2 Unit tests (WireMock Keycloak Admin API): each operation issues the correct request; token refresh on 401; secret never logged

## 3. Tenant lifecycle service and API

- [ ] 3.1 Create `service/admin/TenantAdminService.java`: create (`tenants` row only, 409 on an existing id), list, get, suspend, resume; validate the slug format from `add-tenant-isolation`. Acceptance: a unit test shows create makes no Keycloak call
- [ ] 3.2 Implement delete as ordered erase-then-deprovision (design D5): suspend → per-tenant erasure through `ErasureOrchestrator` from `add-audit-and-gdpr-compliance` → disable the Keycloak users whose `tenant` attribute matches and clear their personal attributes, never deleting them → delete `tenants` row. Stop and report the job id when erasure ends `PARTIAL` or `FAILED`. Acceptance: an integration test with a forced `PARTIAL` job leaves the users and the row in place
- [ ] 3.3 Create `controller/admin/TenantAdminController.java` under `/api/v1/admin/tenants`: create (201 + Location), list (paginated), get (404 unknown), suspend/resume (200), delete (202 job or 204); restrict all to `PLATFORM_ADMIN`. Acceptance: task 3.5 passes
- [ ] 3.4 Emit `ADMIN_OPERATION` audit events through `AuditRecorder` (`add-audit-and-gdpr-compliance`) for tenant create / suspend / resume / delete. Acceptance: an integration test finds one `audit_log` row per operation with the operation name in `details`
- [ ] 3.5 MockMvc tests: PLATFORM_ADMIN required (USER/ADMIN → 403); create leaves Keycloak untouched, delete follows the erase-then-deprovision order
- [ ] 3.6 Widen `GET /api/v1/audit` from `add-audit-and-gdpr-compliance` for `PLATFORM_ADMIN` (all tenants, optional `tenant` filter) while a tenant `ADMIN` stays on their own tenant. Acceptance: `AuditControllerIT` gains both scenarios of the `tenant-administration` spec and they pass

## 4. Suspension enforcement

- [ ] 4.1 In `add-tenant-isolation`'s tenant-context resolver, add: resolved tenant with `status = SUSPENDED` → 403 (fail-closed), covering every data-plane operation at one point. Acceptance: task 4.3 passes
- [ ] 4.2 On suspend, disable the tenant's Keycloak users (search by attribute `tenant`) so new logins fail, and enable them again on resume. Document in `docs/SECURITY.md` that already-issued tokens are backstopped by the Postgres status check until expiry. Acceptance: in the Keycloak Testcontainer test a suspended user cannot obtain a token and a resumed one can
- [ ] 4.3 Integration test: a user of a suspended tenant is refused (403) on chat, ingest, and RAG; resume restores access

## 5. User management service and API

- [ ] 5.1 Create `service/admin/UserManagementService.java`: invite (create Keycloak user with `tenant` attribute = caller's tenant, no group, default role `USER`, trigger set-password email, idempotent by email), list users whose `tenant` attribute is the caller's tenant, assign/revoke `ADMIN`/`USER`, enable/disable, remove (disables the Keycloak account and clears its personal attributes, never deletes it, optionally chaining per-user erasure from `add-audit-and-gdpr-compliance`). Acceptance: task 5.4 passes
- [ ] 5.2 Create `controller/admin/UserAdminController.java` under `/api/v1/admin/users`: restrict to tenant `ADMIN`; derive the tenant from the caller's token, never from the path/body; 403 on any attempt to act on another tenant. Acceptance: task 5.4 passes
- [ ] 5.3 Emit `ADMIN_OPERATION` audit events for invite / role-change / enable-disable / remove. Acceptance: one `audit_log` row per operation in the integration test
- [ ] 5.4 MockMvc + integration tests (Keycloak Testcontainer): invite creates a Keycloak user with `tenant` attribute and `USER`, sends the email, and the invitee's token carries the `tenant` claim and a group claim with no tenant entry; a tenant ADMIN cannot list or mutate another tenant's users (403); role promotion/demotion reflected in Keycloak; remove leaves the Keycloak account in place and disabled, starts erasure only when requested, and no request in the test issues `DELETE` on a Keycloak user

## 6. Documentation and API collection

- [ ] 6.1 Extend `docs/SECURITY.md` (from `add-auth-and-identity`) with tenant and user administration: role model (`PLATFORM_ADMIN` vs tenant `ADMIN`), the `tenant` attribute as the one claim source, SMTP setup, onboarding a tenant, inviting users, suspension and deletion semantics. Acceptance: the section exists and names every new environment variable
- [ ] 6.2 Add Bruno requests under `docs/api/request/AscendAI/` for the tenant and user admin endpoints (with a PLATFORM_ADMIN token variant). Acceptance: `bru run` of the new folder against the local stack returns the expected statuses
- [ ] 6.3 Note the admin endpoints and role model in `apps/ascend-agent/AGENTS.md`. Acceptance: the endpoints appear there
- [ ] 6.4 Run `./gradlew test integrationTest` from `apps/ascend-agent`. Acceptance: both green
