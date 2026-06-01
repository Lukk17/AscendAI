# Image description: e2e test

## What this verifies

- An attached image is accepted by the prompt endpoint.
- The image bytes reach a vision-capable model.
- The response describes the actual subject of the image, not a generic placeholder.

## Prerequisites

Check Bruno CLI is installed.

```bash
bru --version
```

Expect a version string. If the command is not found, install it with `npm install -g @usebruno/cli`.

Check the AscendAgent health endpoint.

```bash
curl -fsS http://localhost:9917/actuator/health
```

Expect HTTP 200 with `{"status":"UP"}`.

Check the fixture image exists.

```bash
ls AscendAgent/e2e/fixtures/image.png
```

Expect the file path to print.

## Reset state

None. This test does not write persisted state.

## Run

Send the Bruno request and wait for the response before moving to the Expected section.

```bash
cd docs/api/request/AscendAI && bru run "ascend-agent/testing/image-description-prompt.yml" --env ascend-local
```

## Expected

The Bruno output shows HTTP 200.

The response body's `content` field is a detailed description (more than a few sentences) that references concrete visual features of `AscendAgent/e2e/fixtures/image.png`: specific subjects, colors, objects, or text in the image.

The response body's `content` field is NOT a refusal like "I don't see an image" or "I'm unable to view images". Those indicate the bytes did not reach the model.

## Fixtures

- `AscendAgent/e2e/fixtures/image.png`: pick something with one obvious correct answer (a specific subject, a unique logo, an annotated chart) so the description can be visually verified.

## Concurrency

- **Mutates:** Postgres `chat_history` (user_id=`frostyImageDescriptionTest`); Redis key `chat:frostyImageDescriptionTest`
- **Conflicts with:** none
- **Serial:** false
