# Image description — run tasks template

Spec: [2-image-description-test.md](2-image-description-test.md)

Copy this file to `runs/<UTC-timestamp>_2-image-description-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Fixture `AscendAgent/e2e/fixtures/image.png` exists

### Run

- [ ] Send `image-description-prompt.yml` via `bru run` and wait for response

### Expected

- [ ] HTTP 200
- [ ] Response `content` describes specific subjects, colors, or text from `image.png` (not a generic "an image of something")
- [ ] AscendAgent log shows `HasImage: true` for this request id
- [ ] AscendAgent log contains no `InvalidMimeTypeException` traces

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary

<!-- One short paragraph: what happened, key evidence, anything noteworthy. -->

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
