# Image Description — manual e2e test

## What this verifies

An attached image is forwarded to a vision-capable model and described accurately, AND the vision-capability gate rejects providers/models that don't support images. Covers:

- **Bug 2** — defensive image MIME parsing (no `InvalidMimeTypeException` on missing/odd content-type)
- **Bug 10** — vision-capability gate: non-vision provider/model combos return HTTP 400 with a clear `ApiError`, not a silent fallback

## Prerequisites

- `docker compose up -d` stack up
- AscendAgent on port 9917
- For the allow-path: API key for OpenAI (`gpt-5.1`, the file default) **or** Anthropic (`claude-sonnet-4-6`) **or** Gemini (`gemini-2.5-flash`) **or** an LM Studio vision model loaded (`qwen/qwen3-vl-4b`)
- For the deny-path scenario: any provider that runs (the deny-path uses `prompt.yml`, not `image-description-prompt.yml`)

## Bruno collection

This test uses two requests:

1. **Allow-path** → `docs/api/request/AscendAI/ascend-agent/testing/image-description-prompt.yml`
2. **Deny-path** → `docs/api/request/AscendAI/ascend-agent/prompt.yml` (the root sandbox request)

`image-description-prompt.yml` is **intentionally allow-path only** — MiniMax has no vision-capable models so it's not listed there. The vision-capability gate is exercised through the root `prompt.yml`, which keeps MiniMax as its default provider and has an `image` row you can enable.

### Scenario A — allow-path (vision-capable model)

In `image-description-prompt.yml`, enable exactly one provider/model pair. Default (already enabled):

- `prompt`: `Describe what you see in this image in detail`
- `image`: file → `AscendAgent/e2e/fixtures/image.png`
- `provider`: `openai`
- `model`: `gpt-5.1`
- `embeddingProvider`: `openai`

Alternative vision-capable rows present in the file (disabled by default — toggle on as needed):

- `anthropic` + `claude-sonnet-4-6`
- `gemini` + `gemini-2.5-flash`
- `lmstudio` + `qwen/qwen3-vl-4b` (plus switch `embeddingProvider` to `lmstudio`)

### Scenario B — deny-path (non-vision provider)

In `prompt.yml` (the root sandbox request), enable:

- `prompt`: `Describe what you see in this image in detail`
- `image`: file → `AscendAgent/e2e/fixtures/image.png` (the `image` row is disabled by default — toggle on and point at the fixture)
- `provider`: `minimax` (default)
- `model`: `MiniMax-M2.7` (default)
- `embeddingProvider`: `openai` (default)

The deny-path is whatever provider/model combination has no vision support; MiniMax is the simplest because it's the file default.

## Steps

1. Send Scenario A (from `image-description-prompt.yml`).
2. Inspect the response body and the AscendAgent log.
3. Send Scenario B (from `prompt.yml`).
4. Inspect the response body and the AscendAgent log.

## Expected

**Scenario A:**

- HTTP 200; `content` describes the actual subject of `image.png` (specific objects, colors, text). A generic "an image of something" answer means the bytes didn't reach the model.
- Agent log shows `HasImage: true` for the request and no `InvalidMimeTypeException` traces.

**Scenario B:**

- HTTP 400 with an `ApiError`-shaped body whose message states that the selected provider/model has no vision support.
- Agent log shows the vision-gate rejection log line; no upstream provider call is made.

Sanity check: re-run Scenario A with a clearly different image. If both runs produce similar generic answers, the image isn't reaching the model — look for `data URL too short` warnings.

## Bugs this covers

- **Bug 2** — agent must not crash on missing/odd image content-type; MIME is sniffed from bytes when the browser-supplied type is unusable.
- **Bug 10** — vision-capability check happens before the provider call.

## Fixtures

- `AscendAgent/e2e/fixtures/image.png` — pick something with one obvious correct answer (a banana on a plain background, a known logo, a chart with a unique title).
