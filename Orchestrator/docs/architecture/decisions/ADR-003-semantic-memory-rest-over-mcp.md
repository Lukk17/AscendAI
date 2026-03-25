# ADR-003: Semantic Memory via REST Instead of MCP

## Status

Accepted

## Context

AscendMemory provides both a REST API and an MCP server. We need to decide how the Orchestrator should interact with it.

The existing `SemanticMemoryClient` uses direct REST calls via `RestClient` to store and retrieve user context. The MCP layer for AscendMemory has known stability issues.

## Decision

Keep `SemanticMemoryClient` as a direct REST client (`RestClient` → `http://localhost:7020`). Do not register AscendMemory as an MCP tool provider.

## Consequences

- **Positive**: Stable, tested integration path
- **Positive**: `SemanticMemoryClient` can handle persistence-specific logic (save/update/delete) that MCP tool semantics are not designed for
- **Positive**: No dependency on MCP server stability for memory operations
- **Negative**: Memory is not available as an LLM-invocable tool — the Orchestrator must explicitly call it during context assembly
- **Negative**: `ascend-memory` requires **LM Studio** running locally on port 1234 to generate vector embeddings. If unavailable, REST calls fail with 500 Internal Server Errors.
