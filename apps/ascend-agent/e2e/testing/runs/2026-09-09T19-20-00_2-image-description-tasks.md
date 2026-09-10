# Image description: run tasks template

Spec: [../2-image-description-test.md](../2-image-description-test.md)

Copy this file to `runs/<UTC-timestamp>_2-image-description-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Fixture `apps/ascend-agent/e2e/fixtures/image.png` exists

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyImageDescriptionTest'`
- [x] Deleted Redis key `chat:frostyImageDescriptionTest`
- [x] Deleted Redis key `user:frostyImageDescriptionTest:instructions`

### Run

- [x] Send `image-description-prompt.yml` via `bru run` and wait for response

### Expected

- [x] HTTP 200
- [x] Response `content` is a detailed description (more than a few sentences)
- [x] Response `content` references concrete visual features of `image.png`: specific subjects, colors, objects, or text
- [x] Response `content` is NOT a refusal like "I don't see an image" or "I'm unable to view images"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyImageDescriptionTest'`
- [x] Deleted Redis key `chat:frostyImageDescriptionTest`
- [x] Deleted Redis key `user:frostyImageDescriptionTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyImageDescriptionTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

The `image-description-prompt.yml` request returned HTTP 200 with a 3322-character `content` field (well over "a few sentences"). The description accurately names the real visual features of `image.png`: spiky blond hair, glowing electric-blue eyes, a dark jacket with a glowing cyan chest emblem, and a night-time city skyline with stars in the background, matching the fixture's actual anime-style character illustration verified by direct visual inspection. No refusal phrasing ("I don't see an image", "I'm unable to view images") appears anywhere in the response. All four Expected assertions hold on directly observed response content, and the paired Bruno test script (`Status code is 200`, `Image description is detailed and not a refusal`) also passed.

Input tokens:

Output tokens:

Start (UTC): 2026-09-09T17:42:27Z

End (UTC): 2026-09-09T17:44:26Z

Duration: 00:01:59

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
