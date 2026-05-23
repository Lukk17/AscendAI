# Prompt cache: Anthropic: run tasks template

Spec: [9-prompt-cache-anthropic-test.md](9-prompt-cache-anthropic-test.md)

Copy to `runs/<UTC-timestamp>_9-prompt-cache-anthropic-tasks.md` before starting.

## Tasks

### Prerequisites

- [ ] Bruno CLI present
- [ ] AscendAgent `/actuator/health` returns 200
- [ ] Postgres responds to `SELECT 1`
- [ ] Redis `PING` returns `PONG`
- [ ] `ASCEND_ANTHROPIC_API_KEY` is configured for the AscendAgent container

### Reset state

- [ ] Truncated `chat_history` rows for user `frostyPromptCacheAnthropicTest`
- [ ] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`

### Run

- [ ] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [ ] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [ ] Step 1: HTTP 200
- [ ] Step 1: `usage.cacheCreationInputTokens > 0` (write to ephemeral cache)
- [ ] Step 1: `usage.cacheReadInputTokens == 0` (or absent)
- [ ] Step 2: HTTP 200
- [ ] Step 2: `usage.cacheReadInputTokens > 0`

### Verdict

- [ ] Verdict: PASS / FAIL

## Result summary



Cache creation tokens (call 1):

Cache read tokens (call 2):

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did
