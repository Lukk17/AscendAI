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

The AscendAgent accepted the multipart image POST at `/api/v1/ai/prompt` with `X-User-Id: frostyImageDescriptionTest` and returned HTTP 200 in approximately 20 seconds (Bruno) and ~22 seconds (curl verification call). The response `content` field contained a rich, multi-section description of the fixture — an anime-style portrait of a male character with spiky platinum-blond hair, glowing blue eyes, a dark high-collar jacket, a neon-blue geometric chest emblem, and a night cityscape background with warm city lights and stars. The description explicitly named colors (electric blue, warm orange, golden), structural features (sharp angular face, geometric chest piece with circuitry-like lines), lighting (cool under-lighting from the chest glow, warm shoulder glow from city lights), and overall style (crisp digital anime with cel-shading). No refusal language was present. All four Expected assertions passed. The image bytes reached the OpenAI gpt-5.1 vision model and produced a detailed, visually accurate description.

Input tokens: 7764 (from gpt-5.1 usage metadata in response)

Output tokens: 1021 (from gpt-5.1 usage metadata in response)

Start (UTC): 2026-06-17T17:45:55Z

End (UTC): 2026-06-17T17:47:44Z

Duration: 00:01:49

---

## Additional tasks I did

- Viewed the fixture `image.png` before running to establish ground truth: anime-style male character portrait with spiky platinum-blond hair, glowing blue eyes, dark jacket, blue geometric chest emblem, night cityscape background.
- Read `image-description-prompt.yml` to confirm the active provider/model before running: OpenAI `gpt-5.1` (the Anthropic and other entries were disabled).
- Ran a second `curl` call directly against the endpoint (in addition to the Bruno run) to capture the full response body for assertion verification, since Bruno CLI does not print the response body to stdout.
