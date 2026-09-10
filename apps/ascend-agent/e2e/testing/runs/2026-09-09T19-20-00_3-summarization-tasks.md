# Document summarization: run tasks template

Spec: [../3-summarization-test.md](../3-summarization-test.md)

Copy this file to `runs/<UTC-timestamp>_3-summarization-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version)
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}`
- [x] Docling Serve `/health` returns HTTP 200
- [x] Fixture `apps/ascend-agent/e2e/fixtures/argent-saga-chronicle.pdf` exists

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySummarizationTest'`
- [x] Deleted Redis key `chat:frostySummarizationTest`
- [x] Deleted Redis key `user:frostySummarizationTest:instructions`

### Run

- [x] Send `doc-summarization-prompt.yml` via `bru run` and wait for response (may take 30–90s) — FAILED: HTTP 422, not 200 (see Result summary)

### Expected

- [ ] HTTP 200 — observed HTTP 422
- [ ] Response `content` is a coherent summary that quotes specific facts from the source document — observed `content` was `undefined` (Bruno test: `expected undefined to be a string`)
- [ ] Response `content` contains at least three of the expected proper nouns listed in the spec's Expected section — not evaluated, `content` was absent
- [ ] Response `content` is NOT a refusal like "the document context block is empty" or "I don't see a document attached" — not evaluated, `content` was absent

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySummarizationTest'` (4 rows, accumulated from the official run attempt plus two off-spec diagnostic retries below)
- [x] Deleted Redis key `chat:frostySummarizationTest`
- [x] Deleted Redis key `user:frostySummarizationTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostySummarizationTest` returned `{"status":"success","message":"All memories wiped for user frostySummarizationTest"}`

### Verdict

- [x] Verdict: FAIL

## Result summary

The one prescribed Run invocation (`bru run "ascend-agent/testing/doc-summarization-prompt.yml" --env ascend-local`) returned HTTP 422 with no `content` field, failing both Expected assertions ("HTTP 200" and "Summary quotes at least 3 facts"). The Bruno test script itself reported the same two failures (`expected 422 to equal 200`, `expected undefined to be a string`), so this is a genuine assertion failure against the spec's Run step, not a test-script defect. Two off-spec diagnostic follow-ups (see below) sent the identical request again and both succeeded with HTTP 200 and grounded, canary-quoting summaries, which points to an intermittent failure in the request path (likely Docling parse or MiniMax provider call) rather than a systemic defect, but the officially prescribed single Run execution is what this verdict is anchored to, per the runner contract's instruction not to substitute a retry for a genuine failure.

Input tokens: not available (no token accounting surfaced by `bru run`; the successful diagnostic curl replay reported `promptTokens: 3540, completionTokens: 582, totalTokens: 4122` for one call, but that call was off-spec and not the official Run)

Output tokens: not available (see above)

Start (UTC): 2026-09-09T17:43:40Z

End (UTC): 2026-09-09T17:47:33Z

Duration: 00:03:53

---

## Additional tasks I did

- After the official Run step returned HTTP 422, re-ran the identical Bruno request (`bru run "ascend-agent/testing/doc-summarization-prompt.yml" --env ascend-local --output ...`) as a diagnostic retry. It returned HTTP 200 with both embedded tests passing. The `--output` flag itself then failed with `EPERM: operation not permitted, open 'C:\Program Files\Git\doc-summarization-result.json'` because `$SCRATCHPAD` was empty in this shell and the flag's relative path resolved into the Git-for-Windows install directory instead of the scratchpad directory; this happened only after the HTTP request itself had already completed and the tests had already run, so it did not affect the diagnostic result.
- Replayed the same request a second time via a direct `curl -X POST` multipart call (same file, prompt, `embeddingProvider=openai`, `provider=minimax`, `model=MiniMax-M2.7`) to capture a full response body for evidence. This also returned HTTP 200 with a summary containing "Aenaria Solveh", "Halen Veyr", "4317 P.E.", "Heron's Tooth", "57 seconds", "Concord of Mireth", "412 A.E.", "Vorsh-Ka the Quiet", "Iren Hask", and "498 A.E." (well over the 3-proper-noun threshold).
- Both diagnostic retries wrote additional per-user state (chat_history rows, Redis cache, memory-extraction points); the prescribed Post-run cleanup commands removed all of it (4 chat_history rows total, both Redis keys, full memory wipe), since those commands are bulk/idempotent by user_id rather than per-request.
