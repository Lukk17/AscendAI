## ADDED Requirements

### Requirement: HTTP-upload ingestion is idempotent

When a user re-uploads a document with the same sanitized filename via `POST /api/ingestion/upload`, the agent SHALL replace prior chunks for that source rather than appending duplicates. Implementation SHALL reuse `documentService.removeOldDocuments(source=<sanitized-filename>)` (the same dedup path used by `ManualIngestionService`).

#### Scenario: Same document uploaded twice

- **WHEN** the user uploads `notes.md` and then uploads a second version of `notes.md`
- **THEN** the Qdrant collection contains chunks corresponding only to the latest upload
- **AND** the count of points with `metadata.source == "notes.md"` equals the chunk count of the latest version (not the sum)

#### Scenario: Different document, same prefix

- **WHEN** the user uploads `notes.md` and then `notes-v2.md`
- **THEN** chunks for `notes.md` are preserved
- **AND** chunks for `notes-v2.md` are added independently

### Requirement: Vision-capability check for image-bearing prompts

When a request to `/api/v1/ai/prompt` includes an `image` part, the agent SHALL verify that the selected `(provider, model)` is in the configured vision-capable allowlist (`app.ai.vision.providers`). If not, the agent SHALL return HTTP 400 with a clear message and SHALL NOT forward the request to the model.

#### Scenario: Vision-capable model accepts image

- **WHEN** the user posts with `provider=lmstudio`, `model=qwen/qwen3-vl-4b`, and an image
- **THEN** the request proceeds and a description is returned

#### Scenario: Non-vision model rejected with 400

- **WHEN** the user posts with `provider=minimax`, `model=MiniMax-M2.7-text-only`, and an image
- **THEN** the controller returns HTTP 400 with body containing `does not support image input`
- **AND** no LLM call is made

### Requirement: Unstructured base URL works for both host and container deployments

The default `app.unstructured.base-url` and the docker-profile override SHALL each work in their respective deployment mode without manual editing. The `application-docker.yaml` profile SHALL set the URL to the docker-network service name (e.g., `http://ascend-unstructured:9080`); the default profile SHALL keep `http://localhost:9080`. Boot logs SHALL include the resolved URL so misconfiguration is visible.

#### Scenario: Host-mode boot

- **WHEN** AscendAgent runs as `./gradlew bootRun` against docker-compose services
- **THEN** the resolved Unstructured URL is `http://localhost:9080` and ingestion works for a DOCX upload

#### Scenario: Container-mode boot

- **WHEN** AscendAgent runs inside docker-compose with profile `docker`
- **THEN** the resolved URL uses the docker-network service name and ingestion works
