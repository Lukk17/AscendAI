# ADR-005: Thinking Model Response Resolution

## Status

Accepted

## Context

Providers configured with `type: anthropic` (LM Studio, Anthropic, MiniMax) may use thinking models that return multi-block responses. The Spring AI `AnthropicChatModel` maps these blocks to multiple `Generation` objects in the `ChatResponse`:

1. **First generation(s)**: Internal chain-of-thought reasoning (thinking text)
2. **Last generation**: The actual answer

The standard `chatResponse.getResult()` returns the **first** `Generation`, which for thinking models contains the reasoning text rather than the answer. This caused two bugs:
- `ChatExecutor` returned the thinking text to the user instead of the actual answer.
- `SemanticMemoryExtractor` received thinking text instead of the expected JSON array, causing fact extraction to fail silently (JSON parse error → empty list → no facts inserted into AscendMemory).

## Decision

Introduce `ChatResponseContentResolver`, a shared `@Service` that resolves `ChatResponse` content by iterating `getResults()` in reverse order and returning the first non-blank text found (i.e., the last generation with content).

Both `ChatExecutor` and `SemanticMemoryExtractor` use this resolver instead of direct `getResult().getOutput().getText()` or `call().content()`.

## Consequences

- **Positive**: Backward-compatible with OpenAI-type (single generation) — last = first, identical behavior
- **Positive**: Automatically handles any future thinking-model additions without code changes
- **Positive**: Follows DRY — single extraction point used by all `ChatResponse` consumers
- **Negative**: Assumes the actual answer is always the last non-blank generation, which holds for all currently supported Anthropic-type providers
