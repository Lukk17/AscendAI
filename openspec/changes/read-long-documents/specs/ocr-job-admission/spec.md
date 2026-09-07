## Purpose

Decides which documents the service takes on for later collection and which it refuses, so that one worker serving
one job at a time is never handed more work than it can finish or more waiting work than it can promise a time for.

## ADDED Requirements

### Requirement: Work accepted for later collection has its own page ceiling, derived from memory

The service SHALL refuse a document submitted for later collection whose page count exceeds a configured ceiling.
That ceiling SHALL be configurable and its default SHALL be derived from the measured memory cost of reading a
document against a stated resident budget, not from a time limit, because no caller is holding a connection against
this work and time is therefore not what binds it. The refusal SHALL use the service's existing oversized-input
error code, SHALL name the document's page count and the ceiling, and SHALL happen before any page is read.

#### Scenario: Document above the job page ceiling

- **WHEN** a document with more pages than the ceiling is submitted for later collection
- **THEN** the service refuses it with the existing oversized-input code
- **AND** the refusal names the document's page count and the ceiling
- **AND** no page of it is read and no worker is occupied

#### Scenario: Document at the job page ceiling

- **WHEN** a document with exactly the ceiling's page count is submitted for later collection
- **THEN** it is accepted

#### Scenario: The ceiling is a memory statement

- **WHEN** the configured ceiling is read together with the documented memory model
- **THEN** the documentation states the resident budget the default was derived from and the per-page cost it used
- **AND** raising the ceiling is described as a memory decision rather than a throughput one

### Requirement: Work that provably cannot finish is still refused up front

The ceiling on how long submitted work may spend reading SHALL be derived from the job page ceiling multiplied by
the per-page allowance, rather than configured independently, so that a document at the page ceiling always has
exactly enough budget to be read and no accepted document can be one that provably cannot finish. Accepting work
that cannot finish occupies the only worker for the whole ceiling and tells the caller nothing until it expires.

#### Scenario: The two ceilings cannot disagree

- **WHEN** the job page ceiling or the per-page allowance is changed
- **THEN** the reading ceiling changes with them
- **AND** a document at the page ceiling still has the full per-page allowance available for every one of its pages

#### Scenario: Every accepted document can finish

- **WHEN** any document is accepted for later collection
- **THEN** its page count multiplied by the per-page allowance is within the reading ceiling

### Requirement: Every existing input guard applies identically to work accepted for later collection

The pixel ceiling on one inference, the decode-time bomb guard, the byte size limit and the file type check SHALL
apply to a document submitted for later collection exactly as they apply to a synchronous request, with the same
error codes and the same detail, and SHALL be applied at submission time rather than when reading starts. A
submission the synchronous path would refuse for any reason other than its page count SHALL be refused here too.

#### Scenario: Oversized page submitted for later collection

- **WHEN** a document whose page exceeds the pixel ceiling is submitted for later collection
- **THEN** it is refused at submission with the same error code the synchronous path uses
- **AND** no work is queued for it

#### Scenario: Unsupported file type submitted for later collection

- **WHEN** a file whose type the service does not support is submitted for later collection
- **THEN** it is refused at submission with the existing unsupported-type code

#### Scenario: Refusal happens before anything is queued

- **WHEN** a submission is refused by any input guard
- **THEN** no identifier is issued for it
- **AND** the queue is unchanged

### Requirement: The queue is bounded in pages and in documents

The service SHALL bound how much work may be waiting at once, both as a total number of pages across everything
waiting and as a number of waiting documents. Both bounds SHALL be configurable. The page bound exists because it is
what makes the wait predictable: the longest a newly accepted submission can wait is the pages already waiting
multiplied by the per-page allowance. The document bound exists because the service holds each waiting submission's
bytes until it runs, so the count is what bounds that storage. A submission that would exceed either bound SHALL be
refused with a distinct queue-full code and a status that tells the caller to try again later, rather than being
accepted into an unbounded wait.

#### Scenario: Page bound reached

- **WHEN** a submission would push the total pages waiting above the page bound
- **THEN** the service refuses it with the queue-full code
- **AND** the refusal tells the caller it can be retried later

#### Scenario: Document bound reached

- **WHEN** a submission would push the number of waiting documents above the document bound, even though the pages
  waiting are within the page bound
- **THEN** the service refuses it with the same queue-full code

#### Scenario: Refusal is temporary and self-clearing

- **WHEN** a submission is refused because the queue is full and waiting work then completes
- **THEN** an identical submission made afterwards is accepted
- **AND** no operator action was needed in between

#### Scenario: The promise the bound makes

- **WHEN** a submission is accepted while the queue holds some number of pages
- **THEN** the service reports how many pages are ahead of it
- **AND** the documented worst-case wait is those pages multiplied by the per-page allowance

### Requirement: One job at a time, in submission order, sharing the worker with synchronous requests

Work accepted for later collection SHALL be read one document at a time, in the order it was submitted, through the
same single-worker concurrency limit that governs synchronous requests. The service SHALL NOT read two documents at
once, and SHALL NOT give work accepted for later collection a second worker, because the memory ceiling is one job's
cost multiplied by the worker count. A synchronous request that arrives while such work is running SHALL wait on the
existing admission gate and SHALL fail on its own budget if the wait exhausts it, exactly as it does behind another
synchronous request.

#### Scenario: Two documents submitted for later collection

- **WHEN** two documents are submitted for later collection in quick succession
- **THEN** the second does not start being read until the first has finished
- **AND** the peak memory of the service does not rise by a second job's cost

#### Scenario: Order is preserved

- **WHEN** several documents are submitted for later collection
- **THEN** they are read in the order they were submitted

#### Scenario: A synchronous request behind a long job

- **WHEN** a synchronous request arrives while a long document is being read
- **THEN** it waits on the same admission gate as any other request
- **AND** it fails with the existing OCR failure code when its own budget expires, with no page read for it

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
