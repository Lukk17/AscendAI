# ocr-service-readiness Specification

## Purpose
Makes the difference between "the process is alive" and "the service can take work" observable, so that the one
state in which the service cannot accept a request is the one state in which it says so.

## Requirements

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

#### Scenario: Liveness while no worker exists at all

- **WHEN** the inference process has died and has not yet been rebuilt
- **THEN** the liveness endpoint still reports the process as alive
- **AND** readiness is the endpoint that reports the condition

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

### Requirement: Readiness answers 503 whenever the service cannot take work

Readiness SHALL report ready only when warmed up and able to take work. It SHALL report not-ready when the engine never warmed, the pool is unusable, a worker is being replaced, or the in-flight job passed its budget unreclaimed. It SHALL use the shared `python-service-platform` body: HTTP 200 `ready` when ready, HTTP 503 `not-ready` when not. `checks` SHALL hold `engine` with `warm`, `worker_pool` with `accepting_work`, and `jobs` with `queued` and `running`.

#### Scenario: Occupied by a job past its budget

- **WHEN** the only worker is occupied by a job whose budget has expired and which has not yet been reclaimed
- **THEN** readiness answers HTTP 503 with `status` `not-ready`

#### Scenario: Worker being replaced

- **WHEN** a worker replacement is in progress
- **THEN** readiness answers HTTP 503 with `status` `not-ready`
- **AND** readiness answers HTTP 200 with `status` `ready` again once the replacement has warmed up

#### Scenario: Engine never warmed

- **WHEN** the engine has not completed a warm-up
- **THEN** readiness answers HTTP 503 with `status` `not-ready` and `checks.engine.warm` false

#### Scenario: Pool unusable and recovering

- **WHEN** the inference process has died and the pool is unusable
- **THEN** readiness answers HTTP 503 for as long as the service cannot take work
- **AND** readiness answers HTTP 200 again once the pool has been rebuilt, without the container being restarted

#### Scenario: Rebuilding has given up

- **WHEN** the service has stopped rebuilding after repeated failures
- **THEN** readiness answers HTTP 503 and continues to do so until the service is restarted

#### Scenario: Shared body shape

- **WHEN** readiness is polled in any of the states above
- **THEN** the body holds `status`, `service` `ascend-ocr`, `version` and `checks` with `engine`, `worker_pool` and `jobs`
