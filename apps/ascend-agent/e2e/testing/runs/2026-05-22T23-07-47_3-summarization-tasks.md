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

HTTP 200 (55s). All 12/12 expected proper nouns present: Aenaria Solveh, Halen Veyr, 4317 P.E., Heron's Tooth, thrall-burn, 57 seconds, Concord of Mireth, 412 A.E., Vorsh-Ka the Quiet, 81 duels, Iren Hask, 498 A.E. Coherent multi-section summary proving full PDF parse through Docling pipeline.

Input tokens: 3590

Output tokens: 1573

Start (UTC): 2026-05-22T23:14:54Z

End (UTC): 2026-05-22T23:16:50Z

Duration: 00:01:56

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
