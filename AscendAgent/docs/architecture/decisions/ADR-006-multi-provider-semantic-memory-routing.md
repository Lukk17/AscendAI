# ADR-006: Multi-Provider Semantic Memory Routing

## Status

Accepted

## Context

The AscendAgent routes chat requests to multiple AI providers (lmstudio, openai, gemini, anthropic, minimax). Each provider may use a different embedding model with a different vector dimension:

- `lmstudio` → `text-embedding-nomic-embed-text-v2-moe` → 768 dims
- `gemini` → `gemini-embedding-001` → 768 dims
- `openai` → `text-embedding-3-small` → 1536 dims
- `anthropic` → no native embeddings → falls back to `openai`
- `minimax` → no native embeddings → falls back to `openai`

Before this change, `SemanticMemoryClient` always called `ascend-memory` without specifying a provider. AscendMemory used a single hardcoded Qdrant collection (`ascend_memory`) with the lmstudio 768-dim model. When the active embedding provider was `openai` (1536 dims), inserting or searching in the 768-dim collection caused dimension mismatches or returned irrelevant results.

Additionally, `SemanticMemoryExtractor` used a provider-configured `memoryExtractionModel` regardless of what model the user had actually requested — causing failures when users sent requests with vision-only models (e.g., `qwen3-vl-4b`) that cannot process text-only extraction prompts.

## Decision

### 1. Per-provider Qdrant collections in AscendMemory

Replace the single `ascend_memory` collection with per-dimension collections:

| Provider | Dims | Qdrant Collection |
|---|---|---|
| `lmstudio` | 768 | `ascend_memory_768` |
| `gemini` | 768 | `ascend_memory_768` |
| `openai` | 1536 | `ascend_memory_1536` |

Providers sharing the same dimension share the same collection. `AscendMemoryClient` is instantiated per-provider and cached as `Dict[str, AscendMemoryClient]`.

### 2. Provider parameter propagated through the entire memory chain

The AscendAgent's `embeddingProvider` (resolved from the request or from `AiProviderProperties.defaultEmbedding`) is forwarded as:
- A `provider` query param in `GET /api/v1/memory/search`
- A `provider` body field in `POST /api/v1/memory/insert`

This ensures search and insert always target the same Qdrant collection.

### 3. Extraction model resolves user's requested model first

`SemanticMemoryExtractor.resolveExtractionModel()` now prioritizes the user's requested `model` over the provider-configured `memoryExtractionModel`. This prevents using an incompatible model for extraction when the user has selected a specialized model (e.g., vision-only).

### 4. Fallback JSON extraction for thinking models

When a thinking model (e.g., MiniMax-M2.7) returns reasoning text with a JSON array embedded at the end, `parseJsonArray()` falls back to `extractEmbeddedJsonArray()` which uses `lastIndexOf('[')` / `lastIndexOf(']')` to extract and parse the final array from the response text.

## Consequences

- **Positive**: Dimension-safe memory — searches and inserts always target a collection with the correct vector size
- **Positive**: No silent data loss when switching between 768-dim and 1536-dim providers
- **Positive**: Memory extraction works with vision models and thinking models
- **Positive**: `MEM0_DEFAULT_PROVIDER` env var in AscendMemory controls the fallback when no provider is specified, making it easy to switch defaults without code changes
- **Negative**: Memories are collection-scoped — a user's memories stored via `lmstudio` are not visible when searching with `openai` (different Qdrant collections). Cross-provider memory queries are not supported.
- **Negative**: Switching a deployment's default embedding provider requires re-inserting existing memories into the new collection.