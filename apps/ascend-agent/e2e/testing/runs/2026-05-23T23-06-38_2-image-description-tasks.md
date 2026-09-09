# Image description: run tasks template

Spec: [2-image-description-test.md](2-image-description-test.md)

Copy this file to `runs/<UTC-timestamp>_2-image-description-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Fixture `AscendAgent/e2e/fixtures/image.png` exists

### Run

- [x] Send `image-description-prompt.yml` via `bru run` and wait for response

### Expected

- [x] HTTP 200
- [x] Response `content` is a detailed description (more than a few sentences) — ~1000 words, 8 sections
- [x] Response `content` references concrete visual features of `image.png`: anime character, glowing electric blue eyes, blond spiky hair, dark jacket with futuristic chest panel, nighttime cityscape background
- [x] Response `content` is NOT a refusal like "I don't see an image" or "I'm unable to view images"

### Verdict

- [x] Verdict: PASS

## Result summary

HTTP 200. Content: Extensive multi-section description of an anime-style character — face, eyes (glowing electric blue), hair (blond spiky), outfit (dark jacket with neon blue chest energy core), lighting (warm amber city + cold blue neon contrast), background (nighttime futuristic city). Provider: OpenAI gpt-5.1. Response time 49.98s.

Input tokens: 0 (metadata not returned)

Output tokens: 0 (metadata not returned)

Start (UTC): 2026-05-23T23:12:06Z

End (UTC): 2026-05-23T23:13:13Z

Duration: 00:01:07

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
