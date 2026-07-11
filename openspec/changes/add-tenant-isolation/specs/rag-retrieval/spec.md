## ADDED Requirements

### Requirement: Mandatory tenant filter on similarity search

`RagRetrievalService` SHALL apply a Spring AI `FilterExpression` of the form `tenant_id == '<currentTenant>'` (built via the `FilterExpressionBuilder` API, not string concatenation of user input) to every `SearchRequest` it issues, using the tenant id resolved from the request's tenant context. The filter SHALL be applied server-side in Qdrant so chunks belonging to other tenants never appear in the candidate list, the score logs, or the retrieved context. When no tenant context is resolved, retrieval SHALL fail with an error and SHALL NOT execute an unfiltered search.

#### Scenario: Cross-tenant retrieval returns zero hits

- **WHEN** tenant `acme` has ingested a document about "Q3 revenue" and a user of tenant `globex` sends a prompt asking about "Q3 revenue"
- **THEN** the similarity search returns zero candidates from `acme`'s chunks
- **AND** the retrieved context is empty unless `globex` has its own matching documents

#### Scenario: Same-tenant retrieval unaffected

- **WHEN** a user of tenant `acme` sends a prompt matching a document ingested by tenant `acme`
- **THEN** the matching chunks are returned and threshold-filtered exactly as before this change

#### Scenario: Retrieval without tenant context fails closed

- **WHEN** `RagRetrievalService.retrieve(...)` is invoked while no tenant is resolved
- **THEN** the call throws an error
- **AND** no `similaritySearch` call reaches the vector store
