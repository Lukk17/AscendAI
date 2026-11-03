## MODIFIED Requirements

### Requirement: Similarity threshold is applied at vector-search time

`RagRetrievalService` SHALL pass a similarity threshold of `0.0` to the `SearchRequest`, so every candidate the mandatory tenant and access list filter permits comes back with its score, and SHALL apply `app.rag.similarity-threshold` in Java to that permitted candidate list, logging the scores of the near misses. The service SHALL NOT drop the entire result set merely because the top-ranked hit fails the threshold. Owner decision 65.22 of 2026-10-04: knowledge search keeps the Java score filter, and this text replaces the earlier statement that Qdrant filters by the threshold server-side, which the code never did.

#### Scenario: All hits above threshold are returned

- **WHEN** Qdrant has 5 hits with scores `[0.91, 0.85, 0.80, 0.74, 0.60]` and the threshold is `0.75`
- **THEN** the retrieved context contains 3 hits (`0.91`, `0.85`, `0.80`)
- **AND** does NOT contain the hits with scores `0.74` and `0.60`

#### Scenario: Top hit below threshold does NOT drop other hits

- **WHEN** Qdrant returns hits `[0.74, 0.80, 0.85]` (top hit fails threshold but others pass)
- **THEN** the retrieved context contains 2 hits (`0.80`, `0.85`)
- **AND** the assembler logs `RAG Context Injected: YES` (not NO)

#### Scenario: All hits below threshold

- **WHEN** all hits returned by Qdrant are below the threshold
- **THEN** the retrieved context is empty
- **AND** the assembler logs `RAG Context Injected: NO`

#### Scenario: The search request carries no server-side threshold

- **WHEN** a prompt is served with RAG enabled and `app.rag.similarity-threshold` is `0.75`
- **THEN** the `SearchRequest` handed to the vector store has a similarity threshold of `0.0`
- **AND** the threshold of `0.75` is applied in Java to the permitted candidates

## ADDED Requirements

### Requirement: Mandatory tenant and access-list filter on similarity search

`RagRetrievalService` SHALL apply one Spring AI `FilterExpression` to every `SearchRequest` it issues, composed of two conjuncts:

```text
tenant_id == '<currentTenant>' AND acl IN <principalSet>
```

`<currentTenant>` is the tenant id resolved from the request's tenant context. `<principalSet>` is the set of group principals resolved for the caller by `add-auth-and-identity`. Both conjuncts SHALL be built through the `FilterExpressionBuilder` API and never by string concatenation, and both SHALL be present on every request: a search filtered by tenant alone is not compliant with this requirement. The composed expression SHALL be applied server-side in Qdrant, so a chunk the caller may not read is never scored, never counted against `topK`, never written to the score log, and never reaches the model.

The access conjunct is a set intersection, not an equality: a chunk is a candidate when its `acl` payload array contains at least one principal the caller holds. Because that is the only test, a chunk whose `acl` is absent or empty intersects nothing and is retrieved by nobody. Deny-by-default SHALL be the natural result of this expression and SHALL NOT be implemented as a special case anywhere in the retrieval path. A caller's roles (for example `ADMIN`) SHALL NOT widen the expression, because a role is not a principal.

When either the tenant context or the principal set is unresolved, retrieval SHALL fail with an error and SHALL NOT execute a search that is unfiltered on either axis.

#### Scenario: Cross-tenant retrieval returns zero hits

- **WHEN** tenant `acme` has ingested a document about "Q3 revenue" and a user of tenant `globex` sends a prompt asking about "Q3 revenue"
- **THEN** the similarity search returns zero candidates from `acme`'s chunks
- **AND** the retrieved context is empty unless `globex` has its own matching documents

#### Scenario: Within-tenant retrieval refused for a caller outside the access list

- **WHEN** a chunk of tenant `acme` carries `acl` of `["local:group:finance"]` and a user of tenant `acme` whose principal set is `["tenant:everyone:acme", "local:group:support"]` sends a prompt matching it
- **THEN** the similarity search returns zero candidates from that chunk
- **AND** a user of tenant `acme` holding `local:group:finance` retrieves the same chunk for the same prompt

#### Scenario: Permitted chunk below the unfiltered cut is still returned

- **GIVEN** ten chunks of tenant `acme` match a query, `app.rag.top-k` is 5, and the caller's principal set intersects the `acl` of exactly one of them, the chunk ranked eighth by similarity
- **WHEN** the caller sends that query
- **THEN** the retrieved context contains the chunk ranked eighth
- **AND** the answer is grounded in that chunk rather than in an empty context

#### Scenario: Same-tenant, permitted retrieval unaffected

- **WHEN** a user of tenant `acme` sends a prompt matching a document ingested by tenant `acme` whose `acl` intersects the caller's principal set
- **THEN** the matching chunks are returned and threshold-filtered in Java exactly as before this change

#### Scenario: Chunk with no access list is retrieved by nobody

- **WHEN** a chunk exists with no `acl` payload field, or with an empty one, and a user of its own tenant sends a prompt that matches it on similarity
- **THEN** the similarity search returns zero candidates from that chunk
- **AND** this holds for every caller in that tenant, whatever principals they hold

#### Scenario: An administrative role does not widen the filter

- **WHEN** a caller holding role `ADMIN` sends a prompt matching a chunk whose `acl` does not intersect that caller's principal set
- **THEN** the similarity search returns zero candidates from that chunk
- **AND** the composed filter expression is identical to the one built for a caller holding no roles with the same principal set

#### Scenario: Retrieval without tenant context fails closed

- **WHEN** `RagRetrievalService.retrieve(...)` is invoked while no tenant is resolved
- **THEN** the call throws an error
- **AND** no `similaritySearch` call reaches the vector store

#### Scenario: Retrieval without a principal set fails closed

- **WHEN** `RagRetrievalService.retrieve(...)` is invoked while the tenant is resolved but no principal set is resolved for the caller
- **THEN** the call throws an error
- **AND** no `similaritySearch` call reaches the vector store
- **AND** the failure is not degraded into a search filtered by tenant alone

### Requirement: Exactly one method issues the similarity search

Production code SHALL contain exactly one method that calls `VectorStore.similaritySearch(...)`, `TenantFilteredVectorSearch.search`, and that method SHALL be the one that composes the filter expression described above. `RagRetrievalService.performSimilaritySearch` SHALL search through it with the target `KNOWLEDGE`, and the capability index search of `add-agent-skills` (`CapabilityIndex.search`) SHALL search through it with the target `CAPABILITIES`, whose mandatory filter admits only global entries and entries of the caller's tenant and which SHALL fail closed when no tenant is resolved. The method SHALL choose the vector store from the target, so a caller cannot pair a store with a weaker filter. No other production class SHALL call `similaritySearch`, directly or through a wrapper. This SHALL be enforced by an architecture test that fails the build when a second call site appears, so the filter cannot be bypassed by a future code path that builds its own `SearchRequest`.

That method SHALL accept an optional narrowing conjunct from its caller, built through `FilterExpressionBuilder` and always joined with AND to the mandatory tenant and access-list filter. The narrowing conjunct SHALL NOT replace the mandatory filter or remove either of its two conjuncts, and the architecture test SHALL stay unchanged.

#### Scenario: A narrowing conjunct is joined, never substituted

- **WHEN** `add-obsidian-vault` searches one vault's notes with the narrowing conjunct `connector_id == <vault's connector id>`
- **THEN** the `SearchRequest` carries the `tenant_id` equality, the `acl` set-intersection and the `connector_id` conjunct, joined with AND
- **AND** no chunk outside the caller's tenant and access list is returned

#### Scenario: A second call site fails the build

- **WHEN** a production class other than `TenantFilteredVectorSearch` calls `VectorStore.similaritySearch(...)`
- **THEN** the architecture test fails
- **AND** the failure names the offending class

#### Scenario: Capability index search stays in the caller's tenant

- **WHEN** a caller of tenant `globex` runs `skill_search` while tenant `acme` has a skill matching the query and a global skill also matches
- **THEN** the search goes through `TenantFilteredVectorSearch.search` with the target `CAPABILITIES`
- **AND** the result holds the global skill and no entry of tenant `acme`

#### Scenario: Every issued search carries both conjuncts

- **WHEN** any prompt is served with RAG enabled
- **THEN** the `SearchRequest` handed to the vector store carries a filter expression containing both the `tenant_id` equality and the `acl` set-intersection
- **AND** no `SearchRequest` is issued whose filter expression is absent or carries only one of the two
