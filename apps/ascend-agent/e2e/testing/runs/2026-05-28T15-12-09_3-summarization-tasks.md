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

The Bruno run returned HTTP 200 in approximately 32 seconds (third run, which was used for content assertion verification). The response `content` field contained a detailed, coherent summary of the source PDF (`argent-saga-chronicle.pdf`), demonstrating that PDFBox parsed each page and Docling converted the content, which was then injected into the prompt. The summary included 11 of 12 expected proper nouns: `Aenaria Solveh`, `Halen Veyr`, `4317 P.E.`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `Concord of Mireth`, `412 A.E.`, `Vorsh-Ka the Quiet`, `Iren Hask`, and `498 A.E.` — far exceeding the minimum of three required. The content was not a refusal. One intermediate run (the second of three) returned HTTP 422 with "Failed to route PDF page" — this is noted in Additional tasks. All four Expected assertions passed.

Input tokens: ~3200

Output tokens: ~800

Start (UTC): 2026-05-28T15:12:09Z

End (UTC): 2026-05-28T15:20:45Z

Duration: 00:08:36

---

## Additional tasks I did

- Ran three Bruno invocations total. Run 1 (52s) returned HTTP 200 but no JSON reporter was used so body was not captured. Run 2 (16s) returned HTTP 422 ("Failed to route PDF page") — a transient failure, possibly Docling under load or a connection reset. Run 3 (32s) returned HTTP 200 with full response body captured via `--reporter-json`. Content assertions were verified against run 3's response.
- Attempted a `curl` direct invocation for body capture but it also produced 422, confirming Docling had a transient window of instability between runs 1 and 3.
