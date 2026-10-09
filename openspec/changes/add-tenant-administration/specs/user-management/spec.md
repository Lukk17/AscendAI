## ADDED Requirements

### Requirement: Tenant-scoped user management API restricted to tenant admins

ascend-ai-agent SHALL expose `/api/v1/admin/users` supporting invite, list, role assignment/revocation, enable/disable, and remove, restricted to the tenant `ADMIN` role. The operated tenant SHALL be derived from the caller's authenticated token, never from a path or body parameter. Any attempt by a tenant admin to read or mutate a user outside their own tenant SHALL return HTTP 403, and a caller without `ADMIN` SHALL receive HTTP 403.

#### Scenario: Non-admin refused

- **WHEN** a caller with only the `USER` role sends `GET /api/v1/admin/users`
- **THEN** the response is HTTP 403

#### Scenario: Cross-tenant access refused

- **WHEN** a tenant `ADMIN` of tenant `acme` attempts to list or modify users of tenant `globex`
- **THEN** the response is HTTP 403 and no data for `globex` is returned or changed

### Requirement: Inviting a user provisions a Keycloak user and sends a set-password email

An invite SHALL create a Keycloak user whose `tenant` attribute is the caller's tenant (taken from the caller's resolved tenant context, never from the request), with the default role `USER` and no group, and SHALL trigger Keycloak's built-in set-password / verify-email action email, sent through the realm SMTP settings, so the invitee sets their own credentials. ascend-ai-agent SHALL never receive or store the invitee's password. The invited user's token, once they log in, SHALL carry the caller's tenant as its `tenant` claim.

#### Scenario: Invite creates a least-privilege user and emails them

- **WHEN** a tenant `ADMIN` of `acme` invites `newuser@acme.example`
- **THEN** a Keycloak user is created with attribute `tenant` = `acme`, role `USER` and no other role, and no group
- **AND** a set-password action email is triggered for that address

#### Scenario: Invited user's token carries the tenant

- **WHEN** the invited user completes set-password and logs in
- **THEN** their token's `tenant` claim equals `acme`

### Requirement: Role assignment and account state are managed per tenant

A tenant `ADMIN` SHALL be able to promote a user to `ADMIN`, demote back to `USER`, and enable or disable an account, all scoped to their tenant, with each change reflected in Keycloak. Disabling and enabling SHALL be the routes `POST /api/v1/admin/users/{userId}/disable` and `POST /api/v1/admin/users/{userId}/enable`, where `{userId}` is the Keycloak user id, and each SHALL change only that user's Keycloak `enabled` flag. Removing a user SHALL disable the Keycloak account and clear its personal attributes, and SHALL NOT delete the account. Chaining the per-user erasure job on removal is added by `add-audit-and-gdpr-compliance`, which lands later. Every invite, role change, enable/disable, and removal SHALL record one event through `AuditEventPort`.

#### Scenario: Promotion reflected in Keycloak

- **WHEN** a tenant `ADMIN` promotes a user to `ADMIN`
- **THEN** the user holds the `ADMIN` realm role in Keycloak
- **AND** one event naming the role change with actor and subject reaches `AuditEventPort`

#### Scenario: Disable and enable through their own routes

- **WHEN** a tenant `ADMIN` of `acme` sends `POST /api/v1/admin/users/{userId}/disable` for a user of `acme`
- **THEN** the response is HTTP 200, the user's Keycloak account is disabled and the user cannot obtain a token
- **AND** after `POST /api/v1/admin/users/{userId}/enable` for the same user the account is enabled and the user can obtain a token again

#### Scenario: Disable of another tenant's user refused

- **WHEN** a tenant `ADMIN` of `acme` sends `POST /api/v1/admin/users/{userId}/disable` for a user of `globex`
- **THEN** the response is HTTP 403
- **AND** the `globex` user's account stays enabled

#### Scenario: Remove keeps the account

- **WHEN** a tenant `ADMIN` removes a user
- **THEN** the Keycloak account is disabled and still exists
- **AND** its personal attributes are cleared
