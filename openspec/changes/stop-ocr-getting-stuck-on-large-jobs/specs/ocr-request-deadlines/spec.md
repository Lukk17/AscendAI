## Purpose

Bounds how long an OCR request may occupy the service, so a long document is not failed for being long, an expired
request stops consuming processor time, and the requests behind it are served instead of inheriting the wait.

## ADDED Requirements

### Requirement: A request budget is derived per page and capped overall

The service SHALL derive each request's time budget from a configured per-page allowance and a configured absolute
ceiling on the whole request. The effective budget SHALL be the smaller of the page count multiplied by the per-page
allowance, and the absolute ceiling. A document SHALL NOT be failed merely for having more pages than a
single-page budget covers, and no request SHALL be allowed to run beyond the absolute ceiling however many pages it
has. Both values SHALL be configurable.

#### Scenario: Multi-page document within the derived budget

- **WHEN** a document of several pages is submitted and each page completes inside the per-page allowance
- **THEN** the service returns the full result
- **AND** the request is not failed for exceeding a single-page budget

#### Scenario: Page count large enough for the ceiling to bind

- **WHEN** a document is submitted whose page count multiplied by the per-page allowance exceeds the absolute
  ceiling
- **THEN** the effective budget is the absolute ceiling, not the larger per-page sum

#### Scenario: A single page that runs long

- **WHEN** one page of a document consumes more than the per-page allowance
- **THEN** the service stops the request once the budget for the whole document is exhausted
- **AND** the caller receives a failure rather than an unbounded wait

### Requirement: An expired request stops computing

When a request's budget is exhausted, the service SHALL stop working on it. The component performing inference
SHALL be given the remaining budget as a duration rather than as an absolute point in time, because clocks are not
comparable across processes, and SHALL check that budget before beginning each page. The service SHALL NOT continue
inferring pages of a request whose caller has already been told the request failed.

#### Scenario: Budget expires part way through a document

- **WHEN** a document's budget is exhausted after some of its pages have been processed
- **THEN** no further page of that document is inferred
- **AND** the processor time consumed after the caller was told the request failed is bounded by at most one page

#### Scenario: Budget already exhausted before the first page

- **WHEN** a request reaches the inference stage with no budget remaining
- **THEN** no page is inferred at all

### Requirement: An expired request fails with the existing OCR failure code and returns nothing partial

A request that exhausts its budget SHALL fail with the service's existing OCR failure code and its HTTP status, on
both the REST and the MCP surface. The service SHALL NOT return a partial result, because a caller cannot
distinguish a truncated document from a short one.

#### Scenario: Timed-out request on the REST surface

- **WHEN** a request submitted over REST exhausts its budget
- **THEN** the response carries the existing OCR failure code and its status
- **AND** the response body contains no page or text content

#### Scenario: Timed-out request on the MCP surface

- **WHEN** the same request is made through the MCP tool
- **THEN** it fails with the same error code as the REST surface
- **AND** no partial page content is returned

### Requirement: Requests waiting for the worker hold their own deadline

Requests that arrive while the service is busy SHALL wait in a queue whose depth is observable. A queued request
SHALL count its wait against its own budget, and a request whose budget expires while it is still waiting SHALL
fail without ever being dispatched for inference. The service SHALL NOT begin inference for a request whose caller
has already been told it failed.

#### Scenario: A request that expires while queued

- **WHEN** a request waits behind a longer job until its own budget is exhausted
- **THEN** it fails with the same error code as any other expired request
- **AND** no inference is performed for it

#### Scenario: A request that is dispatched after waiting

- **WHEN** a request waits behind another job and the worker becomes free while it still has budget left
- **THEN** it is dispatched with only its remaining budget, not with a fresh full budget

#### Scenario: Queue depth is observable

- **WHEN** requests are waiting for the worker
- **THEN** the number waiting is exposed to operators

### Requirement: One job at a time, and the limit is explicit

The service SHALL process one OCR job at a time. The concurrency limit SHALL come from a single configured value
that governs both the number of inference workers and the number of requests admitted for inference
simultaneously, so the two cannot disagree. The documented memory ceiling of the service SHALL be stated as
depending on that value.

#### Scenario: A second request arrives while one is running

- **WHEN** a request arrives while another is being inferred
- **THEN** it waits rather than being inferred alongside the first
- **AND** the peak memory of the service does not rise by a second job's cost

#### Scenario: Configured limit governs both sides

- **WHEN** the configured concurrency limit is read
- **THEN** the number of inference workers and the number of simultaneously admitted requests are both equal to it

### Requirement: A worker that will not stop is replaced

A single page's inference cannot be interrupted from outside the process performing it. When the inference process
has not returned within a configured grace period after its own budget expired, the service SHALL replace that
process so the queue behind it is served. The service SHALL report itself as unable to take work while the
replacement is in progress, and SHALL resume serving once the replacement is ready.

#### Scenario: Worker does not return after its budget expired

- **WHEN** the inference process has not returned by the end of the grace period following its expired budget
- **THEN** the service replaces it
- **AND** requests waiting in the queue are served by the replacement rather than waiting for the abandoned job

#### Scenario: Service state during replacement

- **WHEN** a replacement is in progress
- **THEN** the service reports that it cannot take work
- **AND** it reports that it can take work again once the replacement is ready

#### Scenario: Normal expiry needs no replacement

- **WHEN** the inference process observes its own expired budget and returns on its own
- **THEN** no replacement occurs
- **AND** the next queued request is served without waiting for a new process to warm up
