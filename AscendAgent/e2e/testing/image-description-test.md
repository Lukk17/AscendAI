# Image Description — manual e2e test

## What this verifies

An attached image is forwarded to a vision-capable model and described accurately, AND the vision-capability gate rejects providers/models that don't support images. Covers:

- **Bug 2** — defensive image MIME parsing (no `InvalidMimeTypeException` on missing/odd content-type)
- **Bug 10** — vision-capability gate: non-vision provider/model combos return HTTP 400 with a clear `ApiError`, not a silent fallback

## Prerequisites

- `docker compose up -d` stack up
- AscendAgent on port 9917
- For the allow-path: API key for OpenAI (gpt-5.1) **or** Anthropic (claude-sonnet-4-6) **or** an LM Studio vision model loaded (e.g. `qwen/qwen3-vl-4b`)
- For the deny-path: MiniMax credentials (text-only models)

## Bruno collection

Open Bruno → `docs/api/request/AscendAI/ascend-agent/testing/` → `image-description-prompt.yml`.

The file is a template — multiple `provider=` / `model=` rows are saved against the same field names, toggled via the disabled flag. Before sending, enable exactly one provider row plus its matching model row.

### Scenario A — allow-path (vision-capable)

Enable:

- `prompt`: `Describe what you see in this image in detail`
- `image`: file → `AscendAgent/e2e/fixtures/image.png`
- `provider`: `openai`
- `model`: `gpt-5.1`
- `embeddingProvider`: `openai`

Alternatives that should also work: `anthropic` + `claude-sonnet-4-6`, or `lmstudio` + `qwen/qwen3-vl-4b` (rows present but disabled in the file — toggle them on instead).

### Scenario B — deny-path (text-only model)

Same form, but enable:

- `provider`: `minimax`
- `model`: `MiniMax-M2.7`

Leave everything else identical to Scenario A.

## Steps

1. Send Scenario A.
2. Inspect the response body and the AscendAgent log.
3. Send Scenario B.
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
