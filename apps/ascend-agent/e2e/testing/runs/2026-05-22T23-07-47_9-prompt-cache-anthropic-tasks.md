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

- [x] Truncated `chat_history` rows for user `frostyPromptCacheAnthropicTest` (DELETE 4)
- [x] Deleted Redis key `chat:frostyPromptCacheAnthropicTest` (DEL 1)

### Run

- [x] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [x] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.cacheCreationInputTokens > 0` — observed 2176
- [x] Step 1: `usage.cacheReadInputTokens == 0` (or absent) — observed 0
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.cacheReadInputTokens > 0` — observed 2176

### Verdict

- [x] Verdict: PASS

## Result summary

Call 1: HTTP 200. nativeUsage.cache_creation_input_tokens=2176, cache_read_input_tokens=0.
Call 2: HTTP 200. nativeUsage.cache_read_input_tokens=2176 (equals creation count — full prefix hit).

Cache creation tokens (call 1): 2176

Cache read tokens (call 2): 2176

Output tokens: 348 (both calls identical output)

Start (UTC): 2026-05-22T23:15:35Z

End (UTC): 2026-05-22T23:17:01Z

Duration: 00:01:26

---

## Additional tasks I did
