## ADDED Requirements

### Requirement: A command inside a service with several copies names the compose service

A spec, template, README step or permission allowlist entry that runs a command inside ascend-web-hunter, or reads its
logs, SHALL use the compose form (`docker compose exec`, `docker compose cp`, `docker compose logs`, `docker compose ps`)
with the service name `ascend-web-hunter`, and `--index <n>` when it must reach one copy, never a container name. Every
such command SHALL run against the main compose file with no `-f` flag.

#### Scenario: A reviewer searches the suites

- **WHEN** a reviewer searches the e2e suites, their templates and the allowlist section for a `docker exec`, `docker cp`,
  `docker logs` or `docker inspect` that names `ascend-web-hunter`
- **THEN** none is found outside `e2e/testing/runs/`

#### Scenario: A step aimed at one copy

- **WHEN** a step must act on the second of two copies
- **THEN** it uses `docker compose exec --index 2 ascend-web-hunter <command>`
