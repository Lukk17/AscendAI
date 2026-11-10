# Spec Delta

## MODIFIED Requirements

### Requirement: The queue is bounded in pages and in documents

The service SHALL bound how much work may be waiting at once, both as a total number of pages across everything
waiting and as a number of waiting documents. Both bounds SHALL be configurable. Both bounds SHALL hold for the whole
service, counted across every running container of it, never once per container. The page bound exists because it is
what makes the wait predictable: the longest a newly accepted submission can wait is the pages already waiting,
each multiplied by the per-page allowance of the engine that will read it. The page bound SHALL NOT be configurable below the page ceiling, because a
single maximal document could then never be queued. The document bound exists because the service holds each waiting
submission's bytes until it runs, so the count is what bounds that storage. A submission that would exceed either
bound SHALL be refused with a distinct queue-full code and a status that tells the caller to try again later, rather
than being accepted into an unbounded wait. Two submissions that reach two containers at the same moment SHALL NOT
both be admitted when together they exceed a bound.

#### Scenario: Page bound reached

- **WHEN** a submission would push the total pages waiting above the page bound
- **THEN** the service refuses it with the queue-full code
- **AND** the refusal tells the caller it can be retried later

#### Scenario: Document bound reached

- **WHEN** a submission would push the number of waiting documents above the document bound, even though the pages
  waiting are within the page bound
- **THEN** the service refuses it with the same queue-full code

#### Scenario: The bound holds across containers

- **WHEN** the queue holds one document less than the document bound and two containers each receive a submission at
  the same moment
- **THEN** exactly one of the two submissions is accepted
- **AND** the other is refused with the queue-full code

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

Each container of the service SHALL read documents one at a time, through the same single-worker concurrency limit the
service already enforces, and every container SHALL take its next document from the one queue the whole service
shares, in the order the documents were submitted to any container. A container SHALL NOT read two documents at once
and SHALL NOT give any document a second worker, and no document SHALL be read by two containers. No document SHALL
overtake another for being shorter, cheaper or newer, because the queue's only promise is pages ahead multiplied by the
allowance and that promise does not survive reordering. With several containers the promise is an upper bound, because
each container takes the next document as soon as its own worker is free. Raising the concurrency limit of a container
SHALL therefore be treated as a change to the queue's promise and not only as a change to a setting.

#### Scenario: Two documents submitted together

- **WHEN** one container runs and two documents are submitted to it in quick succession
- **THEN** the second does not start being read until the first has finished
- **AND** the container's peak memory does not rise by a second document's cost

#### Scenario: Order is preserved

- **WHEN** several documents are submitted, some to one container and some to another
- **THEN** reading of each document starts in the order the documents were submitted
- **AND** no document is read by more than one container

#### Scenario: A short document behind a long one

- **WHEN** a one page document is submitted while a document at the page ceiling is being read and no other container
  has a free worker
- **THEN** it waits rather than overtaking
- **AND** it is told how many pages are ahead of it
- **AND** it is never failed for having waited

### Requirement: No document reaches the worker except through the queue

Every document the service reads SHALL have been admitted through the one shared queue and dispatched by the single
consumer of the container that reads it. There SHALL be no second path from a request to a worker, because every
statement this capability makes about what runs at once, what waits and for how long is only true when one component
per container decides what that container runs and the shared queue decides the order.

#### Scenario: One consumer of the worker

- **WHEN** a container's paths to its inference worker are enumerated
- **THEN** exactly one component dispatches work to it
- **AND** that component takes its input from the shared queue and nowhere else

#### Scenario: A submission never runs inline

- **WHEN** a document is submitted while the worker is idle and the queue is empty
- **THEN** it is still recorded, queued and dispatched by a queue consumer
- **AND** the submitting call returns without having read any page

### Requirement: The queue and the work in it are observable to an operator

The number of documents waiting, the number of pages waiting and the number of documents being read SHALL be exposed
to operators through the service's existing readiness and metrics surfaces, additively, without changing the status
those surfaces already report for a service that is merely busy. These counts SHALL describe the whole service, so
every container reports the same counts at the same moment.

#### Scenario: An operator can tell busy from stuck

- **WHEN** the readiness surface is read while a long document is being read and others are waiting
- **THEN** it reports how many documents are waiting and how many are running
- **AND** it still reports the service as ready, because the waiting work will be served

#### Scenario: Every container reports the same queue

- **WHEN** two containers run, a document is being read by one of them and two documents wait, and the readiness
  surface of each container is read
- **THEN** both report two documents waiting and one running

#### Scenario: Existing readiness meaning is unchanged

- **WHEN** the readiness surface is read
- **THEN** it answers with the same status code it does today in both the ready and the not-ready case
- **AND** the fields it reported before this capability existed keep their meaning
