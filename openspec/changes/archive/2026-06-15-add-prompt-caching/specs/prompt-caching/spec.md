## ADDED Requirements

### Requirement: Static prefix is cached per provider via the strategy resolver

AscendAgent SHALL apply a provider-specific prompt-cache strategy (resolved by **provider name**) to the static prefix of every chat request (the `app.system-prompt` SystemMessage) and every memory-extraction request (the `SemanticMemoryExtractor.EXTRACTOR_INSTRUCTION` prefix). The strategy SHALL use Spring AI's native `AnthropicChatOptions.cacheOptions(...)` with `AnthropicCacheStrategy.SYSTEM_ONLY` + `multiBlockSystemCaching=true` for the `anthropic` provider, a read-only outcome logger for `openai` and `gemini` (both wired through Spring AI's OpenAI client in this codebase), and a noop strategy for `minimax` and `lmstudio`.

#### Scenario: Anthropic provider request carries native cache options

- **WHEN** `ChatExecutor.execute` is invoked for a request whose resolved provider name is `anthropic` and `app.ai.prompt-cache.providers.anthropic.enabled` is `true`
- **THEN** the outgoing provider call uses `AnthropicChatOptions` whose `cacheOptions.strategy == SYSTEM_ONLY` and `cacheOptions.multiBlockSystemCaching == true`
- **AND** the prompt is constructed with the static `app.system-prompt` and the dynamic per-user content as TWO separate `SystemMessage` instances so Spring AI applies `cache_control` to the static block only

#### Scenario: OpenAI and Gemini requests log cached_tokens read-only

- **WHEN** `ChatExecutor.execute` is invoked for a request whose resolved provider name is `openai` or `gemini`
- **THEN** the outgoing options are NOT decorated with cache directives (caching is implicit prefix caching on the provider side)
- **AND** after the response, `OpenAiApi.Usage.PromptTokensDetails.cachedTokens` is read and logged at INFO

#### Scenario: MiniMax and LM Studio receive no cache decoration by default

- **WHEN** `ChatExecutor.execute` is invoked for `minimax` or `lmstudio` with default configuration
- **THEN** the outgoing options carry no cache directive
- **AND** no `[PromptCache]` outcome line is emitted

### Requirement: Cache hit and miss are observable in structured logs

Each provider strategy SHALL log a single INFO line per chat call after reading back the provider's reported cached-token count. The line SHALL include the provider name, a boolean `hit` field, and the raw `cached_tokens` (or equivalent) value. Counters are deferred to the `add-observability` change.

#### Scenario: Anthropic cache hit produces an INFO log

- **WHEN** an Anthropic response returns with `cacheReadInputTokens=487`
- **THEN** AscendAgent logs at INFO `[PromptCache] provider=anthropic user=<id> hit=true cache_read_tokens=487 cache_creation_tokens=<n> prompt_tokens=<n>`
- **AND** no error or warning is logged

#### Scenario: OpenAI cache miss on first call

- **WHEN** an OpenAI response returns with `PromptTokensDetails.cachedTokens=0`
- **THEN** AscendAgent logs at INFO `[PromptCache] provider=openai user=<id> hit=false cached_tokens=0 prompt_tokens=<n>`

### Requirement: Cache failure never breaks the chat flow

If a cache-decorated provider call fails because of cache configuration (e.g., Anthropic rejects a malformed `cache_control` block, Gemini returns 4xx because the `CachedContent` resource expired or is missing), AscendAgent SHALL retry the call exactly once with the undecorated request, log a single WARN line naming the provider and the failure reason, and serve the retry result to the caller. Non-cache exceptions SHALL NOT be swallowed.

#### Scenario: Anthropic rejects cache_control block

- **WHEN** the first Anthropic call throws a 400 whose body mentions `cache_control`
- **THEN** AscendAgent retries exactly once without the cache decoration
- **AND** logs `[PromptCache] provider=anthropic WARN cache call failed, retrying without cache: <reason>` exactly once
- **AND** the user-visible response is the retry result

#### Scenario: Non-cache provider exception is not retried

- **WHEN** the provider call throws a 401 unauthorized exception unrelated to cache config
- **THEN** AscendAgent does NOT retry
- **AND** the original exception propagates through the existing exception-handling chain

### Requirement: Master and per-provider toggles disable caching cleanly

`PromptCacheProperties` SHALL expose `app.ai.prompt-cache.enabled` (master) and `app.ai.prompt-cache.providers.<name>.enabled` (per-provider). When either evaluates to `false` for the active provider, the resolver SHALL return a `NoopPromptCacheStrategy` that does not decorate the outgoing prompt and does not read response metadata. Default values: master `true`; anthropic/openai/gemini per-provider `true`; minimax/lmstudio per-provider `false`.

#### Scenario: Master toggle off

- **WHEN** `app.ai.prompt-cache.enabled=false` and a chat request is made on any provider
- **THEN** the outgoing prompt is not decorated with any cache marker
- **AND** no `[PromptCache]` log line is emitted

#### Scenario: Per-provider override off

- **WHEN** `app.ai.prompt-cache.enabled=true` and `app.ai.prompt-cache.providers.anthropic.enabled=false` and the active provider is `anthropic`
- **THEN** the outgoing Anthropic call has no `cache_control` marker
- **AND** other providers continue to apply their cache strategies on their own requests

### Requirement: Memory-extraction prefix is cached on the same provider strategy

`SemanticMemoryExtractor` SHALL apply the same resolved provider strategy to the static `EXTRACTOR_INSTRUCTION` prefix on every extraction call, with the same fallback semantics as the chat flow.

#### Scenario: Extractor call goes through the cache strategy

- **WHEN** `SemanticMemoryExtractor.extract(...)` is invoked on a paid provider
- **THEN** the outgoing provider call has the provider's cache directive attached to the static instruction prefix
- **AND** a cache-config exception triggers exactly one retry without decoration, identical to the `ChatExecutor` behavior

### Requirement: Caching is bound to the static prefix only

The cached prefix SHALL contain only globally-static content: the `app.system-prompt` SystemMessage and (for the extraction path) the `EXTRACTOR_INSTRUCTION`. Per-request content — user memory, RAG-retrieved chunks, attached documents, and chat-history turns — SHALL NOT be included in the cached portion of the prompt. This guarantees that no user data crosses user-id boundaries via the cache.

#### Scenario: Per-request user memory is not cached

- **WHEN** a chat request includes a non-empty `User memory (may be relevant):` block in the assembled SystemMessage
- **THEN** the cache directive (Anthropic block annotation / Gemini `CachedContent`) covers only the static `app.system-prompt` portion and not the user-memory block

#### Scenario: RAG context is not cached

- **WHEN** a chat request includes RAG-retrieved chunks
- **THEN** the cache directive does not cover the RAG-context portion of the prompt
