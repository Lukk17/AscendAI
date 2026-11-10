## MODIFIED Requirements

### Requirement: Static prefix is cached per provider via the strategy resolver

ascend-ai-agent SHALL apply a provider-specific prompt-cache strategy (resolved by **provider name**) to the static prefix of every chat request and every memory-extraction request (the `SemanticMemoryExtractor.EXTRACTOR_INSTRUCTION` prefix). The static prefix of a chat request SHALL be the tenant's personality block followed by the `app.system-prompt` SystemMessage. The strategy SHALL use Spring AI's native `AnthropicChatOptions.cacheOptions(...)` with `AnthropicCacheStrategy.SYSTEM_ONLY` + `multiBlockSystemCaching=true` for the `anthropic` provider, a read-only outcome logger for `openai` and `gemini` (both wired through Spring AI's OpenAI client in this codebase), and a noop strategy for `minimax` and `lmstudio`. Cached and cache-write token counts SHALL be read from Spring AI's provider-neutral usage fields (the cache-read and cache-write input token counts on the response usage), never from a provider-specific usage type.

#### Scenario: Anthropic provider request carries native cache options

- **WHEN** the one chat executor `StreamingChatExecutor` is invoked for a request whose resolved provider name is `anthropic` and `app.ai.prompt-cache.providers.anthropic.enabled` is `true`
- **THEN** the outgoing provider call uses `AnthropicChatOptions` whose `cacheOptions.strategy == SYSTEM_ONLY` and `cacheOptions.multiBlockSystemCaching == true`
- **AND** the prompt is constructed with exactly three `SystemMessage` instances in this order: the personality block, the static `app.system-prompt`, and the dynamic per-request content, so Spring AI applies `cache_control` to the second-to-last block, the `app.system-prompt`, and the cached prefix covers the personality block and the global prompt

#### Scenario: Compacted conversation keeps the breakpoint on the global prompt

- **WHEN** an Anthropic request is made for a conversation whose history starts with a conversation summary
- **THEN** the outgoing `system` array has exactly three blocks
- **AND** `cache_control` is on the second block, which holds the `app.system-prompt`

#### Scenario: Reminder never moves the breakpoint

- **WHEN** an Anthropic request is made with the personality reminder
- **THEN** the reminder is in the final user message and not in the `system` array

#### Scenario: OpenAI and Gemini requests log cached_tokens read-only

- **WHEN** the one chat executor `StreamingChatExecutor` is invoked for a request whose resolved provider name is `openai` or `gemini`
- **THEN** the outgoing options are NOT decorated with cache directives (caching is implicit prefix caching on the provider side)
- **AND** after the response, the cache-read input token count on the response usage is read and logged at INFO

#### Scenario: Provider that reports no cache count

- **WHEN** a response's usage carries no cache-read input token count
- **THEN** the strategy treats the cached count as 0
- **AND** the chat response is returned unchanged

#### Scenario: MiniMax and LM Studio receive no cache decoration by default

- **WHEN** the one chat executor `StreamingChatExecutor` is invoked for `minimax` or `lmstudio` with default configuration
- **THEN** the outgoing options carry no cache directive
- **AND** no `[PromptCache]` outcome line is emitted

### Requirement: Caching is bound to the static prefix only

The cached prefix SHALL contain only the tenant's personality block, the global `app.system-prompt` SystemMessage and (for the extraction path) the `EXTRACTOR_INSTRUCTION`. The personality block is the same for every user of a tenant and changes only when the tenant's personality file changes, so it is static per tenant. Per-user and per-request content - user facts, user memory, the conversation summary, finished subagent runs, RAG-retrieved chunks, attached documents, chat-history turns and the personality reminder - SHALL NOT be included in the cached portion of the prompt. This guarantees that no user data crosses user-id boundaries via the cache. Two requests of the same tenant with an unchanged personality file SHALL send byte-identical first and second system messages.

#### Scenario: Per-request user memory is not cached

- **WHEN** a chat request includes a non-empty `User memory (may be relevant):` block in the assembled SystemMessage
- **THEN** the cache directive (Anthropic block annotation / Gemini `CachedContent`) covers only the personality block and the static `app.system-prompt` portion and not the user-memory block

#### Scenario: RAG context is not cached

- **WHEN** a chat request includes RAG-retrieved chunks
- **THEN** the cache directive does not cover the RAG-context portion of the prompt

#### Scenario: User facts are not cached

- **WHEN** a chat request includes user facts
- **THEN** the user facts are in the third system message, after the cache breakpoint

#### Scenario: Prefix is stable across users of one tenant

- **WHEN** two users of tenant `default` with different user facts, memory and history send requests while the personality file is unchanged
- **THEN** both requests send byte-identical first and second system messages
