## ADDED Requirements

### Requirement: Compaction trigger threshold is configurable

The system SHALL bind a `ChatHistoryCompactionProperties` `@ConfigurationProperties` class at prefix `app.memory.chat-history.compaction` with at minimum the following keys, all backed by sensible defaults so a fresh deployment behaves correctly with zero operator configuration:

- `enabled` (boolean, default `true`)
- `turn-trigger` (int, default `20`) — fire compaction when raw turn count reaches this value.
- `token-trigger-fraction` (double in `(0.0, 1.0]`, default `0.5`) — fire compaction when estimated input tokens reach this fraction of the resolved provider context window.
- `keep-recent-turns` (int, default `8`) — number of most-recent turns to leave raw.
- `max-summary-tokens` (int, default `800`) — soft cap on summary length; outputs above `1.5 ×` this value are rejected.
- `provider-defaults` (`Map<String, String>`) — per-provider default compaction model. Defaults populated for `openai`, `anthropic`, `gemini`, `minimax`, `lmstudio`.

#### Scenario: Defaults preserve out-of-the-box behavior

- **WHEN** the operator deploys the agent without overriding `app.memory.chat-history.compaction.*`
- **THEN** `ChatHistoryCompactionProperties.isEnabled()` returns `true`
- **AND** `getTurnTrigger()` returns `20`
- **AND** `getTokenTriggerFraction()` returns `0.5`
- **AND** `getKeepRecentTurns()` returns `8`
- **AND** `getMaxSummaryTokens()` returns `800`
- **AND** `getProviderDefaults()` contains entries for `openai`, `anthropic`, `gemini`, `minimax`, and `lmstudio`

#### Scenario: Operator can disable compaction globally

- **WHEN** the operator sets `app.memory.chat-history.compaction.enabled: false`
- **THEN** no compaction call is dispatched regardless of conversation length
- **AND** `PersistentChatMemory.add(...)` continues to function exactly as today

### Requirement: Compaction fires when either trigger is exceeded

`ChatHistoryCompactionService.maybeCompact(...)` SHALL evaluate the current conversation against both the turn-count trigger and the token-budget trigger. Compaction SHALL run if either trigger is exceeded.

#### Scenario: Turn-count trigger fires

- **WHEN** a conversation has accumulated 20 raw turns
- **AND** `turn-trigger=20`, `keep-recent-turns=8`
- **THEN** the compaction service computes a `prefixCount = 20 - 8 = 12` and replaces those 12 oldest turns with a single summary

#### Scenario: Token-budget trigger fires before turn-count

- **WHEN** a conversation has only 10 turns but the estimated input-token total is ≥ 50% of the resolved provider context window
- **AND** `token-trigger-fraction=0.5`
- **THEN** compaction fires anyway, replacing the oldest `10 - 8 = 2` turns

#### Scenario: Below both triggers, no compaction

- **WHEN** a conversation has 5 turns and uses a small fraction of the context window
- **THEN** `ChatHistoryCompactionService` returns without invoking any LLM call
- **AND** no Redis or Postgres modification occurs

### Requirement: Compaction is idempotent

The compaction service SHALL recognise an existing `[Conversation summary]` SystemMessage at the head of the conversation as already-compacted content. Re-running compaction on a state that already contains such a summary AND fewer than `turn-trigger` new turns since that summary SHALL produce no change.

#### Scenario: Re-running on an already-compacted conversation is a no-op

- **WHEN** a conversation history begins with one `[Conversation summary] ...` SystemMessage followed by 6 raw turns
- **AND** `turn-trigger=20`, `keep-recent-turns=8`
- **THEN** `maybeCompact(...)` returns without calling the LLM
- **AND** no Redis or Postgres write is issued

#### Scenario: Compaction merges into the existing summary when new turns accumulate past the trigger

- **WHEN** a conversation begins with one `[Conversation summary] ...` SystemMessage followed by 25 new raw turns
- **THEN** the compaction service calls the LLM once
- **AND** the LLM prompt explicitly instructs the model to treat the existing summary as authoritative and merge
- **AND** the result is a single new `[Conversation summary]` SystemMessage replacing both the old summary and the oldest `25 - 8 = 17` raw turns

### Requirement: Per-provider compaction model with per-request override

The compaction service SHALL resolve which (provider, model) pair to use for the summarisation call by the following order:

1. If the request body includes `compactionProvider` and `compactionModel`, use both verbatim.
2. If only `compactionProvider` is set, use that provider plus `provider-defaults[compactionProvider]`.
3. If only `compactionModel` is set, use the request's primary `provider` plus the given model.
4. Otherwise, use the request's primary `provider` plus `provider-defaults[primaryProvider]`.

The resolved model MUST be invoked via the same `ChatModelResolver` / Spring AI client pathway used for primary chat. No new HTTP client or auth layer is introduced.

#### Scenario: Default resolution uses request provider's cheap variant

- **WHEN** a request with `provider=anthropic` and no `compaction*` fields triggers compaction
- **AND** `provider-defaults.anthropic = claude-haiku-4-5`
- **THEN** the compaction LLM call uses `(anthropic, claude-haiku-4-5)`

#### Scenario: REST override fully overrides defaults

- **WHEN** a request includes `compactionProvider=openai` and `compactionModel=gpt-4o-mini`
- **AND** the primary chat call goes to `(anthropic, claude-sonnet-4-5)`
- **THEN** the compaction LLM call uses `(openai, gpt-4o-mini)` regardless of `provider-defaults`

#### Scenario: Only `compactionProvider` set falls back to that provider's default model

- **WHEN** a request includes `compactionProvider=gemini` and no `compactionModel`
- **AND** `provider-defaults.gemini = gemini-flash-lite-latest`
- **THEN** the compaction LLM call uses `(gemini, gemini-flash-lite-latest)`

### Requirement: Summary format and length cap

The compaction LLM output SHALL be a single SystemMessage whose text begins with the literal marker `[Conversation summary]`. The service SHALL post-validate the output:

- If the output does not begin with the marker, the service SHALL prepend the marker and emit an INFO log.
- If the output is empty or its length exceeds `1.5 × max-summary-tokens` (estimated as `length / 4`), the service SHALL skip the replace step, leave the original turns intact, and emit a WARN log.

#### Scenario: Well-formed summary is accepted

- **WHEN** the compaction LLM returns a paragraph starting with `[Conversation summary]` under the size cap
- **THEN** the paragraph is written verbatim as the replacement SystemMessage

#### Scenario: Missing marker is auto-prepended

- **WHEN** the compaction LLM returns a paragraph that does NOT start with `[Conversation summary]`
- **THEN** the service prepends the marker and continues with the replace
- **AND** an INFO-level log records the auto-prepend

#### Scenario: Oversize output is rejected

- **WHEN** the compaction LLM returns text whose estimated tokens exceed `1.5 × max-summary-tokens`
- **THEN** the service does NOT perform the replace
- **AND** the original raw turns are preserved in both backends
- **AND** a WARN-level log records the rejection with the conversation id

### Requirement: Compaction is async and never fails the user's turn

`PersistentChatMemory.add(conversationId, messages)` SHALL invoke `ChatHistoryCompactionService.maybeCompact(...)` only AFTER its Redis and Postgres persistence side-effects, and SHALL dispatch the call asynchronously so the user's HTTP response is unaffected. Any exception raised inside compaction SHALL be caught and logged at WARN; it SHALL NOT propagate out of `add(...)`.

#### Scenario: Compaction LLM failure does not break the turn

- **WHEN** the compaction LLM call throws (network error, rate-limit, malformed credentials)
- **THEN** `PersistentChatMemory.add(...)` still returns normally
- **AND** the user's prompt response is returned without delay
- **AND** the next turn observes the un-compacted history (compaction will retry next `add(...)`)

#### Scenario: Compaction does not block the user's turn

- **WHEN** a request triggers compaction and the cheap-model call takes 1500 ms
- **THEN** the user's prompt response is returned without waiting for compaction to complete
- **AND** the compaction completes on the async executor

### Requirement: Compaction honors chat-history backend toggles

When both `app.memory.chat-history.redis.enabled` and `app.memory.chat-history.postgres.enabled` are `false`, `PersistentChatMemory.add(...)` SHALL short-circuit before invoking the compaction service. When only one backend is enabled, the compaction service SHALL replace the prefix only in that backend.

#### Scenario: Both backends disabled — compaction not invoked

- **WHEN** a request adds messages with both chat-history toggles set to `false`
- **THEN** `ChatHistoryCompactionService.maybeCompact(...)` is NOT called
- **AND** no LLM call is dispatched

#### Scenario: Redis disabled, Postgres enabled — only Postgres receives the replace

- **WHEN** compaction fires with `redis.enabled=false`, `postgres.enabled=true`
- **THEN** the repository's `replacePrefixWithSummary(...)` is called
- **AND** no Redis call (`LTRIM`, `LPUSH`, `EXPIRE`) is issued

### Requirement: Startup banner reports compaction state

The readiness banner emitted by `StartupLogConfig` SHALL include a line reporting whether compaction is enabled and, when enabled, the resolved trigger thresholds and per-provider default models.

#### Scenario: Banner reports enabled compaction with config snapshot

- **WHEN** the application boots with `enabled=true`, `turn-trigger=20`, `token-trigger-fraction=0.5`, `keep-recent-turns=8`, and the default `provider-defaults` map
- **THEN** the banner contains a line of the form `Chat History Compaction: [Enabled] (trigger: 20 turns / 50% context, keep: 8 turns, defaults: openai=gpt-4o-mini, anthropic=claude-haiku-4-5, gemini=gemini-flash-lite-latest, ...)`

#### Scenario: Banner reports disabled compaction

- **WHEN** the application boots with `app.memory.chat-history.compaction.enabled=false`
- **THEN** the banner contains exactly `Chat History Compaction: [Disabled]`

### Requirement: REST API exposes two optional override fields

The prompt request DTO consumed by `POST /api/v1/ai/prompt` SHALL accept two optional fields, `compactionProvider` and `compactionModel`. Omitting either field SHALL fall through to the resolution rules in the "Per-provider compaction model with per-request override" requirement. Existing callers that do not send either field SHALL observe identical behavior to today's API.

#### Scenario: Existing callers see no change

- **WHEN** a client POSTs a prompt without `compactionProvider` or `compactionModel`
- **THEN** the request is accepted exactly as before
- **AND** if compaction fires, it uses the per-provider default for the primary `provider`

#### Scenario: Override fields are accepted

- **WHEN** a client POSTs a prompt that includes `compactionProvider=openai` and `compactionModel=gpt-4o-mini`
- **THEN** the request is accepted with HTTP 200
- **AND** any compaction triggered by this turn uses `(openai, gpt-4o-mini)`

#### Scenario: Unknown compaction provider is rejected at the boundary

- **WHEN** a client POSTs a prompt with `compactionProvider=does-not-exist`
- **THEN** the controller responds with HTTP 400 and an error message naming the offending field
- **AND** no compaction call is dispatched
