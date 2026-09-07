## ADDED Requirements

### Requirement: Prompt bodies never appear in AscendAgent logs

AscendAgent SHALL NOT write user prompt text or attached document content to any log output. The `PromptController` request log line SHALL carry the prompt length in characters and the SHA-256 hex digest of the prompt instead of the body. This SHALL hold at every log level active in the shipped `application.yaml` and `application-docker.yaml` profiles.

#### Scenario: Request log line is redacted

- **WHEN** `POST /api/v1/ai/prompt` is called with prompt `my secret quarterly numbers are 42`
- **THEN** the emitted log line contains the prompt length and SHA-256 digest
- **AND** the string `secret quarterly numbers` appears in no log output

### Requirement: Docker profile disables content-emitting DEBUG levels

`application-docker.yaml` SHALL contain a `logging.level` block setting `org.springframework.ai` and the application package `com.lukk.ascend.ai.agent` to `INFO` (or stricter), so that Spring AI's DEBUG-level request/response logging cannot ship prompt or completion content to stdout — and therefore to Loki — in the container posture. The stale `com.lukk.ai.agent` logger entry in the base `application.yaml` (which does not match the actual package) SHALL be corrected to the real package name.

#### Scenario: Container posture logs no model payloads

- **WHEN** AscendAgent runs with the `docker` profile and processes a chat request
- **THEN** the effective log level for `org.springframework.ai` is `INFO`
- **AND** no model request or response body appears on stdout

#### Scenario: Stale logger name corrected

- **WHEN** `AscendAgent/src/main/resources/application.yaml` is read
- **THEN** its `logging.level` block references `com.lukk.ascend.ai.agent` and contains no `com.lukk.ai.agent` entry

### Requirement: Platform-wide redaction convention covers all six services

A written redaction convention SHALL be documented (in `docs/COMPLIANCE.md`) and applied across AscendAgent, WeatherMCP, ascend-audio-scribe, ascend-web-hunter, AscendMemory, and PaddleOCR: user-supplied content — prompts, documents, transcripts, memory text, scraped page content, OCR output — is never passed as a log argument; logs carry lengths, counts, hashes, and identifiers instead. Each Python service's `[ServiceName]`-prefixed logging SHALL be audited against the convention as part of this change and any content leakage fixed.

#### Scenario: Python service logs metadata, not content

- **WHEN** AscendMemory inserts a memory or ascend-audio-scribe completes a transcription
- **THEN** the emitted log lines identify the operation, user id, and sizes or durations
- **AND** the memory text or transcript content appears in no log line

#### Scenario: Convention is documented

- **WHEN** `docs/COMPLIANCE.md` is read
- **THEN** it contains the redaction convention with concrete allowed/forbidden log-argument examples applicable to all six services
