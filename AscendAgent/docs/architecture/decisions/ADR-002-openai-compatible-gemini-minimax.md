# ADR-002: Provider API Compatibility Strategy

## Status

Accepted

## Context

AI providers expose different API formats. We need to decide which SDK/protocol type to use for each provider within the `ChatModelResolver` framework.

Alternatives considered:
1. **Native SDK per provider** — separate Spring AI starters or custom REST clients
2. **OpenAI-compatible endpoints** — reuse `OpenAiChatModel` with different base URLs
3. **Anthropic-compatible endpoints** — reuse `AnthropicChatModel` with different base URLs

## Decision

Each provider is configured with a `type` that determines which Spring AI model implementation is used:

| Provider | `type` | Base URL | Rationale |
|---|---|---|---|
| `lmstudio` | `anthropic` | `http://127.0.0.1:1234` | LM Studio supports the Anthropic Messages API format |
| `openai` | `openai` | `https://api.openai.com` | Native OpenAI API |
| `gemini` | `openai` | `https://generativelanguage.googleapis.com/v1beta/openai/` | Google provides an OpenAI-compatible endpoint; no Anthropic-compatible option available |
| `anthropic` | `anthropic` | `https://api.anthropic.com` | Native Anthropic API |
| `minimax` | `anthropic` | `https://api.minimax.io/anthropic` | MiniMax provides an Anthropic-compatible endpoint |

The `ChatModelResolver` builds either `OpenAiChatModel` or `AnthropicChatModel` based on the `type` field, with provider-specific base URLs and API keys.

## Consequences

- **Positive**: Only two dependencies needed — `spring-ai-starter-model-openai` and `spring-ai-starter-model-anthropic`
- **Positive**: Uniform configuration: all providers share the same `ProviderConfig` schema regardless of type
- **Positive**: Anthropic-type providers gain native support for thinking models (extended thinking / chain-of-thought)
- **Negative**: Providers using `type: anthropic` may return multi-block thinking responses; handled by `ChatResponseContentResolver` (see [ADR-005](ADR-005-thinking-model-response-resolution.md))
- **Negative**: Provider-specific features (e.g., Gemini grounding) are not accessible through compatibility layers
