# Document summarization: run tasks template

Spec: [../3-summarization-test.md](../3-summarization-test.md)

Copy this file to `runs/<UTC-timestamp>_3-summarization-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [x] Bruno CLI present (`bru --version` returns a version) — 3.4.0
- [x] ascend-ai-agent `/actuator/health` returns HTTP 200 with `{"status":"UP"}` — `{"status":"UP","groups":["liveness","readiness"]}`
- [x] Docling Serve `/health` returns HTTP 200 — `{"status":"ok"}`
- [x] Fixture `apps/ascend-agent/e2e/fixtures/argent-saga-chronicle.pdf` exists

### Reset state

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySummarizationTest'` (DELETE 0, none present)
- [x] Deleted Redis key `chat:frostySummarizationTest` (0, none present)
- [x] Deleted Redis key `user:frostySummarizationTest:instructions` (0, none present)

### Run

- [x] Send `doc-summarization-prompt.yml` via `bru run` and wait for response (took 81143 ms, within 30-90s window)

### Expected

- [x] HTTP 200 — confirmed in raw response JSON (`"status": 200`)
- [x] Response `content` is a coherent summary that quotes specific facts from the source document — Markdown summary with headed sections (The Vell Order, The Korraxin, The Sundering, The Concord of Mireth, The Hask Apostasy, Present)
- [x] Response `content` contains at least three of the expected proper nouns listed in the spec's Expected section — 11 of 12 matched: Aenaria Solveh, Halen Veyr, 4317 P.E., Heron's Tooth, thrall-burn, 57 seconds, Concord of Mireth, 412 A.E., Vorsh-Ka the Quiet, Iren Hask, 498 A.E. (only "81 duels" absent as an exact substring; content instead reads "81 wins, 34 refused challenges")
- [x] Response `content` is NOT a refusal like "the document context block is empty" or "I don't see a document attached" — neither phrase present (checked programmatically)

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostySummarizationTest'` (DELETE 4, two turn-pairs from the two prompt calls I made)
- [x] Deleted Redis key `chat:frostySummarizationTest` (1)
- [x] Deleted Redis key `user:frostySummarizationTest:instructions` (1)
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostySummarizationTest` returned `{"status":"success","message":"All memories wiped for user frostySummarizationTest"}`

### Verdict

- [x] Verdict: PASS

## Result summary

All four Expected assertions hold, verified directly against the raw response body rather than trusting the Bruno script's pass/fail alone. The endpoint returned HTTP 200. The `content` field is a coherent Markdown summary of "The Argent Saga" organized into headed sections (The Vell Order, The Korraxin, The Sundering, The Concord of Mireth, The Hask Apostasy, Present), quoting 11 of the 12 canary facts listed in the spec (only "81 duels" was absent as an exact substring — the model wrote "81 wins, 34 refused challenges" instead, a paraphrase rather than a parsing failure), well above the 3-fact minimum. No refusal phrasing was present. This confirms the PDF was parsed page-by-page through PDFBox/Docling, the extracted text reached the model via `<document_context>`, and the summary is grounded in real document content rather than hallucinated.

Input tokens: 3559 (promptTokens, from the captured request/response pair; MiniMax-M2.7)

Output tokens: 1128 (completionTokens, same pair)

Start (UTC): 2026-09-10T07:59:27Z

End (UTC): 2026-09-10T08:04:01Z

Duration: 00:04:34

---

## Additional tasks I did

- Checked `ascend-agent`'s full container log for the startup-readiness banner's `External dependencies` section (`docker logs ascend-agent | grep -i "External dependencies"`); no banner text was present in the retained log (container likely up long enough that it scrolled out), so this could not be used as a pre-flight signal. Proceeded on the spec's own prerequisite checks, which all passed directly.
- Invoked the spec's Run step (`bru run "ascend-agent/testing/doc-summarization-prompt.yml" --env ascend-local`) twice: once as prescribed, and a second time with `--output ... --format json` solely to capture the raw response body so I could verify the Expected assertions against the actual `content` string myself rather than trusting the embedded Bruno test script's summary verdict. Both calls returned HTTP 200 with the same 2/2 embedded-test pass result. This is why Post-run cleanup found 4 `chat_history` rows (two turn-pairs) instead of 2 — cleanup removed both, so no state was left behind. The reported Input/Output token counts are for one of the two calls, not the sum of both.
- Compared the Bruno request's embedded test script (`ascend-agent/testing/doc-summarization-prompt.yml`) against the spec's Expected section: same 12-item fact list, same "at least 3" threshold, same two refusal phrases checked in lowercase. The script does not check anything weaker than the spec; no discrepancy to report.
- Deleted the temporary JSON capture file from the scratchpad directory after use.
- The run never encountered the HTTP 422 / dropped-page failure mode described in the pre-briefing, so no docker logs for `ascend-agent` or `docling-serve` around a failure were needed.
