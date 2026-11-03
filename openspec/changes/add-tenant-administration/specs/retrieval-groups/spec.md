## ADDED Requirements

### Requirement: Tenant administrators manage retrieval groups

This is company-only work, built after the personal version (owner decision 65.3 of 2026-10-04). ascend-ai-agent SHALL expose `/api/v1/admin/groups` for the tenant `ADMIN` to create, list, read and delete the retrieval groups of the caller's tenant and to add and remove members. A retrieval group SHALL be a Keycloak realm group named `<tenantId>.<name>`, created through the Keycloak Admin API, so a member's token carries it and the member holds `local:group:<tenantId>.<name>`. `<name>` SHALL be at most 51 characters, so that principal stays within the 128-character principal cap of `add-auth-and-identity` with a tenant id of 64 characters, and a longer name SHALL be refused with 400 `validation`. The tenant SHALL come from the caller's token, never from the path or body. A caller without `ADMIN` SHALL receive 403, and a group or user of another tenant SHALL answer 404.

#### Scenario: Group created and a member added

- **WHEN** a tenant `ADMIN` of `acme` creates the group `finance` and adds a user of `acme` to it
- **THEN** Keycloak holds the realm group `acme.finance` with that member
- **AND** the member's next token carries `acme.finance` in the group claim

#### Scenario: Another tenant's group is not reachable

- **WHEN** a tenant `ADMIN` of `globex` reads or changes the members of `finance` of `acme`
- **THEN** the response is 404 and nothing changes

#### Scenario: Group in use cannot be deleted

- **WHEN** a tenant `ADMIN` deletes a group that the access list of a document still names
- **THEN** the response is 409 with `code` `access_group_in_use` and the group stays

#### Scenario: Non-admin refused

- **WHEN** a caller with only `USER` sends `POST /api/v1/admin/groups`
- **THEN** the response is 403
