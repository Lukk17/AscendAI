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

HTTP 200 (19.2s). Detailed multi-paragraph description of anime-style male character: electric blue glowing eyes, spiky blond hair, futuristic neon chest piece, dark jacket, night cityscape background. gpt-5.1 correctly described all major visual elements. No refusal.

Input tokens: 3822

Output tokens: 820

Start (UTC): 2026-05-22T23:13:12Z

End (UTC): 2026-05-22T23:16:05Z

Duration: 00:02:53

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
