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

The Bruno request POSTed `argent-saga-chronicle.pdf` to `POST /api/v1/ai/prompt` (user `frostySummarizationTest`, provider MiniMax-M2.7) and received HTTP 200 in ~23 seconds. The `content` field returned a well-structured markdown summary titled "The Argent Saga – Condensed Summary" containing 8 or more of the spec's expected proper nouns: `Aenaria Solveh`, `Halen Veyr`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `Concord of Mireth`, `412 A.E.`, and `Vorsh-Ka the Quiet`. The response is a coherent, multi-section narrative grounded in the fixture document's content and contains no refusal language. All four Expected assertions pass. The PDF was parsed page-by-page through Docling and the extracted text was injected into the prompt context as verified by the presence of the proper nouns that could only have come from the document.

Input tokens:

Output tokens:

Start (UTC): 2026-05-29T22:33:08Z

End (UTC): 2026-05-29T22:35:20Z

Duration: 00:02:12

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
