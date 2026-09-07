## Purpose

Bounds what a single inference is allowed to cost, so the memory peak of the service is a property of its
configuration rather than a property of whatever the caller happened to upload.

## ADDED Requirements

### Requirement: The input to one inference is bounded by configuration, not by the caller

The service SHALL bound the input given to text detection to a configured longest-side limit, independently of the
size of the page or image submitted. The bound SHALL be configurable, and it MAY be unset to restore the library's
own unbounded behaviour. Lowering the bound reduces memory and reduces the smallest text that can be detected, so
the deployed value SHALL be chosen by measuring both against real documents rather than taken as an unexamined
default. The owner measured 960, 1280 and 1536 against his own documents and chose 1536 as near lossless; the
shipped default is therefore 1536, not the library's unbounded behaviour, and the three candidates with what each
costs in memory and in detected lines are recorded in
[ADR-006](../../../../apps/ascend-ocr/docs/architecture/decisions/ADR-006-detector-input-bound.md).

#### Scenario: Input larger than the bound

- **WHEN** a bound is configured and a page whose longest side exceeds it is submitted
- **THEN** detection receives the page scaled down to the bound
- **AND** the peak memory of the call is lower than the same page produces with no bound configured

#### Scenario: Input smaller than the bound

- **WHEN** a bound is configured and a page whose longest side is below it is submitted
- **THEN** the page is not scaled up to reach the bound

#### Scenario: No bound configured

- **WHEN** no bound is configured
- **THEN** detection receives the page at the resolution it would receive today

#### Scenario: Text is read at full resolution whatever the bound

- **WHEN** a bound is configured and text is detected on the scaled-down page
- **THEN** the text is recognised from the page at its full resolution, so the bound costs detected lines rather
  than recognition quality

### Requirement: Peak memory is set by the largest page, not by the length of the document

The memory cost of a request SHALL be governed by the largest single page it contains. The service SHALL process
pages one at a time and SHALL release each page's rendered image before the next page is rendered, so that adding
pages to a document adds only the memory its results retain.

#### Scenario: Many pages of ordinary size

- **WHEN** a document of many pages, none of them unusually large, is processed
- **THEN** peak memory is close to the cost of one of those pages
- **AND** it does not grow in proportion to the page count

#### Scenario: One page much larger than the rest

- **WHEN** a document contains one page far larger than its others
- **THEN** peak memory is governed by that page

### Requirement: The service states the memory ceiling its configuration implies

At startup the service SHALL report the peak memory one call may reach under its current configuration, and SHALL
state that this ceiling is multiplied by the configured concurrency limit. An operator SHALL be able to read the
consequence of raising that limit without deriving it.

#### Scenario: Startup reports the ceiling

- **WHEN** the service starts
- **THEN** its startup output states the implied per-call memory ceiling and the concurrency limit it is
  multiplied by

#### Scenario: The ceiling follows the configuration

- **WHEN** the detector bound or the pixel ceiling is changed and the service is restarted
- **THEN** the reported ceiling changes with them
