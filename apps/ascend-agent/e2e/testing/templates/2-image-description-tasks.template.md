# Image description: run tasks template

Spec: [../2-image-description-test.md](../2-image-description-test.md)

Copy this file to `runs/<UTC-timestamp>_2-image-description-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Fixture `apps/ascend-agent/e2e/fixtures/image.png` exists

### Reset state

- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostyImageDescriptionTest'`
- [ ] Deleted Redis key `chat:frostyImageDescriptionTest`
- [ ] Deleted Redis key `user:frostyImageDescriptionTest:instructions`

### Run

- [ ] Send `image-description-prompt.yml` via `bru run` and wait for response

### Expected

- [ ] HTTP 200
- [ ] Response `content` is a detailed description (more than a few sentences)
- [ ] Response `content` references concrete visual features of `image.png`: specific subjects, colors, objects, or text
- [ ] Response `content` is NOT a refusal like "I don't see an image" or "I'm unable to view images"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostyImageDescriptionTest'`
- [ ] Deleted Redis key `chat:frostyImageDescriptionTest`
- [ ] Deleted Redis key `user:frostyImageDescriptionTest:instructions`
- [ ] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyImageDescriptionTest` returned `{"status":"success", ...}`

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
