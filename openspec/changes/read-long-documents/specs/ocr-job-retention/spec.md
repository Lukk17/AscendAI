## Purpose

Says how long a completed result lives, who removes it, and what happens to work that was in flight when the service
stopped, so that forty minutes of reading is not lost to a restart and a document's text does not accumulate on the
service's storage forever.

## ADDED Requirements

### Requirement: A completed result is kept for a bounded window and then removed by the service

The service SHALL keep a completed result for a configurable retention window measured from the moment the work
finished, and SHALL remove it once that window has passed, without an operator or a caller having to ask. The
default window SHALL be long enough that a caller whose polling stopped can restart it and still collect the result,
and the documentation SHALL state what the window costs, which is that a document's extracted text remains on the
service's storage for that long.

#### Scenario: Result inside the retention window

- **WHEN** a completed result is read at any point before its retention window has passed
- **THEN** the service returns it

#### Scenario: Result after the retention window

- **WHEN** the retention window for a completed result has passed
- **THEN** the service has removed it within a bounded time of the window ending
- **AND** reading its identifier reports that the identifier is unknown or expired

#### Scenario: Removal needs nobody

- **WHEN** results pass their retention window while no caller reads anything and no operator acts
- **THEN** they are still removed

### Requirement: A caller can remove its own result immediately

A caller holding an identifier SHALL be able to remove the work and its result at any time, before or after it has
finished, without waiting for the retention window. A result holds the document's own text, so a caller that no
longer needs it SHALL NOT have to leave it on the service.

#### Scenario: Removing a finished result early

- **WHEN** a caller removes finished work
- **THEN** the result is gone immediately
- **AND** reading its identifier reports that the identifier is unknown or expired

#### Scenario: Removing work twice

- **WHEN** a caller removes work it has already removed
- **THEN** the service answers with its not-found code rather than an error that suggests something went wrong

### Requirement: Retained work is bounded in count as well as in time

The number of finished records the service retains SHALL be bounded by a configurable limit, and when that limit is
reached the oldest finished record SHALL be removed first. The retention window alone does not bound storage,
because many small documents can finish inside one window, so the count bound is what makes the storage the service
holds a stated number rather than an open one.

#### Scenario: More finished work than the limit

- **WHEN** more work finishes inside a retention window than the count limit allows
- **THEN** the oldest finished records are removed first
- **AND** the number retained never exceeds the limit

#### Scenario: Eviction does not touch unfinished work

- **WHEN** the count limit is reached while other work is waiting or running
- **THEN** only finished records are removed
- **AND** no waiting or running work is lost

### Requirement: A completed result survives a restart of the service

A result that was complete before the service stopped SHALL still be readable by its identifier after the service
starts again, for the remainder of its retention window, provided the service's storage was not itself discarded.
Reading a document is expensive enough that losing a finished result to an ordinary restart is not acceptable, and
the documentation SHALL state plainly which kinds of restart preserve the storage and which do not.

#### Scenario: Reading a result after a restart

- **WHEN** work finishes, the service is restarted, and the identifier is read afterwards
- **THEN** the result is returned as before the restart
- **AND** its retention window is measured from when it finished, not from the restart

### Requirement: Work in flight when the service stopped is failed, not left hanging

Work that was waiting or running when the service stopped SHALL be reported as finished unsuccessfully once the
service starts again, with a distinct reason that identifies the restart as the cause and marks the work as safe to
resubmit. The service SHALL NOT restart such work by itself, because it cannot know whether the document being read
is what brought the service down. A caller SHALL NOT be left polling work that nothing will ever finish.

#### Scenario: Running work at the moment of a restart

- **WHEN** the service is restarted while a document is being read and the identifier is read afterwards
- **THEN** the state reports failure with the restart as its reason
- **AND** the reason distinguishes it from a document the service could not read, so a caller knows resubmitting is
  worthwhile

#### Scenario: Waiting work at the moment of a restart

- **WHEN** the service is restarted while documents are waiting and their identifiers are read afterwards
- **THEN** each reports the same restart failure
- **AND** none of them is read after the restart without being submitted again

#### Scenario: Nothing is left in a non-terminal state

- **WHEN** every identifier the service holds is read after a restart
- **THEN** none of them reports waiting or running unless it was submitted after the restart

### Requirement: Storage the service works in is reclaimed on the same terms as the work it holds

Temporary storage the service uses while reading a document SHALL be reclaimed on a horizon derived from the longest
work the service accepts, rather than from the synchronous request ceiling, so that a legitimately long piece of work
never has its own working files removed while it is still using them. Storage left behind by a worker that was killed
SHALL still be reclaimed as it is today, and the bytes of a submission that is removed or that finishes SHALL be
removed with it.

#### Scenario: Long work keeps its working files

- **WHEN** a document is being read for longer than the synchronous request ceiling
- **THEN** the files that reading needs are not reclaimed while it runs

#### Scenario: Files of finished work

- **WHEN** work finishes, successfully or not, or is removed by a caller
- **THEN** the submitted bytes it was holding are removed
- **AND** only the record and, on success, the result remain until the retention window ends

#### Scenario: Files left by a killed worker

- **WHEN** the worker reading a document is killed and a fresh worker becomes available
- **THEN** the working files that worker left behind are reclaimed, as they are today
- **AND** nothing older than the longest work the service accepts remains
