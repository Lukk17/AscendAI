## MODIFIED Requirements

### Requirement: Static prefix is cached per provider via the strategy resolver

ascend-ai-agent SHALL apply a provider-specific prompt-cache strategy (resolved by **provider name**) to the static prefix of every chat request (the `app.system-prompt` SystemMessage) and every memory-extraction request (the `SemanticMemoryExtractor.EXTRACTOR_INSTRUCTION` prefix). The strategy SHALL use Spring AI's native `AnthropicChatOptions.cacheOptions(...)` with `AnthropicCacheStrategy.SYSTEM_ONLY` + `multiBlockSystemCaching=true` for the `anthropic` provider, a read-only outcome logger for `openai` and `gemini` (both wired through Spring AI's OpenAI client in this codebase), and a noop strategy for `minimax` and `lmstudio`. Cached and cache-write token counts SHALL be read from Spring AI's provider-neutral usage fields (the cache-read and cache-write input token counts on the response usage), never from a provider-specific usage type.

#### Scenario: Anthropic provider request carries native cache options

- **WHEN** `ChatExecutor.execute` is invoked for a request whose resolved provider name is `anthropic` and `app.ai.prompt-cache.providers.anthropic.enabled` is `true`
- **THEN** the outgoing provider call uses `AnthropicChatOptions` whose `cacheOptions.strategy == SYSTEM_ONLY` and `cacheOptions.multiBlockSystemCaching == true`
- **AND** the prompt is constructed with the static `app.system-prompt` and the dynamic per-user content as TWO separate `SystemMessage` instances so Spring AI applies `cache_control` to the static block only

#### Scenario: OpenAI and Gemini requests log cached_tokens read-only

- **WHEN** `ChatExecutor.execute` is invoked for a request whose resolved provider name is `openai` or `gemini`
- **THEN** the outgoing options are NOT decorated with cache directives (caching is implicit prefix caching on the provider side)
- **AND** after the response, the cache-read input token count on the response usage is read and logged at INFO

#### Scenario: Provider that reports no cache count

- **WHEN** a response's usage carries no cache-read input token count
- **THEN** the strategy treats the cached count as 0
- **AND** the chat response is returned unchanged

#### Scenario: MiniMax and LM Studio receive no cache decoration by default

- **WHEN** `ChatExecutor.execute` is invoked for `minimax` or `lmstudio` with default configuration
- **THEN** the outgoing options carry no cache directive
- **AND** no `[PromptCache]` outcome line is emitted
