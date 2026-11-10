## Purpose

Makes sure every chat request fits the provider's context window with the personality file, the global system prompt, the reminder and the user's own text always kept whole, by reserving their space first and trimming everything else in a fixed, reported order.

## ADDED Requirements

### Requirement: One context window table for the whole agent

The agent SHALL bind `app.chat.context-budget` with a context window in tokens per provider (defaults: `openai` 128000, `anthropic` 200000, `gemini` 1000000, `minimax` 200000, `lmstudio` 8192), a fallback window for any other provider (8192), an output reserve in tokens (default 1024), and a safety margin as a fraction of the window (default 0.1). Token counts SHALL be estimated as characters divided by four, rounded up per part, the estimate compaction already uses. Compaction's token trigger SHALL read its window from this table, so there is one table only. Configuration SHALL be refused at startup when a window is below 1024, the output reserve is not positive, or the margin is outside 0 to 0.5.

#### Scenario: Defaults bind

- **WHEN** the agent starts without overriding `app.chat.context-budget`
- **THEN** the window of `lmstudio` is 8192 and of `anthropic` is 200000
- **AND** the compaction token trigger for `lmstudio` uses 8192

### Requirement: Protected parts are reserved before anything else is assembled

For every chat request the agent SHALL compute the available budget as the window of the request's provider minus the output reserve and the safety margin, then reserve, before any other part is added, the protected parts: the personality block, the global system prompt, the reminder, the user's own typed text, and the tool definitions offered to the request. Protected parts SHALL never be trimmed. When the protected parts alone exceed the available budget, the request SHALL be refused before any provider call with HTTP 413 and the RFC 7807 problem detail that `upgrade-spring-boot-4` defines for every agent error (`application/problem+json`), with `code` `context_too_large`, `type` `https://ascend.ai/errors/context-too-large` and a `detail` naming the provider, the window and the estimated size of the protected parts.

#### Scenario: Protected parts do not fit

- **WHEN** a request to `lmstudio` carries a typed prompt of 30000 characters
- **THEN** the response is 413 with `Content-Type: application/problem+json` and `code` `context_too_large`
- **AND** no provider call is made and nothing is saved to history

### Requirement: Other parts are trimmed in a fixed order

When the protected parts fit but the full request does not, the agent SHALL drop parts in this order until the request fits, and SHALL keep everything not dropped in its normal place: first the oldest raw history turns, one user and assistant pair at a time, then the conversation summary, then the finished subagent runs block, then semantic memory entries from the least relevant, then retrieved document chunks from the lowest score, then the attached document text, cut at the end with a fixed "[attachment cut to fit the context]" line, then the user facts block, replaced by its fixed "none" line. Dropped parts SHALL only be left out of this request and SHALL never be deleted from history or any store. The response metadata SHALL list each trimmed part with its count, and one INFO line SHALL log the provider, the window, the estimate before and after, and the trimmed counts.

#### Scenario: Near-full history on a small window

- **WHEN** a request to `lmstudio` has 60 history turns that together exceed the budget
- **THEN** the oldest turns are left out until the request fits
- **AND** the first system message is the full personality block and the reminder directly precedes the user's typed text at the end of the final user message
- **AND** the response metadata `contextTrimmed` reports the number of history turns left out

#### Scenario: Memory is trimmed before user facts

- **WHEN** after dropping all history the request still does not fit and semantic memory holds 10 entries
- **THEN** semantic memory entries are dropped from the least relevant before the user facts block is touched

### Requirement: The prompt has exactly three system messages

Every chat request SHALL send exactly three system messages: the personality block, the global system prompt, and one dynamic block. The dynamic block SHALL hold, in this order and each under a fixed heading, the user facts, the conversation summary when history starts with one, the finished subagent runs block when there is one, and the semantic memory block. A conversation summary at the head of history SHALL be moved into the dynamic block and SHALL NOT be sent as a history message. Every other system message found in history SHALL be moved into the dynamic block the same way. The dynamic block SHALL always be present, even when all its parts are empty.

#### Scenario: Compacted conversation keeps three system messages

- **WHEN** history starts with a `[Conversation summary]` message followed by 8 turns
- **THEN** the request carries exactly three system messages
- **AND** the summary text is inside the third one and not among the history messages

### Requirement: The budget holds on every chat path

The same layout and budget SHALL apply to the synchronous prompt endpoint, to the streaming endpoint of `add-chat-streaming-and-conversations`, and to the cache retry without decoration, which SHALL reuse the exact prompt of the first attempt.

#### Scenario: Cache retry keeps the same prompt

- **WHEN** the first Anthropic call fails with a cache configuration error and is retried without decoration
- **THEN** the retry sends the same three system messages and the same history as the first attempt

### Requirement: The budget is visible at startup

The startup banner SHALL show each provider's window, the output reserve, the margin, and for each provider the estimated size of the global system prompt plus the personality limit plus the reminder plus the user facts limit as a share of that window. When that share is above `app.chat.context-budget.warn-fraction` (default 0.5) for any provider, one WARN line SHALL name the provider.

#### Scenario: Small window warning

- **WHEN** the personality limit is raised to 20000 characters and `lmstudio` has a window of 8192
- **THEN** the startup log holds one WARN line naming `lmstudio` and the share

### Requirement: The streamed turn uses the same prompt layout and context budget

The streamed turn of `POST /api/v1/ai/prompt/stream` SHALL build its prompt through `PromptLayout` and `ContextBudget` and SHALL compute the request's `RequestProvenance` the same way as the blocking turn, in the one chat executor, putting its holder into the tool context under `request_provenance`. A prompt whose protected part does not fit the context budget SHALL be refused with 413 `context_too_large` before any SSE bytes are written. The `done` event's metadata SHALL carry `fileChanges` and `contextTrimmed`.

#### Scenario: Same provenance as the synchronous path

- **WHEN** the same prompt with a retrieved document is answered once via `/prompt` and once via `/prompt/stream`
- **THEN** both requests carry the same `RequestProvenance` value under `request_provenance` in the tool context

#### Scenario: Over the budget before streaming

- **WHEN** a streamed prompt's protected part does not fit the context budget
- **THEN** the response is HTTP 413 with `code` `context_too_large` and no SSE event is written
