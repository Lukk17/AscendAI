## ADDED Requirements

### Requirement: Agent start-up tests reach the branch they name

The ascend-ai-agent unit tests SHALL reach the branch each test name describes and SHALL assert its observable result: the readiness banner line for an AscendMemory probe that answers a non-200 status, the full HTTPS address with its port when SSL is configured, and the restored interrupt flag when the vector store start-up is interrupted. Network behaviour SHALL be tested against a local JDK `HttpServer` and SHALL NOT be inferred from private fields. Every such test SHALL mark its given, when and then steps and SHALL end with an assertion.

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

### Requirement: A shared end-to-end harness scripts the model and fakes an MCP server

The ascend-ai-agent end-to-end suite SHALL have one shared harness: a scripted model that answers the OpenAI chat completion format, plain and streamed, with a fixed tool call, a fixed text or a fixed HTTP error chosen by a marker in the last user message, and that also answers the OpenAI embeddings format with deterministic vectors (owner answer 72.8 of 2026-10-06), a fake MCP server with a readable and clearable call log, which run as the containers `e2e-scripted-model` (at `http://e2e-scripted-model:3000` on the stack's network) and `e2e-fake-mcp` (at `http://e2e-fake-mcp:7032` on the stack's network), each publishing its port on the host on `127.0.0.1` only (`127.0.0.1:7033` for the scripted model, `127.0.0.1:7032` for the fake MCP server) so a spec on the host reads the two logs there, and an overlay that adds the provider `scripted` (models `e2e-scripted` and `scripted-text-only`, the second marked as having no image support) and the MCP connection `e2e-fake` to the agent only while that overlay is copied into the running agent. The overlay SHALL be plain configuration with no profile section, SHALL reach the agent only by a copy into `/app/config/application.yaml` of the running container followed by a restart, and `compose.yaml` SHALL hold no test line: no `e2e` profile, no changed `SPRING_PROFILES_ACTIVE`, no overlay mount and no `SPRING_CONFIG_ADDITIONAL_LOCATION` (owner answer 98.1 of 2026-10-08). Without the copied file the agent SHALL run with its shipped configuration and SHALL NOT know the provider `scripted`. An embeddings input that holds `E2E-EMBED <vector name>` SHALL get the fixed vector of that name, every other input SHALL get one fixed default vector orthogonal to every named vector, and the same input SHALL always get the same vector, so a deterministic spec that ingests and retrieves calls no real provider. The overlay SHALL make the scripted model the embedding endpoint of the provider `scripted`, and SHALL point the agent's semantic memory client at the AscendMemory fake that `e2e-scripted-model` serves under the route prefix `/ascend-memory/` (insert, search and the health probe), so no request of the deterministic phase reaches the real AscendMemory and no deterministic spec wipes memories (owner answer 91.1 of 2026-10-08). A deterministic check of semantic memory SHALL read the scripted model's request log under `/ascend-memory/`, never a stored memory point. The scripted model's request log and the fake's call log SHALL be readable by a spec as observable state of the fakes. The fake MCP server SHALL be one fake MCP server class of the agent's test sources, packaged as its test image and started in-process by the agent's integration tests (owner answer 91.2 of 2026-10-08), SHALL listen on port 7032 in its image, written into the image with no setting, SHALL serve the same tools on the endpoint paths `/mcp`, `/external` and `/internal`, and SHALL record the endpoint path of every call. `e2e-scripted-model` SHALL be the only HTTP fake container of the suite: every other HTTP fake SHALL be served by it from the one environment file `scripted-model.json`, under a first path segment of its own that is neither `/v1/` nor `/mockoon-admin/`, with global variables under a name prefix of its own, so the deterministic phase runs exactly the two test containers `e2e-scripted-model` and `e2e-fake-mcp`, and every Testcontainers integration test that needs an HTTP fake SHALL load the same file in its Mockoon container (owner answer 86.1 of 2026-10-08). No shipped file SHALL hold a test value of the harness: the shipped price table SHALL NOT name the provider `scripted` (owner answer 90 of 2026-10-08). The harness SHALL run only for deterministic specs: no AI-run spec SHALL run while either harness container runs or while the agent holds the copied overlay, and every run scenario SHALL run the harness specs in a phase of its own in which only the agent changes: a start step that copies the overlay into the agent and restarts it, with nothing set in a shell, followed by a check that the file is in place and readable and the agent is healthy, and an end step that removes both containers and recreates the agent from its image, which removes the copied file. AscendMemory SHALL NOT be restarted for the phase. The end step SHALL run even when a spec failed, and a check SHALL confirm that the copied file is gone, that `provider=scripted` answers 400 and that no harness container runs before the AI-run phase starts.

#### Scenario: Shipped configuration does not know the scripted provider

- **WHEN** the agent runs with no copied overlay and a prompt is sent with `provider=scripted`
- **THEN** the answer is 400 for an unknown provider

#### Scenario: The scripted model calls a fake tool on cue

- **WHEN** the overlay is copied into the running agent and the agent restarted, both harness containers run, and a prompt is sent with `provider=scripted` and the message `E2E-SCRIPT harness-smoke-read-canary`
- **THEN** the answer is 200, its content holds `ZORVEL-QUILL-7731` and `metadata.toolsUsed` holds `read_canary`
- **AND** the fake's call log holds one `read_canary` call

#### Scenario: The harness logs are read on loopback only

- **WHEN** both harness containers run
- **THEN** `GET http://127.0.0.1:7033/mockoon-admin/logs` and `GET http://127.0.0.1:7032/e2e/calls` from the host answer 200
- **AND** `docker port` shows the two ports bound to `127.0.0.1` and to no other address

#### Scenario: The fake MCP server records the endpoint path of each call

- **WHEN** `read_canary` is called once through `/external` and once through `/internal` of `http://e2e-fake-mcp:7032`
- **THEN** `GET http://127.0.0.1:7032/e2e/calls` lists two `read_canary` calls, one with the endpoint path `/external` and one with `/internal`

#### Scenario: Retrieval is scripted and stays offline

- **WHEN** the agent runs with the copied overlay, a fixture holding `E2E-EMBED harness-smoke-embed` is ingested, and a prompt with `provider=scripted` holding the same marker is sent
- **THEN** the fixture's chunk is the first retrieved chunk
- **AND** the scripted model's request log holds the embeddings requests of the ingestion and of the prompt, and no request of the run reached a real model provider

#### Scenario: A scripted model without image support refuses an image

- **WHEN** the agent runs with the copied overlay and a prompt with an image is sent with `provider=scripted` and `model=scripted-text-only`
- **THEN** the answer is 415 with the code `vision_unsupported`
- **AND** the scripted model's request log holds no chat request of that prompt

#### Scenario: Semantic memory is faked in the deterministic phase

- **WHEN** the agent runs with the copied overlay and a scripted chat turn of a spec user succeeds
- **THEN** the scripted model's request log holds the insert of that turn's memory extraction under `/ascend-memory/api/v1/memory/insert`
- **AND** the real AscendMemory holds no memory point of that user and was not restarted for the phase

#### Scenario: The end step runs after a failed spec

- **WHEN** a deterministic spec of the harness phase fails
- **THEN** the end step still removes both harness containers and recreates the agent from its image
- **AND** the end check confirms that `/app/config/application.yaml` is gone from the agent and that the agent answers `provider=scripted` with 400 before any AI-run spec starts

#### Scenario: The phase changes no compose line

- **WHEN** the harness phase has run from start to end
- **THEN** `compose.yaml` is unchanged and the agent's `SPRING_PROFILES_ACTIVE` is the shipped `docker` during and after the phase

#### Scenario: No AI-run spec meets the harness

- **WHEN** a run scenario has finished its harness phase and starts its first AI-run spec
- **THEN** neither harness container runs, the agent holds no copied overlay and its semantic memory client calls the real AscendMemory

### Requirement: Provider 429 and 502 handling is checked end to end

The ascend-ai-agent end-to-end suite SHALL check, with the scripted model and no real model, how the agent answers a provider that refuses a chat request: a provider answer of 429 SHALL reach the caller as HTTP 429 with the agent's provider error body and SHALL be sent to the provider exactly once, and a provider answer of 502 SHALL be retried, so a provider that recovers on the next attempt gives the caller its answer. The checks SHALL read the scripted model's request log to count the chat requests the agent sent, never a log line of the agent. A memory extraction request, which carries the system prompt of `SemanticMemoryExtractor`, SHALL NOT be counted.

#### Scenario: Provider answers 429

- **WHEN** a prompt is sent with `provider=scripted` and the message `E2E-SCRIPT-HTTP-429`
- **THEN** the answer is HTTP 429 with the message `AI provider error: 429 -`
- **AND** the scripted model's request log holds exactly one chat request with that marker

#### Scenario: Provider answers 502 once and then recovers

- **WHEN** a prompt is sent with `provider=scripted` and the message `E2E-SCRIPT-HTTP-502`, and the scripted model answers 502 to the first request and `E2E-SCRIPT-RECOVERED` to the next
- **THEN** the answer is 200 and its content holds `E2E-SCRIPT-RECOVERED`
- **AND** the scripted model's request log holds exactly two chat requests with that marker, not counting the memory extraction request that follows the successful turn
