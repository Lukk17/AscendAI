# ADR-003: Semantic Memory via REST Instead of MCP

## Status

Accepted

## Context

AscendMemory provides both a REST API and an MCP server. We need to decide how the AscendAgent should interact with it.

The existing `SemanticMemoryClient` uses direct REST calls via `RestClient` to store and retrieve user context. The MCP layer for AscendMemory has known stability issues.

## Decision

Keep `SemanticMemoryClient` as a direct REST client (`RestClient` → `http://localhost:7020`). Do not register AscendMemory as an MCP tool provider.

## Consequences

- **Positive**: Stable, tested integration path
- **Positive**: `SemanticMemoryClient` can handle persistence-specific logic (save/update/delete) that MCP tool semantics are not designed for
- **Positive**: No dependency on MCP server stability for memory operations
- **Negative**: Memory is not available as an LLM-invocable tool — the AscendAgent must explicitly call it during context assembly
- **Note**: The default configuration (`lmstudio` embedding provider) requires LM Studio running locally on port 1234. Configuring `openai` or `gemini` as the embedding provider eliminates this dependency (see ADR-006).
