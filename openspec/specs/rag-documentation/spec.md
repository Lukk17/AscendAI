# rag-documentation Specification

## Purpose

The RAG pipeline carries documentation obligations, and this capability states them as checkable requirements rather than leaving them to prose that drifts. An operator has to be told how files reach the knowledge-base bucket, that auto-ingestion is off by default and indexing is triggered by hand, how to turn the poller on and what it costs, how the embedding dimension is coupled to the collection name and what a provider switch therefore requires, and how the RAG corpus differs from semantic memory and from short-term chat history. The choice to default auto-ingestion to off is recorded as an architecture decision record.

## Requirements
### Requirement: README documents the RAG ingestion lifecycle

`apps/ascend-agent/README.md` SHALL include a section titled "RAG ingestion lifecycle" that explains, in order: (1) how to put files into the `knowledge-base` bucket on the S3-compatible object store (folders `obsidian/` for `.md`, `documents/` for PDFs/DOCX), naming Floci as the local implementation and the Floci UI on port `9071` as the way to browse it; (2) that `app.ingestion.auto.enabled` defaults to `false` and the user must call `POST /api/ingestion/run` to index files dropped into the bucket; (3) how to switch on the auto-poller (`app.ingestion.auto.enabled: true`) and the trade-offs; (4) the embedding-dimension/collection coupling (`ascendai-{dims}`) and what to do when changing embedding providers (re-index required); (5) the distinction between RAG corpus, semantic memory, and short-term chat history.

The section SHALL NOT instruct the reader to install or use the `mc` client, and SHALL NOT reference a container named `minio`.

#### Scenario: Section present and discoverable

- **WHEN** a developer reads `apps/ascend-agent/README.md`
- **THEN** they find a section heading equal to or containing `RAG ingestion lifecycle`
- **AND** that section addresses each of the five points above

#### Scenario: Manual-vs-auto trigger explained

- **WHEN** a user wants to know "why doesn't my freshly-uploaded `.md` show up in answers?"
- **THEN** the README explicitly states that `POST /api/ingestion/run` is required unless auto-ingestion is enabled

#### Scenario: Upload instructions work on the current stack

- **WHEN** a developer follows the upload instructions verbatim against a running Floci on port 9070
- **THEN** the file lands in the `knowledge-base` bucket under the documented prefix
- **AND** a subsequent `POST /api/ingestion/run` indexes it
### Requirement: ADR documents the auto-ingestion default

`apps/ascend-agent/docs/architecture/decisions/` SHALL contain an ADR explaining why `app.ingestion.auto.enabled` defaults to `false`, listing the considered alternatives and the trade-offs (cost, accidental indexing, predictable startup).

#### Scenario: ADR present

- **WHEN** the architecture decisions directory is listed
- **THEN** it contains an ADR file whose title references "auto-ingestion default" or similar
- **AND** the ADR contains "Context", "Decision", "Consequences" sections per the existing ADR style

