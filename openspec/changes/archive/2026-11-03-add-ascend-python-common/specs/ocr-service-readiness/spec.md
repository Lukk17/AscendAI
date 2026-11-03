# Spec Delta

## REMOVED Requirements

### Requirement: Readiness reports whether the service can take work

**Reason**: Its scenario "Response shape and status are unchanged" pins HTTP 200 in both states and the old body. The four Python services now share one readiness contract (`python-service-platform`, "Health, readiness and metrics have one shape"), which answers 503 when not ready. OpenSpec does not let a MODIFIED block drop or rename a scenario, so the requirement is removed and added again below under a new name with the same conditions.

**Migration**: A consumer that read `status` from a 200 body reads the HTTP status or the same `status` field, whose values stay `ready` and `not-ready`. The fields `engine_warm`, `accepting_work`, `jobs_queued` and `jobs_running` move under `checks` as described in the requirement "Readiness answers 503 whenever the service cannot take work". No consumer in this repository reads `/ready` of ascend-ocr (checked with `git grep -n "/ready"` over `apps/ascend-agent/src`, both compose files and `infra` on 2026-10-03).

## ADDED Requirements

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
