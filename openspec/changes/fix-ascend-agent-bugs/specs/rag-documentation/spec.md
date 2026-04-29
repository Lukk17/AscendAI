## ADDED Requirements

### Requirement: README documents the RAG ingestion lifecycle

`AscendAgent/README.md` SHALL include a section titled "RAG ingestion lifecycle" that explains, in order: (1) how to put files into the `knowledge-base` MinIO bucket (folders `obsidian/` for `.md`, `documents/` for PDFs/DOCX); (2) that `app.ingestion.auto.enabled` defaults to `false` and the user must call `POST /api/ingestion/run` to index files dropped into MinIO; (3) how to switch on the auto-poller (`app.ingestion.auto.enabled: true`) and the trade-offs; (4) the embedding-dimension/collection coupling (`ascendai-{dims}`) and what to do when changing embedding providers (re-index required); (5) the distinction between RAG corpus, semantic memory, and short-term chat history.

#### Scenario: Section present and discoverable

- **WHEN** a developer reads `AscendAgent/README.md`
- **THEN** they find a section heading equal to or containing `RAG ingestion lifecycle`
- **AND** that section addresses each of the five points above

#### Scenario: Manual-vs-auto trigger explained

- **WHEN** a user wants to know "why doesn't my freshly-uploaded `.md` show up in answers?"
- **THEN** the README explicitly states that `POST /api/ingestion/run` is required unless auto-ingestion is enabled

### Requirement: ADR documents the auto-ingestion default

`AscendAgent/docs/architecture/decisions/` SHALL contain an ADR explaining why `app.ingestion.auto.enabled` defaults to `false`, listing the considered alternatives and the trade-offs (cost, accidental indexing, predictable startup).

#### Scenario: ADR present

- **WHEN** the architecture decisions directory is listed
- **THEN** it contains an ADR file whose title references "auto-ingestion default" or similar
- **AND** the ADR contains "Context", "Decision", "Consequences" sections per the existing ADR style
