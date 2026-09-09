# Prompt cache: Anthropic: run tasks template

Spec: [9-prompt-cache-anthropic-test.md](9-prompt-cache-anthropic-test.md)

Copy to `runs/<UTC-timestamp>_9-prompt-cache-anthropic-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `ASCEND_ANTHROPIC_API_KEY` is configured for the AscendAgent container (confirmed by task context)

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheAnthropicTest`
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`

### Run

- [x] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [x] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.cacheCreationInputTokens > 0` (write to ephemeral cache) — observed 2176
- [x] Step 1: `usage.cacheReadInputTokens == 0` (or absent) — observed 0
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.cacheReadInputTokens > 0` — observed 2176

### Verdict

- [x] Verdict: PASS

## Result summary

Step 1: `cache_creation_input_tokens=2176`, `cache_read_input_tokens=0`. Step 2: `cache_read_input_tokens=2176` (matches step 1 creation count).

Cache creation tokens (call 1): 2176

Cache read tokens (call 2): 2176

Output tokens: 366 (both calls identical)

Start (UTC): 2026-05-24T01:52:11Z

End (UTC): 2026-05-24T01:53:39Z

Duration: 00:01:28

---

## Additional tasks I did
