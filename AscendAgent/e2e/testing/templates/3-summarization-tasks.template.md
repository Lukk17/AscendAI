# Document summarization: run tasks template

Spec: [3-summarization-test.md](3-summarization-test.md)

Copy this file to `runs/<UTC-timestamp>_3-summarization-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [ ] Docling Serve `/health` returns HTTP 200
- [ ] Fixture `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` exists

### Run

- [ ] Send `doc-summarization-prompt.yml` via `bru run` and wait for response (may take 30–90s)

### Expected

- [ ] HTTP 200
- [ ] Response `content` is a coherent summary that quotes specific facts from the source document
- [ ] Response `content` contains at least three of the expected proper nouns listed in the spec's Expected section
- [ ] Response `content` is NOT a refusal like "the document context block is empty" or "I don't see a document attached"

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
