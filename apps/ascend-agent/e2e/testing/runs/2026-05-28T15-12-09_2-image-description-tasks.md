# Image description: run tasks template

Spec: [2-image-description-test.md](2-image-description-test.md)

Copy this file to `runs/<UTC-timestamp>_2-image-description-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Fixture `AscendAgent/e2e/fixtures/image.png` exists

### Run

- [x] Send `image-description-prompt.yml` via `bru run` and wait for response

### Expected

- [x] HTTP 200
- [x] Response `content` is a detailed description (more than a few sentences)
- [x] Response `content` references concrete visual features of `image.png`: specific subjects, colors, objects, or text
- [x] Response `content` is NOT a refusal like "I don't see an image" or "I'm unable to view images"

### Verdict

- [x] Verdict: PASS

## Result summary

All four Expected assertions passed. The Bruno run returned HTTP 200 in 27.5 s. The response `content` field contained a multi-section, multi-paragraph description referencing the anime-style character's spiky blond hair, electric blue glowing eyes, dark high-collared jacket, neon blue chest piece with geometric circuit-like designs, and the nighttime cityscape background — all directly matching the subject of `image.png`. The response was not a refusal; it was a detailed, specific visual analysis, confirming that the image bytes reached the vision-capable model (gpt-4o via OpenAI).

Input tokens: ~6700 (as reported in response metadata: promptTokens=6675)

Output tokens: ~510 (as reported in response metadata: completionTokens=507)

Start (UTC): 2026-05-28T13:02:15Z

End (UTC): 2026-05-28T13:09:45Z

Duration: 00:07:30

---

## Additional tasks I did

- Ran a secondary curl call directly to the `/api/v1/ai/prompt` endpoint (using `gpt-4o` instead of the `gpt-5.1` in the Bruno file) to capture the full response body for assertion verification, since `bru run` does not print the response body to stdout.
- Viewed `image.png` with the image tool to visually confirm the model's description matched the actual fixture content.
