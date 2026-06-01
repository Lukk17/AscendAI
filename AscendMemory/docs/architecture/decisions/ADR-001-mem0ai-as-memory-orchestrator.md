# ADR-001: mem0ai as Memory Orchestrator

**Date**: 2026-06-01
**Status**: Accepted
**Deciders**: Łukasz Sarna

---

## Context

AscendMemory must embed user text, store the vectors in Qdrant, deduplicate semantically similar entries, and return
ranked search results. These operations can be assembled from primitives (a Qdrant client, an embedding HTTP call,
custom deduplication logic) or delegated to a higher-level library. The choice determines how much operational code
lives inside this service versus in a dependency.

---

## Decision

Use mem0ai 1.0.3 as the memory orchestration layer. `AscendMemoryClient` wraps `mem0.Memory` and calls
`memory.add()`, `memory.search()`, `memory.delete()`, and `memory.get_all()`. All embedding, Qdrant I/O, and
deduplication is handled by the library.

(`src/service/memory_client.py:52-166`)

---

## Alternatives Considered

### Alternative 1: Direct Qdrant client + httpx embedding calls

- **Pros**: Full control over the embedding pipeline, deduplication strategy, and Qdrant payload schema.
- **Cons**: Requires implementing chunking, semantic deduplication, and the LLM fact-extraction pass from scratch. All
  of that is provided by mem0ai.
- **Why not**: The added implementation cost is not justified for the scope of this service.

### Alternative 2: LangChain memory utilities

- **Pros**: Mature ecosystem, wide model support.
- **Cons**: Heavier dependency graph; the Spring AI LangChain integration is Java-side only. Python-side LangChain
  memory abstractions do not align well with the per-user, per-provider routing needed here.
- **Why not**: mem0ai is purpose-built for this use case; LangChain adds complexity without a clear benefit.

---

## Consequences

### Positive

- Semantic deduplication, fact extraction, and Qdrant payload management are handled by the library.
- Adding a new embedding provider requires only a config dict entry, not code changes.

### Negative

- mem0ai's API changes across minor versions; upgrades require verifying the `results` dict shape and the
  `Memory.from_config` signature.
- The library's `delete_all` has a bug (resets the entire collection). A workaround is required.

### Risks

- **mem0ai breaking change**: Pin to `1.0.3` in `pyproject.toml`. Review changelog before upgrading.
- **json_object unsupported format**: A monkey-patch on `OpenAILLM.generate_response` strips the unsupported
  parameter for local models. If mem0ai restructures the LLM client class, the patch silently stops applying.
