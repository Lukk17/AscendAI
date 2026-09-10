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

The Bruno request returned HTTP 200 in approximately 22 seconds. The response `content` field contained a rich, structured summary of the Argent Saga document. All four Expected assertions passed: (1) HTTP 200 confirmed; (2) the summary is coherent and grounded in document content (7-rank order structure, specific dates and events); (3) at least 11 of the 12 specified proper nouns and facts were present verbatim, including `Aenaria Solveh`, `Halen Veyr`, `4317 P.E.`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `Concord of Mireth`, `412 A.E.`, `Vorsh-Ka the Quiet`, `Iren Hask`, and `498 A.E.`; (4) the response is a detailed factual summary with no refusal language — the PDF was parsed page-by-page through the Docling pipeline and the extracted text clearly reached the MiniMax-M2.7 model (3444 prompt tokens consumed, confirming document context was injected).

Input tokens: 3444

Output tokens: 564

Start (UTC): 2026-06-17T22:08:00Z

End (UTC): 2026-06-17T22:10:25Z

Duration: 00:02:25

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
