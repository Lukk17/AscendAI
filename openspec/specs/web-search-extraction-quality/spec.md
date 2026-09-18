# web-search-extraction-quality Specification

## Purpose

Defines what ascend-web-hunter returns from a fetched page: the structured article extraction available behind an output-format switch, the readability fallback that rescues a thin primary extraction, and the scrolling the browser tier drives so lazy-loaded and infinite-scroll content is present before extraction runs.

## Requirements

### Requirement: Readability fallback for thin extractions

When the primary extractor (trafilatura) returns content below a configurable quality threshold, the service SHALL attempt a `readability-lxml` extraction and return whichever result scores higher by content length/density.

#### Scenario: Primary extractor yields thin content

- **WHEN** trafilatura returns content below the quality threshold for a page that has substantial main content
- **THEN** the readability fallback runs
- **AND** the higher-scoring extraction is returned

### Requirement: Dynamic-page scroll handling

The Playwright tier SHALL drive scrolling for lazy-loaded / infinite-scroll pages using the existing `SCROLL_*` settings (iterations and step), which are currently defined but unused. Scrolling SHALL be bounded by the configured iteration count and the per-read wall-clock budget.

#### Scenario: Infinite-scroll page

- **WHEN** a page loads additional content on scroll and the Playwright tier handles it
- **THEN** the tier scrolls up to the configured iteration count before extracting
- **AND** content that only appears after scrolling is present in the extracted result

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
