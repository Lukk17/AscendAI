## Purpose

Bounds what a single inference is allowed to cost, so the memory peak of the service is a property of its
configuration rather than a property of whatever the caller happened to upload.

## ADDED Requirements

### Requirement: The input to one inference is bounded by configuration, not by the caller

The service SHALL bound the input given to text detection to a longest-side limit set by the operator, independently
of the size of the page or image submitted. A caller MAY choose among operator-configured quality modes, each of
which names its own bound, and SHALL NOT supply the bound as a number. The bound SHALL NOT be unset. Lowering a bound
reduces memory and reduces the smallest text that can be detected, so the deployed values SHALL be chosen by
measuring both against real documents rather than taken as unexamined defaults. The modes, the bound each ships with
and the largest downscale a bound may impose are owned by the `ocr-page-resolution` capability.

#### Scenario: Input larger than the bound

- **WHEN** a page whose longest side exceeds its mode's bound is submitted
- **THEN** detection receives the page scaled down to the bound
- **AND** the peak memory of the call is lower than the same page would produce with no bound

#### Scenario: Input smaller than the bound

- **WHEN** a page whose longest side is below its mode's bound is submitted
- **THEN** the page is not scaled up to reach the bound

#### Scenario: Recognition reads the rendered page, within a measured ratio

- **WHEN** text is detected on the scaled-down page
- **THEN** the text is recognised from crops of the page at its rendered resolution
- **AND** that holds as a quality claim only while the downscale stays within the ratio `ocr-page-resolution`
  permits, because past it every line can be found and every line misread

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
