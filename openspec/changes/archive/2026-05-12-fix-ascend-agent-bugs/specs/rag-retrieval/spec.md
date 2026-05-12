## ADDED Requirements

### Requirement: Similarity threshold is applied at vector-search time

`RagRetrievalService` SHALL pass `app.rag.similarity-threshold` to the underlying `SearchRequest` so that Qdrant filters results server-side. The service SHALL NOT use `SearchRequest.SIMILARITY_THRESHOLD_ACCEPT_ALL` and SHALL NOT drop the entire result set merely because the top-ranked hit fails the threshold.

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
