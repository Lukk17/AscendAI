# Document summarization: run tasks template

Spec: [../3-summarization-test.md](../3-summarization-test.md)

Copy this file to `runs/<UTC-timestamp>_3-summarization-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Docling Serve `/health` returns HTTP 200
- [x] Fixture `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` exists

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySummarizationTest'`
- [x] Deleted Redis key `chat:frostySummarizationTest`
- [x] Deleted Redis key `user:frostySummarizationTest:instructions`

### Run

- [x] Send `doc-summarization-prompt.yml` via `bru run` and wait for response (may take 30-90s)

### Expected

- [x] HTTP 200
- [x] Response `content` is a coherent summary that quotes specific facts from the source document
- [x] Response `content` contains at least three of the expected proper nouns listed in the spec's Expected section
- [x] Response `content` is NOT a refusal like "the document context block is empty" or "I don't see a document attached"

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySummarizationTest'`
- [x] Deleted Redis key `chat:frostySummarizationTest`
- [x] Deleted Redis key `user:frostySummarizationTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostySummarizationTest` returned `{"status":"success", ...}`

### Verdict

- [x] Verdict: PASS

## Result summary

The Bruno request returned HTTP 200 in 30199 ms. The response `content` field quoted ten of the twelve canary proper nouns from the spec's Expected list, well above the required three: Aenaria Solveh, Halen Veyr, 4317 P.E., Heron's Tooth, thrall-burn, 57 seconds, Concord of Mireth, 412 A.E., Vorsh-Ka the Quiet, 498 A.E. Neither refusal phrase appeared. This is the second of five back to back executions run to verify the retry and fan out fix for the intermittent 422 `Failed to route PDF page` error. Response time was close to run 1's, so nothing in this run's own timing distinguishes a retry firing from a clean single pass conversion.

Input tokens: 233 (promptTokens, from response `metadata.usage`)

Output tokens: 553 (completionTokens, from response `metadata.usage`)

Start (UTC): 2026-09-03T20:17:43Z

End (UTC): 2026-09-03T20:18:39Z

Duration: 00:00:56

---

## Additional tasks I did

Captured the full Bruno JSON result with `bru run ... -o run2-result.json`, written to the session scratchpad directory rather than into `e2e/testing/runs/`, to inspect `response.data.metadata.usage` for token counts. The file lives outside the repository and was not committed to the run-record boundary.
