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

The Bruno request returned HTTP 200 in 28816 ms. The response `content` field was a coherent five-section summary of the fixture PDF and quoted nine of the twelve canary proper nouns from the spec's Expected list, well above the required three: Aenaria Solveh, Halen Veyr, 4317 P.E., Heron's Tooth, thrall-burn, 57 seconds, 412 A.E., Vorsh-Ka the Quiet, Iren Hask. Neither refusal phrase appeared. This is the first of five back to back executions run to verify the retry and fan out fix for the intermittent 422 `Failed to route PDF page` error. No connection level failure was observed on this attempt, so nothing in this run's own timing distinguishes a retry firing from a clean single pass conversion.

Input tokens: 233 (promptTokens, from response `metadata.usage`)

Output tokens: 558 (completionTokens, from response `metadata.usage`)

Start (UTC): 2026-09-03T20:15:48Z

End (UTC): 2026-09-03T20:16:54Z

Duration: 00:01:06

---

## Additional tasks I did

Prerequisite checks (`bru --version`, AscendAgent health, Docling Serve health, fixture presence) were run about 15 seconds before Start was recorded, as part of a single environment recon pass shared across all five planned executions of this spec. Start reflects the moment reset for this specific run began.

Confirmed via `docker ps` that the `ascend-agent` container was recreated at 2026-09-03 22:13:51 CEST (about 2 minutes before this run started), consistent with the caller's statement that the fix under test was freshly deployed.

Captured the full Bruno JSON result with `bru run ... -o run1-result.json` to inspect `response.data.metadata.usage` for token counts, since the tasks template's Input/Output tokens fields are not populated by the spec's own assertions. Deleted `run1-result.json` after extracting the figures above; it was a scratch artifact outside the run-record boundary.
