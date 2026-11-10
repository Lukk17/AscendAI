## REMOVED Requirements

### Requirement: Vision-capability check for image-bearing prompts

**Reason**: It says a non-vision model with an image answers HTTP 400, and its scenario is named "Non-vision model rejected with 400". The code answers 415 with the code `vision_unsupported`. A MODIFIED block cannot drop or rename a scenario, so the requirement is removed and re-added whole as "Vision-capability check answers 415 for image-bearing prompts" below, with the same allowlist check, the same vision-capable scenario and the status the code answers.

**Migration**: Nothing changes in the code. `PromptController` already answers 415. A client that expected 400 for this refusal reads 415 and the problem body code `vision_unsupported` (capability `agent-error-responses`).

## ADDED Requirements

### Requirement: Vision-capability check answers 415 for image-bearing prompts

When a request to `/api/v1/ai/prompt` includes an `image` part, the agent SHALL verify that the selected `(provider, model)` is in the configured vision-capable allowlist (`app.ai.vision.providers`). If not, the agent SHALL return HTTP 415 with an `application/problem+json` body whose `code` is `vision_unsupported` (capability `agent-error-responses`) and whose `detail` says the model does not support image input, and SHALL NOT forward the request to the model.

#### Scenario: Vision-capable model accepts image

- **WHEN** the user posts with `provider=lmstudio`, `model=qwen/qwen3-vl-4b`, and an image
- **THEN** the request proceeds and a description is returned

#### Scenario: Non-vision model rejected with 415

- **WHEN** the user posts with `provider=minimax`, `model=MiniMax-M2.7-text-only`, and an image
- **THEN** the controller returns HTTP 415 with `Content-Type: application/problem+json`
- **AND** the body has `code` `vision_unsupported` and a `detail` containing `does not support image input`
- **AND** no LLM call is made
