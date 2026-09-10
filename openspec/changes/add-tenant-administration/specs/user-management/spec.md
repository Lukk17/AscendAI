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

An invite SHALL create a Keycloak user in the caller's tenant group with the default role `USER`, and SHALL trigger Keycloak's built-in set-password / verify-email action email so the invitee sets their own credentials. ascend-ai-agent SHALL never receive or store the invitee's password. The invited user's token, once they log in, SHALL carry the caller's tenant as its `tenant` claim.

#### Scenario: Invite creates a least-privilege user and emails them

- **WHEN** a tenant `ADMIN` of `acme` invites `newuser@acme.example`
- **THEN** a Keycloak user is created in group `/tenants/acme` with role `USER` and no other role
- **AND** a set-password action email is triggered for that address

#### Scenario: Invited user's token carries the tenant

- **WHEN** the invited user completes set-password and logs in
- **THEN** their token's `tenant` claim equals `acme`

### Requirement: Role assignment and account state are managed per tenant

A tenant `ADMIN` SHALL be able to promote a user to `ADMIN`, demote back to `USER`, and enable or disable an account, all scoped to their tenant, with each change reflected in Keycloak. Removing a user SHALL disable or delete the Keycloak account, and MAY chain the per-user erasure job (`add-audit-and-gdpr-compliance`) when the caller requests data removal. Every invite, role change, enable/disable, and removal SHALL emit an audit event.

#### Scenario: Promotion reflected in Keycloak

- **WHEN** a tenant `ADMIN` promotes a user to `ADMIN`
- **THEN** the user holds the `ADMIN` realm role in Keycloak
- **AND** an audit row records the role change with actor and subject

#### Scenario: Remove with data erasure

- **WHEN** a tenant `ADMIN` removes a user requesting data removal
- **THEN** the Keycloak account is disabled or deleted
- **AND** a per-user erasure job is started for that user
