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

The Bruno request returned HTTP 200 in ~21 seconds. The response `content` field contains a structured markdown summary of argent-saga-chronicle.pdf via the MiniMax-M2.7 model (3705 prompt tokens, 547 completion tokens). The summary references at least 10 of the 12 expected proper nouns from the spec: Aenaria Solveh, Halen Veyr, 4317 P.E., Heron's Tooth, thrall-burn, 57 seconds, Concord of Mireth, 412 A.E., Vorsh-Ka the Quiet, Iren Hask, and 498 A.E. The content is grounded in specific facts from the document (founding dates, duel counts, coalition sizes, ritual names) and is not a refusal. All four Expected assertions pass.

Input tokens: 3705

Output tokens: 547

Start (UTC): 2026-06-18T12:38:56Z

End (UTC): 2026-06-18T12:41:08Z

Duration: 00:02:12

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
