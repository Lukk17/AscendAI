## ADDED Requirements

### Requirement: ascend-web-hunter runs as several copies of one compose service

The `ascend-web-hunter` service of the development compose file and of the standalone bundle SHALL declare no fixed
container name, no fixed host name and no published host port. The number of its copies SHALL come from one setting,
`WEB_HUNTER_REPLICAS`, with the default 1. Each copy SHALL have its short container ID as host name. Every other service
of both files SHALL keep its fixed container name.

#### Scenario: Default count

- **WHEN** the stack starts with `WEB_HUNTER_REPLICAS` unset
- **THEN** exactly one `ascend-web-hunter` container runs
- **AND** its host name is 12 lower case hexadecimal characters

#### Scenario: Two copies

- **WHEN** the stack starts with `WEB_HUNTER_REPLICAS=2`
- **THEN** two `ascend-web-hunter` containers run and both report healthy
- **AND** their host names differ

#### Scenario: Both files have the same shape

- **WHEN** a reviewer reads the `ascend-web-hunter` service of the development compose file and of the standalone bundle
- **THEN** neither declares `container_name`, `hostname` or `ports`
- **AND** both read the count from `WEB_HUNTER_REPLICAS` with the default 1

### Requirement: One edge proxy is the entry point of every copy

A service `ascend-web-hunter-edge` SHALL be the only service that publishes port 7021, on `127.0.0.1` in the
development stack and on every interface in the standalone bundle. Its host port SHALL be the setting
`WEB_HUNTER_HOST_PORT` with the default 7021, and its container port SHALL stay 7021. It SHALL spread requests over every running copy
found under the compose service name, SHALL pass the caller's `Host` header unchanged, SHALL write the caller's address
into `X-Forwarded-For`, and SHALL keep serving when a copy is added or removed. Its configuration SHALL be the same bytes
in both files. How often it looks up the copies and how long it tries other copies for one request SHALL be the settings
`WEB_HUNTER_EDGE_DNS_REFRESH_SECONDS` and `WEB_HUNTER_EDGE_TRY_DURATION_SECONDS`, each with the default 5 seconds.

#### Scenario: The edge waits are settings

- **WHEN** the stack starts with `WEB_HUNTER_EDGE_TRY_DURATION_SECONDS` unset and then with it set to 9
- **THEN** the edge proxy tries other copies for one request for 5 seconds in the first case
- **AND** for 9 seconds in the second case

#### Scenario: Requests reach every copy

- **WHEN** two copies run and a caller sends several requests to port 7021 of the host
- **THEN** each request is answered as without the proxy
- **AND** each copy has answered at least one of them

#### Scenario: A copy that stops

- **WHEN** one of two copies is stopped while requests arrive
- **THEN** the requests are answered by the other copy

#### Scenario: Same configuration in both files

- **WHEN** a reviewer compares the edge configuration of the development stack with the one of the standalone bundle
- **THEN** the two files are byte identical

### Requirement: Every copy shares the service's state

With several copies, every behaviour that depends on state SHALL answer the same whichever copy serves the request: an
MCP call needs no session held by one copy, a caller's rate limit budget is one budget for the whole service, a NoVNC
flow opened on one copy is joined from another, a crawl page is read once, a session clear on one copy drops the cached
reads of that site on every copy, and one retention sweep round deletes an expired download once.

#### Scenario: One check proves all of them together

- **WHEN** the two copy part of the concurrent interventions e2e spec runs
- **THEN** every behaviour of this requirement is observed through HTTP answers, per copy metrics and Redis keys
- **AND** no assertion reads a log line
