## REMOVED Requirements

### Requirement: Structured article extraction behind an output-format switch

**Reason**: The requirement described the structured extractor correctly and then pinned the API surface shut:
"The REST and MCP read operations do not expose this field, so every response served over the API is the flat shape
and no caller is affected", with a scenario, "API callers always receive the flat shape", asserting exactly that.
Both statements are now false by intent. The extractor itself is unchanged, so only the API half of the requirement
is being rewritten, and the scenario that asserts the closed surface cannot survive that rewrite.

**Migration**: Replaced by "Structured article extraction, selectable by the caller" below. The two orchestrator
scenarios carry over word for word. The closed-surface scenario is replaced by one that asserts the structured
response over the API and one that asserts the rejected combination with `include_links`. A caller that sends no
`output_format` sees no change, because the field defaults to `text`.

## ADDED Requirements

### Requirement: Structured article extraction, selectable by the caller

The orchestrator SHALL support an `output_format` of `structured` that returns extracted article metadata, at least
title, author, publication date, and site name, alongside the main text, using the extractor's metadata capability.
When `output_format` is absent or `text`, the response shape SHALL be the flat content field, unchanged from
before.

The REST and MCP read operations SHALL accept `output_format` and SHALL default it to `text`, so a caller that
omits it receives the flat shape it receives today. Because the annotated-links response carries the flat content
plus a link map and cannot carry the structured shape, `output_format=structured` combined with `include_links`
SHALL be rejected at the API boundary rather than accepted and ignored.

#### Scenario: Structured output requested from the orchestrator

- **WHEN** a read runs with `output_format=structured` for an article page
- **THEN** the result includes the main text plus available title, author, date, and site-name fields

#### Scenario: Default output unchanged

- **WHEN** a read runs without `output_format`
- **THEN** the response shape is the flat content response

#### Scenario: Structured output requested over the API

- **WHEN** a read is requested over REST or MCP with `output_format=structured`
- **THEN** the response carries the structured fields alongside the content

#### Scenario: Structured output asked for with links

- **WHEN** a read is requested with `output_format=structured` and `include_links=true`
- **THEN** the request is rejected at the boundary naming the unsupported combination
- **AND** no read runs
