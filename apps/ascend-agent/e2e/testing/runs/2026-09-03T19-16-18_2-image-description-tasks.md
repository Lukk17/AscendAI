# Image description: run tasks template

Spec: [../2-image-description-test.md](../2-image-description-test.md)

Copy this file to `runs/<UTC-timestamp>_2-image-description-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) - 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Fixture `AscendAgent/e2e/fixtures/image.png` exists

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyImageDescriptionTest'` (found 2 leftover rows from a prior run)
- [x] Deleted Redis key `chat:frostyImageDescriptionTest`
- [x] Deleted Redis key `user:frostyImageDescriptionTest:instructions`

### Run

- [x] Send `image-description-prompt.yml` via `bru run` and wait for response

### Expected

- [x] HTTP 200
- [x] Response `content` is a detailed description (more than a few sentences)
- [x] Response `content` references concrete visual features of `image.png`: specific subjects, colors, objects, or text (a stylized anime-style male character with spiky blond hair, glowing blue eyes and chest circuitry, dark jacket, night cityscape background)
- [x] Response `content` is NOT a refusal like "I don't see an image" or "I'm unable to view images"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyImageDescriptionTest'`
- [x] Deleted Redis key `chat:frostyImageDescriptionTest`
- [x] Deleted Redis key `user:frostyImageDescriptionTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyImageDescriptionTest` returned `{"status":"success","message":"All memories wiped for user frostyImageDescriptionTest"}`

### Verdict

- [x] Verdict: PASS

## Result summary

Both Bruno test assertions passed (status code 200, description length and refusal check). The response body's `content` field is a multi-paragraph, section-by-section description covering pose, hair, glowing chest and eye elements, clothing, lighting and the night cityscape background, well past the 200-character minimum and grounded in concrete visual detail rather than a generic placeholder. No refusal phrase was present. All four pieces of post-run state were cleared successfully.

Provider: openai. Model: gpt-5.1-2025-11-13 (per `metadata.model` in the response, resolved from the request's enabled `provider=openai` / `model=gpt-5.1` form fields).

Token usage (single call, from `metadata.usage` and `metadata.usage.nativeUsage` in the response body):
Input (prompt) tokens: 3098
Output (completion) tokens: 644
Total tokens: 3742
Cached tokens: 0 (`nativeUsage.prompt_tokens_details.cached_tokens`)

Input tokens: 3098

Output tokens: 644

Start (UTC): 2026-09-03T19:18:57Z

End (UTC): 2026-09-03T19:19:39Z

Duration: 00:00:42

---

## Additional tasks I did

Wrote the Bruno run output to a scratch JSON file (`bru run ... -o <scratch>/test2-image.json`) to inspect the full response body, including `metadata.usage` and `metadata.usage.nativeUsage`, for token accounting. Outside the spec's own assertions but needed for the sweep's token-accounting requirement.
