# Image description — run tasks template

Spec: [2-image-description-test.md](../2-image-description-test.md)

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
- [x] Response `content` references concrete visual features of `image.png` — specific subjects, colors, objects, or text
- [x] Response `content` is NOT a refusal like "I don't see an image" or "I'm unable to view images"

### Verdict

- [x] Verdict: PASS

## Result summary

Vision pipeline delivered the image bytes to the model. Bruno HTTP 200 in ~20.3s. Response is a multi-paragraph description of an anime-style character: spiky blonde hair, glowing neon-blue eyes, dark jacket with high collar, glowing chest tech-plate, night cityscape background with bokeh and stars, warm/cool contrast lighting. Numerous concrete visual features cited; no refusal.

Input tokens: ~1500

Output tokens: ~700

Start (UTC): 2026-05-12T17:27:03Z

End (UTC): 2026-05-12T17:27:58Z

Duration: 00:00:55

---

## Additional tasks I did

None.
