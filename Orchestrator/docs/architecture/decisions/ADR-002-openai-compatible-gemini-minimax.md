# ADR-002: OpenAI-Compatible Endpoints for Gemini and MiniMax

## Status

Accepted

## Context

Both Google Gemini (via AI Studio) and MiniMax expose OpenAI-compatible API endpoints. We need to decide whether to use their native SDKs/starters or leverage the existing `OpenAiChatModel` from Spring AI.

Alternatives considered:
1. **Native SDK per provider** — separate Spring AI starters or custom REST clients
2. **OpenAI-compatible endpoints** — reuse `OpenAiChatModel` with different base URLs

## Decision

Use OpenAI-compatible endpoints for Gemini (`https://generativelanguage.googleapis.com/v1beta/openai/`) and MiniMax (`https://api.minimax.io/v1`). Both are configured as `type: openai` in `app.ai.providers`, so the `ChatModelResolver` builds them identically to OpenAI using `OpenAiChatModel` with a custom base URL.

## Consequences

- **Positive**: No additional dependencies — both providers reuse the existing `spring-ai-starter-model-openai`
- **Positive**: Uniform configuration: all OpenAI-compatible providers share the same `ProviderConfig` schema
- **Positive**: Gemini API key from [AI Studio](https://aistudio.google.com/) works directly — no Vertex AI setup needed
- **Negative**: If providers diverge from OpenAI API compatibility, may need custom handling
- **Negative**: Provider-specific features (e.g., Gemini grounding) are not accessible through the OpenAI-compatible layer
