# Prompt cache: Anthropic: run tasks template

Spec: [../9-prompt-cache-anthropic-test.md](../9-prompt-cache-anthropic-test.md)

Copy to `runs/<UTC-timestamp>_9-prompt-cache-anthropic-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present (3.4.0)
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `ASCEND_ANTHROPIC_API_KEY` is configured for the AscendAgent container (presence check confirmed the variable was set; value not printed)

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheAnthropicTest` (0 leftover rows, clean before this run)
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `user:frostyPromptCacheAnthropicTest:instructions`

### Run

- [x] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [x] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.nativeUsage.cache_creation_input_tokens > 0` (write to ephemeral cache) (observed 3744)
- [x] Step 1: `usage.nativeUsage.cache_read_input_tokens == 0` (or absent) (observed 0)
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.nativeUsage.cache_read_input_tokens > 0` (observed 3744, matching step 1's cache_creation_input_tokens exactly)

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyPromptCacheAnthropicTest'`
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `user:frostyPromptCacheAnthropicTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyPromptCacheAnthropicTest` returned `{"status":"success","message":"All memories wiped for user frostyPromptCacheAnthropicTest"}`

### Verdict

- [x] Verdict: PASS

## Result summary

Both Bruno-run calls passed all assertions. Call 1 returned HTTP 200 with `metadata.usage.nativeUsage.cache_creation_input_tokens = 3744` and `cache_read_input_tokens = 0`, the expected cold-cache-write shape (a true cold start, no prior identical prompt within the TTL). Call 2, sent immediately after, returned HTTP 200 with `cache_read_input_tokens = 3744`, exactly matching call 1's `cache_creation_input_tokens`, proving Anthropic's native `cache_control` directive both wrote and then read the ephemeral cache entry as designed. `promptTokens` (the non-cached portion) grew from 427 to 901 between calls because call 1's turn was written to `chat_history` and is included in call 2's prompt; the cached prefix itself stayed exactly the same size across both calls (3744 tokens), confirming no drift. Post-run cleanup dropped the Postgres rows, both Redis keys and wiped the AscendMemory points for this user.

Provider: anthropic. Model: claude-sonnet-4-6 for both calls.

Token usage, call 1 (from `metadata.usage` and `nativeUsage`):
Input (prompt, non-cached) tokens: 427
Output (completion) tokens: 370
Total tokens: 797
Cache creation tokens: 3744
Cache read tokens: 0

Token usage, call 2 (from `metadata.usage` and `nativeUsage`):
Input (prompt, non-cached) tokens: 901
Output (completion) tokens: 370
Total tokens: 1271
Cache creation tokens: 0
Cache read tokens: 3744

Cache creation tokens (call 1): 3744

Cache read tokens (call 2): 3744

Output tokens: 370 (call 1) + 370 (call 2) = 740 total

Start (UTC): 2026-09-03T19:24:24Z

End (UTC): 2026-09-03T19:25:19Z

Duration: 00:00:55

---

## Additional tasks I did

Wrote both Bruno run outputs to scratch JSON files (`test9-call1.json`, `test9-call2.json`) to inspect the full response bodies, including `metadata.usage.nativeUsage`, for the per-call token and cache accounting this sweep requires beyond the spec's own Bruno-side assertions.
