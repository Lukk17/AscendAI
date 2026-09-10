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

The third attempt returned HTTP 200 after two 422 failures caused by the Docling worker OOM crash (confirmed via AscendAgent logs showing `Unexpected end of file from server` at DoclingClient.process). The response `content` field contains a coherent structured summary of the Argent Saga document with specific facts proving the PDF was parsed page-by-page through Docling and the extracted text reached the model. The following proper nouns from the spec's canary list were all present in the response: `Aenaria Solveh`, `Halen Veyr`, `4317 P.E.`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `Concord of Mireth`, `412 A.E.`, `Vorsh-Ka the Quiet`, `Iren Hask`, and `498 A.E.` — eleven of twelve required markers, well above the three-minimum threshold. The content was not a refusal. All four Expected assertions passed.

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T17:46:06Z

End (UTC): 2026-06-17T17:50:39Z

Duration: 00:04:33

---

## Additional tasks I did

- Attempt 1 (422, 52s): Docling worker OOM crash — `Unexpected end of file from server` at DoclingClient.process. Retried per caller-granted environmental-flakiness allowance.
- Attempt 2 (422, 19s): Same Docling worker crash. Retried (second and final allowed retry).
- Attempt 3 (200, 47s): Success. Inspected `content` field via direct curl to confirm proper nouns from the spec's canary list.
- Checked AscendAgent docker logs to confirm the 422 cause was Docling OOM, not a logic defect in the summarization pipeline.
