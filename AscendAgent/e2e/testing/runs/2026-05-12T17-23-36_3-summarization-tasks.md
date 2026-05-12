# Document summarization — run tasks template

Spec: [3-summarization-test.md](../3-summarization-test.md)

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

PDFBox → Docling pipeline parsed all pages and the model produced a grounded summary in ~37s. Bruno HTTP 200. Response contains nearly every spec proper noun: `Aenaria Solveh`, `Halen Veyr`, `4317 P.E.`, `Heron's Tooth`, `thrall-burn`, `57 seconds`, `Concord of Mireth`, `412 A.E.`, `Vorsh-Ka the Quiet`, `81` duels, `Iren Hask`, `498 A.E.` — far exceeding the three-of list threshold. No refusal.

Input tokens: ~5000

Output tokens: ~900

Start (UTC): 2026-05-12T17:28:39Z

End (UTC): 2026-05-12T17:29:54Z

Duration: 00:01:15

---

## Additional tasks I did

None.
