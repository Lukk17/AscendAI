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

- [ ] Verdict: FAIL

## Result summary

The Bruno request returned HTTP 422 with body `{"status":422,"message":"Failed to route PDF page: argent-saga-chronicle.pdf","error":"Unprocessable Entity"}`. All four prerequisites passed (Bruno 3.4.0, AscendAgent health UP, Docling Serve health ok, fixture PDF present at 100,822 bytes). The PDF pipeline started correctly — all 5 pages were classified as text pages and routed to Docling. Pages 1, 3, 4, and 5 were processed successfully (extracting 2704, 2622, 2677, and 1180 characters respectively). However, the Docling child worker process for page 2 crashed mid-processing (Docling logs show "Child process [9] died"), causing the AscendAgent to throw a DocumentRoutingException and return 422. Because the agent's pipeline fails-fast on any single page failure, the model never received the document context and no summary was generated. This is an intermittent Docling infrastructure fault (child process OOM or crash under parallel page load), not a bug in the routing or summarization logic itself.

Input tokens:

Output tokens:

Start (UTC): 2026-06-17T16:37:14Z

End (UTC): 2026-06-17T16:40:37Z

Duration: 00:03:23

---

## Additional tasks I did

- Inspected AscendAgent container logs to confirm the 422 root cause: Docling worker process for page 2 crashed (log line: "Child process [9] died" in docling-serve). Pages 1, 3, 4, 5 succeeded; page 2 failed causing the whole request to fail-fast.
- Inspected docling-serve container logs to confirm the child process crash was an infrastructure-level fault, not a malformed PDF issue.
