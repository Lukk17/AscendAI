# Chat-history compaction: fires + replaces prefix: run tasks template

Spec: [../10-compaction-fires-test.md](../10-compaction-fires-test.md)

Copy to `runs/<UTC-timestamp>_10-compaction-fires-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present (3.4.0)
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] Seed scripts `seed-compaction-fires.sql` + `seed-compaction-fires.redis` exist
- [x] Default compaction config in effect (`enabled=true`, `turn-trigger=20`, `keep-recent-turns=8`) (confirmed indirectly by the observed compaction firing at turns=23 with prefixCount=15, consistent with these defaults; `/actuator/configprops` was not queried directly per the spec's own caveat that it returns nothing useful unless exposed)

### Reset state

- [x] Applied `seed-compaction-fires.sql` to Postgres (deleted 9 leftover rows from a prior post-compaction run, then inserted 21)
- [x] Applied `seed-compaction-fires.redis` to Redis
- [x] Verified Postgres has 21 rows for `frostyCompactionFiresTest`
- [x] Verified Redis list `chat:frostyCompactionFiresTest` has 21 entries
- [x] Deleted Redis key `user:frostyCompactionFiresTest:instructions` (seeds don't touch it)

### Run

- [x] Step 1: sent `compaction-fires-prompt.yml`, HTTP 200
- [x] Step 2: waited 5 seconds for async compaction
- [x] Step 3: queried Postgres for post-compaction row counts

### Expected

- [x] Step 1: HTTP 200, response is a normal chat completion
- [x] Step 3: `chat_history` row count for `frostyCompactionFiresTest` equals exactly 9
- [x] Step 3: exactly 1 row has `role='system'` and content begins with `[Conversation summary]`
- [x] Step 3: exactly 8 rows have `role IN ('user', 'assistant')`
- [x] (Manual spot-check) summary content references Rex / Warsaw / TechCorp / Spring Boot

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyCompactionFiresTest'`
- [x] Deleted Redis key `chat:frostyCompactionFiresTest`
- [x] Deleted Redis key `user:frostyCompactionFiresTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyCompactionFiresTest` returned `{"status":"success","message":"All memories wiped for user frostyCompactionFiresTest"}`

### Verdict

- [x] Verdict: PASS

## Result summary

The seeded 21-row conversation grew to 23 rows after the prompt (1 new user + 1 new assistant turn), which crossed the turn-trigger of 20 and fired `ChatHistoryCompactionService` asynchronously. By the time the post-run Postgres query ran, the row count had already settled to exactly 9: 1 `role='system'` row whose content begins with `[Conversation summary]`, and 8 `role IN ('user','assistant')` rows, matching every Expected assertion in the spec. The summary row's content read "The user is a backend engineer at TechCorp in Warsaw who works daily with Spring Boot. Recently, a deployment failed due to a bad Liquibase change, and the user is now considering migrating one of their services from Spring Boot to Quarkus. Outside of work, the user has a beagle named Rex who enjoys chasing squirrels in the backyard; Rex recently slipped on a wet floor but is fine, and needs vaccinations updated next month at a Warsaw clinic.", covering Rex, Warsaw, TechCorp and Spring Boot as the spec's manual spot-check names (not asserted programmatically). Post-run cleanup dropped the 9 surviving rows, both Redis keys and wiped AscendMemory points for this user.

Provider: anthropic for both the main chat call and the compaction call (`compactionProvider=anthropic compactionModel=claude-haiku-4-5`, from the agent's own `[Compaction]` log line, since the compaction call has no HTTP response exposed to the runner).

Token usage, call 1, main chat completion (`compaction-fires-prompt.yml`, from `metadata.usage` and `nativeUsage` in the Bruno response body):
Model: claude-sonnet-4-6
Input (prompt) tokens: 618
Output (completion) tokens: 159
Total tokens: 777
Cache read tokens: 3744 (matches call 2's cache write from test 9, run minutes earlier in the same sweep against the same static system-prompt prefix; both anthropic tests share one ephemeral cache entry keyed on that prefix)
Cache creation tokens: 0

Token usage, call 2, async compaction summary call (model claude-haiku-4-5, sourced from the agent's `AnthropicPromptCacheStrategy` log line at 19:26:59.389, not from an HTTP response, since this call is fired server-side and never returns to the caller):
Input (prompt) tokens: 115
Output (completion) tokens: genuinely unavailable. No log line in this build records the compaction call's completion/output token count; only `prompt_tokens`, `cache_read_tokens` and `cache_creation_tokens` are logged by `AnthropicPromptCacheStrategy`. Recording as unavailable rather than 0 or an estimate.
Cache read tokens: 0
Cache creation tokens: 0

Input tokens: 618 (call 1) + 115 (call 2, from log) = 733 total

Output tokens: 159 (call 1). Call 2's output tokens are unavailable (see above).

Pre-compaction row count (after step 1): 23 (inferred from 21 seeded + 2 new; not independently queried before compaction had already completed by the time the post-run query ran, since compaction settled faster than the two sequential shell round-trips took)

Post-compaction row count (after step 3): 9

Summary row content (paste here for manual review):

```
[Conversation summary]
The user is a backend engineer at TechCorp in Warsaw who works daily with Spring Boot. Recently, a deployment failed due to a bad Liquibase change, and the user is now considering migrating one of their services from Spring Boot to Quarkus. Outside of work, the user has a beagle named Rex who enjoys chasing squirrels in the backyard; Rex recently slipped on a wet floor but is fine, and needs vaccinations updated next month at a Warsaw clinic.
```

Start (UTC): 2026-09-03T19:25:37Z

End (UTC): 2026-09-03T19:27:53Z

Duration: 00:02:16

---

## Additional tasks I did

Wrote the Bruno run output to a scratch JSON file (`test10-run.json`) to inspect `metadata.usage.nativeUsage` for call 1's token accounting.

Ran `docker logs ascend-agent --since 60s` as a diagnostic to find the compaction call's provider, model and prompt-token count, since the compaction call is fired asynchronously server-side and never returns an HTTP response the runner can inspect. This log evidence is cited only for token-accounting purposes; the pass/fail verdict rests entirely on the Postgres row-count and content assertions the spec names, not on any log line.

Defect observed in the spec's own Reset-state command shape, not worked around: `docker exec redis rm /tmp/seed-compaction-fires.redis` failed with `rm: can't remove 'C:/Users/Lukk/AppData/Local/Temp/seed-compaction-fires.redis': No such file or directory`. A follow-up diagnostic (`docker exec redis ls -la /tmp/`) failed the same way (`ls: C:/Users/Lukk/AppData/Local/Temp/: No such file or directory`). Both commands are exactly as written in the spec; the failure is my Git Bash shell auto-converting the bare leading-slash argument `/tmp/...` into a Windows path before it reaches `docker exec`, so the container never saw `/tmp/...` at all, it saw a Windows path string. Per the runner contract this is reported rather than worked around (no `MSYS_NO_PATHCONV=1` or `//tmp/...` substitution was applied). Net effect: the seed's temp file was not confirmed removed from the `redis` container's `/tmp`, though this is a harmless orphaned file that does not affect the Postgres/Redis state the spec's own Expected assertions check.
