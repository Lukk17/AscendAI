# ADR-002: Qdrant as Vector Backend

**Date**: 2026-06-01
**Status**: Accepted
**Deciders**: Łukasz Sarna

---

## Context

mem0ai supports multiple vector store backends: Qdrant, Chroma, Pinecone, Weaviate, and others. AscendMemory needs
to pick one. The choice determines what infrastructure must be provisioned and whether memory storage can share
resources with other parts of the platform.

---

## Decision

Use Qdrant as the only vector backend. The `vector_store.provider` in every mem0ai config dict is hard-coded to
`"qdrant"`. Collections are named by dimension: `ascend_memory_768` and `ascend_memory_1536`.

(`src/service/memory_client.py:76-81`, `src/config/config.py:10-31`)

---

## Alternatives Considered

### Alternative 1: Chroma

- **Pros**: Embedded mode needs no external process in development.
- **Cons**: Not already deployed in the platform. AscendAgent's RAG pipeline uses Qdrant; running two vector stores
  would complicate operations.
- **Why not**: Qdrant is already a platform prerequisite (external to all services). Adding Chroma provides no
  benefit beyond development convenience and adds an operational burden.

### Alternative 2: Pinecone (cloud)

- **Pros**: Managed service, no self-hosted infra.
- **Cons**: Requires a paid account and a Pinecone-specific API key. Introduces a cloud cost dependency. Not
  consistent with the local-first development philosophy of the platform.
- **Why not**: The platform prefers self-hosted infrastructure that can run locally without cost.

---

## Consequences

### Positive

- Memory storage reuses the same Qdrant instance as AscendAgent's RAG pipeline.
- Qdrant is well-supported by mem0ai and by the platform's existing operational runbooks.

### Negative

- AscendMemory cannot be deployed without a running Qdrant instance.
- Multiple services sharing one Qdrant instance creates a blast-radius risk: a Qdrant outage affects both RAG and
  memory.

### Risks

- **Qdrant unavailability**: The warmup probe retries for 5 minutes; if Qdrant does not recover within that window,
  the service stays degraded until restarted.
