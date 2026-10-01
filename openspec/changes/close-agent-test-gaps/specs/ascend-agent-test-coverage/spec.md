## ADDED Requirements

### Requirement: Agent start-up and provider wiring tests reach the branch they name

The ascend-ai-agent unit tests SHALL reach the branch each test name describes and SHALL assert its observable result: the readiness banner line for an AscendMemory probe that answers a non-200 status, the full HTTPS address with its port when SSL is configured, the restored interrupt flag when the vector store start-up is interrupted, and the HTTP version and read timeout that a provider's request factory puts on the wire. Network behaviour SHALL be tested against a local JDK `HttpServer` and SHALL NOT be inferred from private fields. Every such test SHALL mark its given, when and then steps and SHALL end with an assertion.

#### Scenario: AscendMemory answers 500

- **WHEN** the readiness banner is built while the AscendMemory probe answers `500`
- **THEN** the AscendMemory banner line shows the non-200 outcome, not the connection refused outcome

#### Scenario: SSL banner shows the port

- **WHEN** the readiness banner is built with SSL configured and port `9917`
- **THEN** the banner contains `https://localhost:9917`

#### Scenario: Interrupted vector store start-up keeps the interrupt

- **WHEN** listing Qdrant collections throws `InterruptedException` during start-up
- **THEN** the start-up does not fail
- **AND** the thread's interrupt flag is set afterwards

#### Scenario: Provider that requires HTTP/1.1

- **WHEN** a provider configured with `requiresHttp1 = true` sends a request to a local server
- **THEN** the server records protocol `HTTP/1.1`

#### Scenario: Provider read timeout

- **WHEN** a provider configured with a 1-second timeout calls a server that waits 3 seconds
- **THEN** the call fails with a timeout before the server answers
