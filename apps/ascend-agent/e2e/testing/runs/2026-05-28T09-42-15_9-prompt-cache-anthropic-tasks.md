# Prompt cache: Anthropic: run tasks template

Spec: [9-prompt-cache-anthropic-test.md](9-prompt-cache-anthropic-test.md)

Copy to `runs/<UTC-timestamp>_9-prompt-cache-anthropic-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `ASCEND_ANTHROPIC_API_KEY` is configured for the AscendAgent container

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`

### Run

- [x] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [x] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.cacheCreationInputTokens > 0` — observed 2176 (write to ephemeral cache)
- [x] Step 1: `usage.cacheReadInputTokens == 0` — observed 0
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.cacheReadInputTokens > 0` — observed 2176

### Verdict

- [x] Verdict: PASS

## Result summary

Both steps completed successfully within 18 seconds of each other, well inside the 5-minute ephemeral cache window. Step 1 (POST at 15:45:53 UTC) returned HTTP 200 with `metadata.usage.nativeUsage.cache_creation_input_tokens = 2176` and `cache_read_input_tokens = 0`, confirming a clean cold-start cache write. Step 2 (POST at 15:46:11 UTC) returned HTTP 200 with `cache_read_input_tokens = 2176` and `cache_creation_input_tokens = 425` (the second call added the assistant reply to the chat history prefix, which also got cached). The step-2 read count of 2176 exactly matches the step-1 creation count, confirming Anthropic's `cache_control` directive is correctly applied by Spring AI's `AnthropicCacheOptions`. All five Expected assertions pass. The `CustomMetadata` fix is confirmed: each usage key appears exactly once in the response body with correct non-zero values.

Cache creation tokens (call 1): 2176

Cache read tokens (call 2): 2176

Output tokens: ~500 (best estimate for LLM API calls during this run)

Start (UTC): 2026-05-28T09:42:15Z

End (UTC): 2026-05-28T09:46:30Z

Duration: 00:04:15

---

## Additional tasks I did

- Read `step1_output.json` and `step2_output.json` (Bruno `--reporter-json` captures) to verify `nativeUsage` field values directly from the response body, per caller's note that the actual JSON path is `metadata.usage.nativeUsage.cacheCreationInputTokens` (camelCase under `nativeUsage`).
- Noted step 2's `cache_creation_input_tokens = 425` in addition to `cache_read_input_tokens = 2176`: the second call extends the cached prefix with the first assistant reply, which is expected behaviour and does not affect the pass verdict.
