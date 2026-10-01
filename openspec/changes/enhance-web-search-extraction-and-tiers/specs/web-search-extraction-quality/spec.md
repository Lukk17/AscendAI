## MODIFIED Requirements

### Requirement: Structured article extraction, selectable by the caller

The orchestrator SHALL support an `output_format` of `structured` that returns extracted article metadata, at least
title, author, publication date, and site name, plus the embedded structured data in `metadata`, alongside the main
text. When `output_format` is absent or `text`, the response shape SHALL be the flat content field, unchanged from
before. `output_format` SHALL be one of `text`, `structured`, `schema`, `tables` and `screenshot`.

The REST and MCP read operations SHALL accept `output_format` and SHALL default it to `text`, so a caller that
omits it receives the flat shape it receives today. Because the annotated-links response carries the flat content
plus a link map and cannot carry any other shape, `include_links` SHALL be accepted only with `output_format`
`text`, and every other format combined with `include_links` SHALL be rejected at the API boundary rather than
accepted and ignored.

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

#### Scenario: Non-text format asked for with links

- **WHEN** a read is requested with `include_links=true` and any `output_format` other than `text`
- **THEN** the request is rejected at the boundary naming the unsupported combination
- **AND** no read runs

## REMOVED Requirements

### Requirement: Readability fallback for thin extractions

**Reason**: Replaced by the scored ensemble in `web-search-structured-extraction`, which runs both extractors on every page instead of only below a threshold. ADR-009 is superseded by ADR-016.

**Migration**: None for callers. The response shape is unchanged. Any setting that only served the recall-pass threshold is removed from configuration and docs.
