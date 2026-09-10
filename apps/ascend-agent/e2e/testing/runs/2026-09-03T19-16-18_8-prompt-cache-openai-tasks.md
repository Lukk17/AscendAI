# Prompt cache: OpenAI: run tasks template

Spec: [../8-prompt-cache-openai-test.md](../8-prompt-cache-openai-test.md)

Copy to `runs/<UTC-timestamp>_8-prompt-cache-openai-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present (3.4.0)
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `OPENAI_API_KEY` is configured for the AscendAgent container (presence check confirmed the variable was set; value not printed)

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheOpenaiTest` (found 4 leftover rows from a prior run)
- [x] Deleted Redis key `chat:frostyPromptCacheOpenaiTest`
- [x] Deleted Redis key `user:frostyPromptCacheOpenaiTest:instructions`

### Run

- [x] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [x] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold) (observed 2462)
- [x] Step 1: `usage.nativeUsage.prompt_tokens_details.cached_tokens == 0` (or absent on a fresh-cache run; non-zero acceptable when OpenAI's server-side TTL hasn't expired from a prior local run) (observed 0)
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.nativeUsage.prompt_tokens_details.cached_tokens > 0` (observed 2560)

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [x] Deleted Postgres `chat_history` rows where `user_id = 'frostyPromptCacheOpenaiTest'`
- [x] Deleted Redis key `chat:frostyPromptCacheOpenaiTest`
- [x] Deleted Redis key `user:frostyPromptCacheOpenaiTest:instructions`
- [x] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyPromptCacheOpenaiTest` returned `{"status":"success","message":"All memories wiped for user frostyPromptCacheOpenaiTest"}`

### Verdict

- [x] Verdict: PASS

## Result summary

Both Bruno-run calls passed all assertions. Call 1 (cache-miss seed) returned HTTP 200 with `metadata.usage.promptTokens = 2462` (above the 1024 threshold) and `nativeUsage.prompt_tokens_details.cached_tokens = 0`, the expected fresh-cache shape. Call 2, sent immediately after within the 5-minute cache TTL window, returned HTTP 200 with `nativeUsage.prompt_tokens_details.cached_tokens = 2560`, proving OpenAI's automatic prefix cache fired on the second identical prompt. `promptTokens` grew from 2462 to 2796 between the two calls because call 1's turn was written to `chat_history` and is included in call 2's prompt prefix (the spec's Reset only runs once, before both calls, not between them); this growth is expected and does not affect the cache assertion, since the cached count of 2560 is well above the "high hundreds" floor the spec names. Post-run cleanup dropped the Postgres rows, both Redis keys and wiped the AscendMemory points for this user.

Provider: openai. Model: gpt-4o-2024-08-06 for both calls.

Token usage, call 1 (from `metadata.usage` and `nativeUsage`):
Input (prompt) tokens: 2462
Output (completion) tokens: 238
Total tokens: 2700
Cached tokens: 0

Token usage, call 2 (from `metadata.usage` and `nativeUsage`):
Input (prompt) tokens: 2796
Output (completion) tokens: 246
Total tokens: 3042
Cached tokens: 2560

Input tokens (call 1): 2462

Cached tokens (call 2): 2560

Output tokens: 238 (call 1) + 246 (call 2) = 484 total

Start (UTC): 2026-09-03T19:23:07Z

End (UTC): 2026-09-03T19:24:04Z

Duration: 00:00:57

---

## Additional tasks I did

Wrote both Bruno run outputs to scratch JSON files (`test8-call1.json`, `test8-call2.json`) to inspect the full response bodies, including `metadata.usage.nativeUsage.prompt_tokens_details`, for the per-call token and cache accounting this sweep requires beyond the spec's own Bruno-side assertions.
