## Purpose

Decides which documents the service takes on and which it refuses, so that one worker serving one document at a
time is never handed more work than it can finish or more waiting work than it can promise a time for.

## ADDED Requirements

### Requirement: A document has a page ceiling, and it bounds what one document may do to the queue

The service SHALL refuse a document whose page count exceeds a configured ceiling. That ceiling SHALL be
configurable, and its default SHALL be derived from how long one document may occupy the single worker and hold up
everything queued behind it, stated as a measured per-page cost multiplied by the ceiling. It SHALL NOT be derived
from a time limit on a request, because no caller is holding a connection against the work. The documentation SHALL
also record the memory the ceiling implies, as a cross-check rather than as the derivation, together with the
per-page memory term it uses and whether that term is measured or carried forward. The refusal SHALL use the
service's existing oversized-input error code, SHALL name the document's page count and the ceiling, and SHALL
happen before any page is read.

#### Scenario: Document above the page ceiling

- **WHEN** a document with more pages than the ceiling is submitted
- **THEN** the service refuses it with the existing oversized-input code
- **AND** the refusal names the document's page count and the ceiling
- **AND** no page of it is read and no worker is occupied

#### Scenario: Document at the page ceiling

- **WHEN** a document with exactly the ceiling's page count is submitted
- **THEN** it is accepted

#### Scenario: The basis of the ceiling is documented

- **WHEN** the configured ceiling is read together with the documentation that derives it
- **THEN** the documentation states the longest the worker may be held by one document at that ceiling, using a
  measured per-page cost
- **AND** it states the memory that ceiling implies, which per-page memory term it used, and whether that term was
  measured against the models the service runs today or carried forward from an earlier fit
- **AND** raising the ceiling is described as a decision about the queue rather than as a throughput setting

#### Scenario: No page ceiling is derived from a deadline

- **WHEN** the service's settings are read
- **THEN** the page ceiling is the configured one
- **AND** no setting bounds a request's total duration, because no request holds a connection

### Requirement: Work that provably cannot finish is still refused up front

The ceiling on how long a document may spend being read SHALL be derived from the page ceiling multiplied by the
per-page allowance of the slowest engine any accepted language can load, rather than configured independently, so that a document at the page ceiling always has exactly
enough budget to be read and no accepted document can be one that provably cannot finish. Accepting work that cannot
finish occupies the only worker for the whole ceiling and tells the caller nothing until it expires.

#### Scenario: The two ceilings cannot disagree

- **WHEN** the page ceiling or any engine's per-page allowance is changed
- **THEN** the reading ceiling changes with them
- **AND** a document at the page ceiling still has its own engine's full per-page allowance for every one of its pages

#### Scenario: Every accepted document can finish

- **WHEN** any document is accepted
- **THEN** its page count multiplied by its own engine's per-page allowance is within the reading ceiling

### Requirement: The per-page allowance is a deadline sized above the measured cost

Each page's allowance SHALL be set above the measured cost of reading a page on the engine that reads it, by a stated
margin, and every other duration the service derives SHALL be derived from those allowances. How an engine's
allowance is computed, and the one configured time input it follows, are owned by the `ocr-page-resolution`
capability. The documentation SHALL record the measurements, the margin, and whether those measurements came from
real documents or from synthetic ones. An allowance sized at the measured cost would fail legitimate pages, and an
allowance stated without its evidence cannot be revised when the evidence changes.

#### Scenario: The allowance is documented against its evidence

- **WHEN** an engine's per-page allowance is read together with its documentation
- **THEN** the documentation gives the measurements it was derived from and the margin above them
- **AND** it states plainly whether those measurements were taken on real scanned documents or on synthetic pages

#### Scenario: Every derived duration follows the allowance

- **WHEN** an engine's per-page allowance changes
- **THEN** the reading ceiling, the reclamation grace, the maximum lifetime, the queue's promised wait and the poll
  hint all change with it wherever that engine's allowance enters them
- **AND** none of them has to be edited separately for them to agree

### Requirement: Every existing input guard applies at submission

The source pixel ceiling that guards against decompression bombs, the byte size limit and the file type check SHALL
apply to every submitted document with the same error codes and the same detail they carry today, and SHALL be
applied at submission time rather than when reading starts. A document that any of these guards refuses SHALL never
reach the queue. A page larger than its quality mode supports is not refused by these guards, because the
`ocr-page-resolution` capability reads it shrunk.

#### Scenario: Decompression bomb submitted

- **WHEN** a raster image declaring more pixels than the source pixel ceiling is submitted
- **THEN** it is refused at submission with the existing oversized-input error code
- **AND** no work is queued for it

#### Scenario: Unsupported file type submitted

- **WHEN** a file whose type the service does not support is submitted
- **THEN** it is refused at submission with the existing unsupported-type code

#### Scenario: Refusal happens before anything is queued

- **WHEN** a submission is refused by any input guard
- **THEN** no identifier is issued for it
- **AND** the queue is unchanged

### Requirement: The queue is bounded in pages and in documents

The service SHALL bound how much work may be waiting at once, both as a total number of pages across everything
waiting and as a number of waiting documents. Both bounds SHALL be configurable. The page bound exists because it is
what makes the wait predictable: the longest a newly accepted submission can wait is the pages already waiting,
each multiplied by the per-page allowance of the engine that will read it. The page bound SHALL NOT be configurable below the page ceiling, because a
single maximal document could then never be queued. The document bound exists because the service holds each waiting
submission's bytes until it runs, so the count is what bounds that storage. A submission that would exceed either
bound SHALL be refused with a distinct queue-full code and a status that tells the caller to try again later, rather
than being accepted into an unbounded wait.

#### Scenario: Page bound reached

- **WHEN** a submission would push the total pages waiting above the page bound
- **THEN** the service refuses it with the queue-full code
- **AND** the refusal tells the caller it can be retried later

#### Scenario: Document bound reached

- **WHEN** a submission would push the number of waiting documents above the document bound, even though the pages
  waiting are within the page bound
- **THEN** the service refuses it with the same queue-full code

#### Scenario: A queue that could not hold one maximal document is rejected

- **WHEN** the service is configured with a queue page bound below the page ceiling
- **THEN** it refuses to start
- **AND** the message names both settings

#### Scenario: Refusal is temporary and self-clearing

- **WHEN** a submission is refused because the queue is full and waiting work then completes
- **THEN** an identical submission made afterwards is accepted
- **AND** no operator action was needed in between

#### Scenario: The promise the bound makes

- **WHEN** a submission is accepted while the queue holds some number of pages
- **THEN** the service reports how many pages are ahead of it
- **AND** the documented worst-case wait is those pages, each at its own engine's per-page allowance

### Requirement: One document at a time, in submission order

Documents SHALL be read one at a time, in the order they were submitted, through the same single-worker concurrency
limit the service already enforces. The service SHALL NOT read two documents at once and SHALL NOT give any document
a second worker, because every promise the queue makes about waiting is computed against one document being read at
a time. No document SHALL overtake another for being shorter, cheaper or newer, because the queue's only promise is
pages ahead multiplied by the allowance and that promise does not survive reordering. Raising the concurrency limit
SHALL therefore be treated as a change to the queue's promise and not only as a change to a setting.

#### Scenario: Two documents submitted together

- **WHEN** two documents are submitted in quick succession
- **THEN** the second does not start being read until the first has finished
- **AND** the service's peak memory does not rise by a second document's cost

#### Scenario: Order is preserved

- **WHEN** several documents are submitted
- **THEN** they are read in the order they were submitted

#### Scenario: A short document behind a long one

- **WHEN** a one page document is submitted while a document at the page ceiling is being read
- **THEN** it waits rather than overtaking
- **AND** it is told how many pages are ahead of it
- **AND** it is never failed for having waited

### Requirement: No document reaches the worker except through the queue

Every document the service reads SHALL have been admitted through the queue and dispatched by the single consumer
that drains it. There SHALL be no second path from a request to the worker, because every statement this capability
makes about what runs at once, what waits and for how long is only true when one component decides what runs.

#### Scenario: One consumer of the worker

- **WHEN** the service's paths to the inference worker are enumerated
- **THEN** exactly one component dispatches work to it
- **AND** that component takes its input from the queue and nowhere else

#### Scenario: A submission never runs inline

- **WHEN** a document is submitted while the worker is idle and the queue is empty
- **THEN** it is still recorded, queued and dispatched by the queue's consumer
- **AND** the submitting call returns without having read any page

### Requirement: The queue and the work in it are observable to an operator

The number of documents waiting, the number of pages waiting and whether a document is currently being read SHALL be
exposed to operators through the service's existing readiness and metrics surfaces, additively, without changing the
status those surfaces already report for a service that is merely busy.

#### Scenario: An operator can tell busy from stuck

- **WHEN** the readiness surface is read while a long document is being read and others are waiting
- **THEN** it reports how many documents are waiting and that one is running
- **AND** it still reports the service as ready, because the waiting work will be served

#### Scenario: Existing readiness meaning is unchanged

- **WHEN** the readiness surface is read
- **THEN** it answers with the same status code it does today in both the ready and the not-ready case
- **AND** the fields it reported before this capability existed keep their meaning
