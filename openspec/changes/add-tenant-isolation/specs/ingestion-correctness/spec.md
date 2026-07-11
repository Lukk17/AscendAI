## MODIFIED Requirements

### Requirement: HTTP-upload ingestion is idempotent

When a user re-uploads a document with the same sanitized filename via `POST /api/ingestion/upload`, the agent SHALL replace prior chunks for that source rather than appending duplicates. Deduplication SHALL be scoped to the caller's tenant: the removal of old documents SHALL match both the source identity and the `tenant_id` metadata of the caller's tenant, so a re-upload in one tenant never deletes or replaces chunks belonging to another tenant. Implementation SHALL reuse `documentService.removeOldDocuments(...)` (the same dedup path used by `ManualIngestionService`) extended with the tenant predicate.

#### Scenario: Same document uploaded twice

- **WHEN** a user of tenant `acme` uploads `notes.md` and then uploads a second version of `notes.md`
- **THEN** the Qdrant collection contains chunks corresponding only to the latest upload for tenant `acme`
- **AND** the count of points with `metadata.source == "notes.md"` and `metadata.tenant_id == "acme"` equals the chunk count of the latest version (not the sum)

#### Scenario: Different document, same prefix

- **WHEN** the user uploads `notes.md` and then `notes-v2.md`
- **THEN** chunks for `notes.md` are preserved
- **AND** chunks for `notes-v2.md` are added independently

#### Scenario: Same filename in two tenants coexists

- **WHEN** tenant `acme` uploads `handbook.pdf` and tenant `globex` uploads a different `handbook.pdf`
- **THEN** both documents' chunks exist in the collection, distinguished by `metadata.tenant_id`
- **AND** neither upload overwrites the other's MinIO object (keys `tenant/acme/documents/handbook.pdf` and `tenant/globex/documents/handbook.pdf`)

#### Scenario: Re-upload in one tenant leaves the other tenant intact

- **WHEN** both tenants hold `handbook.pdf` and tenant `acme` re-uploads a new version
- **THEN** only points with `metadata.tenant_id == "acme"` for that source are replaced
- **AND** tenant `globex`'s points for `handbook.pdf` are unchanged
