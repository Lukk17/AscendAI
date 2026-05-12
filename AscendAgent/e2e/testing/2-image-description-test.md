# Image description — e2e test

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

The Bruno output shows HTTP 200 and a response body whose `content` field describes specific subjects, colors, or text from `AscendAgent/e2e/fixtures/image.png`. A generic description ("an image of something") means the bytes did not reach the model.

The AscendAgent log shows `HasImage: true` for the matching request id.

The AscendAgent log contains no `InvalidMimeTypeException` traces during the request.

## Fixtures

- `AscendAgent/e2e/fixtures/image.png` — pick something with one obvious correct answer (a specific subject, a unique logo, an annotated chart) so the description can be visually verified.
