## ADDED Requirements

### Requirement: Compaction never touches the personality file or the reminder

Compaction SHALL read and replace only chat history rows. The personality file, its heading and the personality reminder are never written into chat history, so the summariser SHALL never receive them and a summary SHALL never replace them. After compaction the next request SHALL still carry the full personality block as its first system message and the reminder right before the user's typed text in its final user message, and the summary SHALL be placed inside the dynamic system block.

#### Scenario: Personality survives compaction

- **WHEN** compaction replaces the oldest 12 turns of a conversation with a summary
- **THEN** the summariser input contains neither the personality file text nor the reminder
- **AND** the next request's first system message is the full personality block and its third system message contains the summary

### Requirement: Token trigger uses the shared context window table

The token-budget trigger SHALL take the provider's context window from `app.chat.context-budget`, the same table the chat context budget uses, and SHALL NOT keep a context window table of its own.

#### Scenario: Window override reaches compaction

- **WHEN** the operator sets the `lmstudio` window to 32768 in `app.chat.context-budget`
- **AND** a conversation on `lmstudio` reaches an estimated 16384 input tokens with `token-trigger-fraction=0.5`
- **THEN** compaction fires
