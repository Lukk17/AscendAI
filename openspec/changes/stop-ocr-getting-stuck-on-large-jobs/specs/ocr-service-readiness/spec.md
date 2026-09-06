## Purpose

Makes the difference between "the process is alive" and "the service can take work" observable, so that the one
state in which the service cannot accept a request is the one state in which it says so.

## ADDED Requirements

### Requirement: Liveness answers independently of OCR work

The liveness endpoint SHALL report the API process as alive whenever that process can answer, and SHALL NOT depend
on the state of any inference worker, any in-flight job, or any queue. A stuck or absent inference worker SHALL NOT
make liveness fail, because the correct response to that condition is to replace the worker rather than to restart
the container and lose the warm engine and every queued request with it.

#### Scenario: Liveness while a job is stuck

- **WHEN** the inference worker is occupied by a job past its budget
- **THEN** the liveness endpoint still reports the process as alive

#### Scenario: Liveness while a worker is being replaced

- **WHEN** the inference worker is being replaced
- **THEN** the liveness endpoint still reports the process as alive

### Requirement: Readiness reports whether the service can take work

The readiness endpoint SHALL report the service as ready only when it is both warmed up and able to take work. It
SHALL report not-ready when the engine has never warmed, when the worker pool is unusable, when a worker is being
replaced, or when the in-flight job is past its budget and has not yet been reclaimed. Readiness SHALL keep its
existing response shape and SHALL keep answering with a success status in both states, with the ready or not-ready
condition carried in the body, so existing consumers are unaffected.

#### Scenario: Occupied by a job past its budget

- **WHEN** the only worker is occupied by a job whose budget has expired and which has not yet been reclaimed
- **THEN** readiness reports not-ready

#### Scenario: Worker being replaced

- **WHEN** a worker replacement is in progress
- **THEN** readiness reports not-ready
- **AND** readiness reports ready again once the replacement has warmed up

#### Scenario: Engine never warmed

- **WHEN** the engine has not completed a warm-up
- **THEN** readiness reports not-ready, as it does today

#### Scenario: Response shape and status are unchanged

- **WHEN** readiness is polled in any of the states above
- **THEN** the endpoint answers with the same success status it answers with today
- **AND** the existing fields of the readiness body are unchanged

### Requirement: Readiness distinguishes busy from unable

Being busy with a job that is still inside its budget SHALL NOT make the service report not-ready, because a
request arriving then will be served. The readiness body SHALL expose enough detail for an operator to tell a busy
service from a stuck one, specifically whether the service is currently accepting work and how many requests are
waiting.

#### Scenario: Busy with a healthy job

- **WHEN** a job is running and is still inside its budget
- **THEN** readiness reports ready
- **AND** the body shows that the service is accepting work

#### Scenario: Operator distinguishes busy from stuck

- **WHEN** readiness is polled while requests are queued behind a healthy job
- **THEN** the body reports the number of requests waiting
- **AND** the same field set makes the stuck case, where the service is not accepting work, distinguishable from it
