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

- [ ] HTTP 200
- [ ] Response `content` is a coherent summary that quotes specific facts from the source document
- [ ] Response `content` contains at least three of the expected proper nouns listed in the spec's Expected section
- [ ] Response `content` is NOT a refusal like "the document context block is empty" or "I don't see a document attached"

### Verdict

- [x] Verdict: FAIL

## Result summary

All three attempts returned HTTP 422 with `{"message":"Failed to route PDF page: argent-saga-chronicle.pdf","status":422,"error":"Unprocessable Entity"}`. Docling Serve experienced a child process crash (`Child process [N] died`) on every attempt — confirmed in container logs for all three runs. On each attempt Docling successfully converted several pages (pages 2, 3, 5 converted with HTTP 200 responses at the Docling level) but a worker process died while handling one of the parallel page-conversion jobs (page 4's layout pipeline), causing AscendAgent to receive a Docling error and surface a 422 to the caller. The memory bump to shm_size 2g / memory 2-6g did NOT prevent the crashes; all three attempts failed identically. None of the Expected assertions (HTTP 200, coherent summary, proper nouns) were satisfied.

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T18:04:00Z

End (UTC): 2026-06-17T18:07:46Z

Duration: 00:03:46

---

## Additional tasks I did

- Inspected `docker logs docling-serve` after each attempt to confirm worker crash (`Child process died`) rather than a network or agent-side failure. Crash occurred on all three attempts, with `INFO: Child process [12] died` (attempt 2) and `INFO: Child process [13] died` (attempt 3) visible in container stdout, followed by automatic Docling restart.
- Verified that Docling health endpoint returned HTTP 200 before each retry, confirming the crash was mid-request rather than at startup.
- The 422 error message `Failed to route PDF page: argent-saga-chronicle.pdf` is the AscendAgent's surface-level error when the Docling call fails; root cause is confirmed as Docling worker OOM/crash, not a routing or configuration error in the agent itself.
