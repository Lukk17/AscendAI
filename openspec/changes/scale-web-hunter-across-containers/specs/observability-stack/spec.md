## ADDED Requirements

### Requirement: Prometheus scrapes every ascend-web-hunter copy

Prometheus SHALL find the ascend-web-hunter targets through DNS on the compose service name, port 7021, and SHALL scrape
each running copy as its own target, labelled `service="ascend-web-hunter"` and with its own `instance`.

#### Scenario: Two copies

- **WHEN** two copies run
- **THEN** the Prometheus target list shows two `ascend-web-hunter` targets with health `up` and different `instance`
  labels

#### Scenario: Back to one copy

- **WHEN** the count goes back to one
- **THEN** the target list shows one `ascend-web-hunter` target after the next DNS refresh
