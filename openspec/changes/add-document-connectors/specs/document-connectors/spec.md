## ADDED Requirements

### Requirement: Connector-landed documents are visible to the whole owning company

Once `add-tenant-isolation` stamps access lists, every chunk produced from a document that any connector type of `add-connector-framework` landed SHALL carry an access list of exactly `["tenant:everyone:{tenantId}"]` with `acl_source` of `tenant-default`, a matching `acl_version`, and `acl_synced_at` set at ingestion, written by the same ingestion producer default that `add-tenant-isolation` applies to a document with no source-captured list. A connector SHALL NOT compose, assemble, or supply an access list of its own, and SHALL NOT set `acl_source` to a connector name, because no part of that list was decided by the source.

Per-document permissions captured from the source are out of scope for this version. A connector SHALL NOT read item or container permissions from the source, and SHALL NOT request an application permission that exists only to resolve them.

#### Scenario: Synced document is retrievable by a caller in the owning company

- **WHEN** a connector of tenant `acme` lands a document and the ingestion pipeline indexes it
- **THEN** every chunk of that document carries `acl` equal to `["tenant:everyone:acme"]` and `acl_source` of `tenant-default`
- **AND** an authenticated caller of tenant `acme`, whose principal set contains `tenant:everyone:acme`, retrieves that document for a matching prompt

#### Scenario: Synced document is not retrievable across tenants

- **WHEN** a caller of tenant `globex` sends a prompt matching a document synced by a connector of tenant `acme`
- **THEN** no chunk of that document is returned

#### Scenario: The connector produces no access list

- **WHEN** the connector framework and the SharePoint connector are inspected for access-list construction
- **THEN** neither builds a principal string, calls a principal factory, nor sets any of the four access-list metadata keys
- **AND** the only producer of `tenant:everyone:{tenantId}` remains the helper owned by `add-tenant-isolation`
