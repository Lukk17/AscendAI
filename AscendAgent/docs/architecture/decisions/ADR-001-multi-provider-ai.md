# ADR-001: Multi-Provider AI with Per-Request Selection

## Status

Accepted

## Context

The AscendAgent originally used a single `ChatClient` bean wired to LM Studio. To support multiple AI providers (OpenAI, Gemini, Anthropic, MiniMax) without restarting the application, we need a mechanism for per-request provider and model selection.

Alternatives considered:
1. **Spring Profiles** — one profile per provider, requires restart to switch
2. **Multiple `ChatClient` beans** — N named beans, selected via qualifier
3. **`ChatModelResolver` with per-request resolution** — dynamic provider map

## Decision

Implement a `ChatModelResolver` that initializes a `Map<String, ChatModel>` from YAML configuration at startup. Each request may include optional `provider` and `model` parameters. The resolver falls back to `app.ai.default-provider` when no provider is specified. The `ChatExecutor` builds a `ChatClient` per-request from the resolved `ChatModel`.

## Consequences

- **Positive**: Provider switching without restart, per-request model override, easy to add new providers via YAML
- **Positive**: No Spring profiles needed for AI provider selection
- **Negative**: `ChatClient` is built per-request (minor performance overhead)
- **Negative**: All enabled providers are initialized at startup even if unused
