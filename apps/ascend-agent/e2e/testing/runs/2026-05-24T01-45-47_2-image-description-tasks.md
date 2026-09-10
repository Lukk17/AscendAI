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

HTTP 200. Response is a detailed multi-section description (~900 words) of an anime-style futuristic character: spiky blond hair, electric blue glowing eyes, neon blue chest panel, dark high-collar jacket, city-at-night background with warm orange horizon. All concrete visual features. No refusal. Response time 16.5s (vision model inference).

Input tokens: 0 (not tracked in metadata)

Output tokens: 0

Start (UTC): 2026-05-24T01:52:25Z

End (UTC): 2026-05-24T01:53:13Z

Duration: 00:00:48

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
