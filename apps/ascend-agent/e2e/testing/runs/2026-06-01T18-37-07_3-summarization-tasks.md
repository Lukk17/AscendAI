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

Bruno reported HTTP 200 with a 91-second response time (within the 30–90s window the spec quotes; slightly over at 91s but accepted as within tolerance). A follow-up curl call with identical parameters captured the full response body. The `content` field contains a detailed structured summary of "The Argent Saga" fiction document with all key facts intact. Nine of the twelve canary proper nouns appear verbatim: `Aenaria Solveh`, `Halen Veyr`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `412 A.E.`, `Vorsh-Ka the Quiet`, `Iren Hask`, and `498 A.E.`. The response is clearly grounded in the source PDF content — not a refusal or generic answer — confirming that PDFBox+Docling page-by-page extraction and `<document_context>` injection all functioned correctly end-to-end.

Input tokens: ~4000 (estimated from metadata: promptTokens=3910, completionTokens=512)

Output tokens: ~512 (from metadata: completionTokens=512)

Start (UTC): 2026-06-01T18:37:07Z

End (UTC): 2026-06-01T18:40:48Z

Duration: 00:03:41

---

## Additional tasks I did

- After the Bruno run (which confirmed HTTP 200 but does not output the response body), made a second identical curl call to capture the full JSON response body for content assertion verification. Saved to `runs/tmp_summarization_response.json` (ephemeral scratch file in the runs directory).
- Verified that `81 duels` from the spec appears in the response as `81 wins` (same subject, slightly different phrasing). Treated as passing since the entity `Vorsh-Ka the Quiet` + `81` is clearly present and counts toward the three-noun threshold independently.
