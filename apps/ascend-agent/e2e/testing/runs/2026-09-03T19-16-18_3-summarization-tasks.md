# Document summarization: run tasks template

Spec: [../3-summarization-test.md](../3-summarization-test.md)

Copy this file to `runs/<UTC-timestamp>_3-summarization-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) - 3.4.0
- [x] AscendAgent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Docling Serve `/health` returns HTTP 200 (`{"status":"ok"}`)
- [x] Fixture `AscendAgent/e2e/fixtures/argent-saga-chronicle.pdf` exists

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySummarizationTest'` (found 2 leftover rows from a prior run)
- [x] Deleted Redis key `chat:frostySummarizationTest`
- [x] Deleted Redis key `user:frostySummarizationTest:instructions`

### Run

- [x] Sent `doc-summarization-prompt.yml` via `bru run` and waited for response (30s)

### Expected

- [ ] HTTP 200 (observed HTTP 422)
- [ ] Response `content` is a coherent summary that quotes specific facts from the source document (not applicable, request errored before reaching the chat model)
- [ ] Response `content` contains at least three of the expected proper nouns listed in the spec's Expected section (not applicable, no `content` field present)
- [ ] Response `content` is NOT a refusal like "the document context block is empty" or "I don't see a document attached" (not applicable, response body has no `content` field at all)

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySummarizationTest'` (0 rows, confirms the request never reached the chat-completion stage)
- [x] Deleted Redis key `chat:frostySummarizationTest`
- [x] Deleted Redis key `user:frostySummarizationTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostySummarizationTest` returned `{"status":"success","message":"All memories wiped for user frostySummarizationTest"}`

### Verdict

- [x] Verdict: FAIL

## Result summary

The run failed before reaching the chat model. `bru run "ascend-agent/testing/doc-summarization-prompt.yml" --env ascend-local` returned HTTP 422 with body `{"timestamp":"2026-09-03T19:20:38.060210830Z","message":"Failed to route PDF page: argent-saga-chronicle.pdf","error":"Unprocessable Entity","status":422}`. Both Bruno test assertions failed as a direct consequence (status-code check expected 200 got 422; content-string check found `content` undefined because the error body carries no `content` field). None of the four Expected assertions in the spec could be evaluated because the response never reached the shape they test against.

Diagnostic root cause (log inspection only, not used as a pass criterion, the failing HTTP status and body above are the actual evidence): AscendAgent's own log shows the PDF was split into 5 pages and all 5 were dispatched to Docling in parallel (`parallelism=5`). Pages 1, 4 and 5 converted successfully. Pages 2 and 3 failed with `java.net.SocketException: Unexpected end of file from server` while calling Docling. The docling-serve container's own log for the same window shows `Child process [345] died` immediately after it started converting pages 2 and 3 concurrently with the tail of page 5's conversion, i.e. the Docling worker process crashed mid-request under the 5-way parallel CPU-only inference load this single PDF triggers, which severed the two in-flight connections from AscendAgent and surfaced as the 422. `curl -fsS http://localhost:5001/health` returned `{"status":"ok"}` both before the run (prerequisite check) and is reachable now, so the container recovered after respawning its child process; this looks like a resource-exhaustion issue on the Docling side under concurrent page dispatch rather than a defect in the reset/cleanup edits the spec gained today. Environment, not spec logic, is the most likely proximate cause, but this run is the first execution since the spec's edits and it did not produce a passing result, so it is recorded as FAIL per the runner contract rather than silently retried.

Provider / model: not reached, request failed during document ingestion prior to any chat-model call. No `metadata.usage` block exists in the 422 error response.

Input tokens: not applicable, call never reached the chat model.

Output tokens: not applicable, call never reached the chat model.

Start (UTC): 2026-09-03T19:19:56Z

End (UTC): 2026-09-03T19:21:17Z

Duration: 00:01:21

---

## Additional tasks I did

Ran `docker logs ascend-agent --since 90s` and `docker logs docling-serve --since 90s` as diagnostics to identify the proximate cause of the 422 (Docling worker process crash under 5-way parallel page dispatch, `java.net.SocketException: Unexpected end of file from server` on pages 2 and 3). These log lines are cited as diagnostic clues only, per the behaviour-only-assertions rule; the pass/fail verdict rests solely on the observed HTTP 422 and the response body content, not on the log text. Did not retry the request with different input; the spec's Run step names one invocation and no retry logic, so a retry would have been an off-spec workaround rather than a report of what actually happened on first execution.
