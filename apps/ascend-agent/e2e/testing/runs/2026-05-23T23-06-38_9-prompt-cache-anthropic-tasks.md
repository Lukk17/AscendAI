# Prompt cache: Anthropic: run tasks template

Spec: [9-prompt-cache-anthropic-test.md](9-prompt-cache-anthropic-test.md)

Copy to `runs/<UTC-timestamp>_9-prompt-cache-anthropic-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `ASCEND_ANTHROPIC_API_KEY` is configured for the AscendAgent container (confirmed by user context)

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`

### Run

- [x] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [x] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.cacheCreationInputTokens > 0` — observed 2176
- [x] Step 1: `usage.cacheReadInputTokens == 0` — observed 0
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.cacheReadInputTokens > 0` — observed 2176

### Verdict

- [x] Verdict: PASS

## Result summary

Both calls HTTP 200. Call 1 wrote Anthropic ephemeral cache (cacheCreationInputTokens=2176, cacheReadInputTokens=0). Call 2 confirmed cache read (cacheReadInputTokens=2176, matching call 1's creation count). cacheCreationInputTokens on call 2 = 776 (new incremental portion above the cached breakpoint).

Cache creation tokens (call 1): 2176

Cache read tokens (call 2): 2176

Output tokens: 358 (both calls)

Start (UTC): 2026-05-23T23:12:20Z

End (UTC): 2026-05-23T23:13:33Z

Duration: 00:01:13

---

## Additional tasks I did
