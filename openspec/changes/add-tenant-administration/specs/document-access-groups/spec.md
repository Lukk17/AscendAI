## ADDED Requirements

### Requirement: A tenant administrator narrows who finds an uploaded document

This is company-only work (owner decision 65.3 of 2026-10-04). ascend-ai-agent SHALL expose `PUT /api/v1/documents/{id}/access` with the body `{"everyone": <boolean>, "groups": [<group name>]}`, restricted to the tenant `ADMIN` of the document's tenant. It SHALL store the list on the document's registry row, rewrite `acl` on every chunk of the document to `tenant:everyone:{tenantId}` when `everyone` is true plus `local:group:<tenantId>.<name>` for each group, set `acl_source` to `admin-assignment` and set `acl_version` to the hash of the new list that `add-tenant-isolation` defines. A later reindex SHALL keep the stored list. It SHALL refuse an empty list (`everyone` false and no group) with 400 `validation`, a group that does not exist in the tenant with 400 `unknown_access_group`, a connector document with 409 `document_access_managed_by_connector`, and a document of another tenant with 404. `GET /api/v1/documents/{id}` SHALL return the current `access`.

#### Scenario: Document narrowed to one group

- **WHEN** a tenant `ADMIN` of `acme` sends `PUT /api/v1/documents/{id}/access` with `{"everyone": false, "groups": ["finance"]}` for an uploaded document
- **THEN** the response is 200 with the new access
- **AND** a user of `acme` in the group `finance` finds the document in knowledge search, while a user of `acme` outside it does not

#### Scenario: Reindex keeps the narrowed list

- **WHEN** a narrowed document is reindexed
- **THEN** every new chunk carries the narrowed `acl` and not `tenant:everyone:acme`

#### Scenario: Empty access list refused

- **WHEN** the body is `{"everyone": false, "groups": []}`
- **THEN** the response is 400 with `code` `validation` and the chunks are unchanged

#### Scenario: Non-admin refused

- **WHEN** a caller with only `USER` sends the request
- **THEN** the response is 403 and the chunks are unchanged

#### Scenario: Narrowed access hides a document from a user outside the group

- **WHEN** the access groups spec narrows an indexed canary to the group `finance` as a tenant `ADMIN`
- **THEN** a prompt with `attachSources=true` by a `finance` member lists the document, the same prompt by a user outside the group does not, and the chunks carry the narrowed `acl` after a reindex
