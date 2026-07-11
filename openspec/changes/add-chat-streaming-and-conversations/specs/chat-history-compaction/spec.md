# chat-history-compaction Delta Specification

## MODIFIED Requirements

### Requirement: REST API exposes two optional override fields

The prompt request contracts consumed by `POST /api/v1/ai/prompt` and `POST /api/v1/ai/prompt/stream` SHALL both
accept two optional fields, `compactionProvider` and `compactionModel`. Omitting either field SHALL fall through to
the resolution rules in the "Per-provider compaction model with per-request override" requirement. Compaction scope is
the individual conversation resolved for the request (the conversation UUID), not the user's lifetime history.
Existing callers of the synchronous endpoint that do not send either field SHALL observe identical behavior to
today's API.

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

#### Scenario: Stream endpoint honors the override fields

- **WHEN** a client POSTs to `/api/v1/ai/prompt/stream` with `compactionProvider=openai` and `compactionModel=gpt-4o-mini` and the turn crosses a compaction trigger
- **THEN** the compaction dispatched after the stream terminates uses `(openai, gpt-4o-mini)`
- **AND** the compaction replaces the prefix of that conversation only, leaving the user's other conversations untouched
