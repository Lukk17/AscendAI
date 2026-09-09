# Document summarization: run tasks template

Spec: [3-summarization-test.md](3-summarization-test.md)

Copy this file to `runs/<UTC-timestamp>_3-summarization-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Docling Serve `/health` returns HTTP 200
- [x] Fixture `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` exists

### Run

- [x] Send `doc-summarization-prompt.yml` via `bru run` and wait for response (may take 30–90s) — 55.6s

### Expected

- [x] HTTP 200
- [x] Response `content` is a coherent summary that quotes specific facts from the source document
- [x] Response `content` contains at least three of the expected proper nouns — found 11/12: Aenaria Solveh, Halen Veyr, 4317 P.E., Heron's Tooth, thrall-burn, 57 seconds, Concord of Mireth, 412 A.E., Vorsh-Ka the Quiet, 81 (duels), Iren Hask, 498 A.E.
- [x] Response `content` is NOT a refusal like "the document context block is empty" or "I don't see a document attached"

### Verdict

- [x] Verdict: PASS

## Result summary

HTTP 200. Coherent structured summary with 7 sections covering Vell Order, The Eclipse, Sundering, Concord of Mireth, Korraxin, Hask Apostasy, Present Day. 11 of 12 spec proper nouns present (only "81 duels" phrasing differs slightly — "81 wins" — but the fact is present). No refusal language. Response time 55.6s (within 30–90s window).

Input tokens: 0 (metadata not returned)

Output tokens: 0 (metadata not returned)

Start (UTC): 2026-05-23T23:14:03Z

End (UTC): 2026-05-23T23:15:15Z

Duration: 00:01:12

---

## Additional tasks I did

<!-- Optional. List anything outside the spec. Leave empty if nothing extra. -->
