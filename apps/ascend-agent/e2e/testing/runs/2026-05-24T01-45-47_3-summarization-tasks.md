# Document summarization: run tasks template

Spec: [3-summarization-test.md](3-summarization-test.md)

Copy this file to `runs/<UTC-timestamp>_3-summarization-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Docling Serve `/health` returns HTTP 200
- [x] Fixture `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` exists

### Run

- [x] Send `doc-summarization-prompt.yml` via `bru run` and wait for response (may take 30–90s)

### Expected

- [x] HTTP 200
- [x] Response `content` is a coherent summary that quotes specific facts from the source document
- [x] Response `content` contains at least three of the expected proper nouns listed in the spec's Expected section
- [x] Response `content` is NOT a refusal like "the document context block is empty" or "I don't see a document attached"

### Verdict

- [x] Verdict: PASS

## Result summary

HTTP 200 in 48.7s. Response is a well-structured summary with 10 of 12 required proper nouns present: Aenaria Solveh, Halen Veyr, 4317 P.E., Heron's Tooth, thrall-burn, 57 seconds, Concord of Mireth, 412 A.E., Iren Hask, 498 A.E. PDF was parsed page-by-page through Docling and extracted text reached the model. No refusal phrases.

Input tokens: 0 (not tracked in metadata)

Output tokens: 0

Start (UTC): 2026-05-24T01:53:52Z

End (UTC): 2026-05-24T01:55:28Z

Duration: 00:01:36

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
