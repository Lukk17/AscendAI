# Prompt cache: Anthropic: run tasks template

Spec: [../9-prompt-cache-anthropic-test.md](../9-prompt-cache-anthropic-test.md)

Copy to `runs/<UTC-timestamp>_9-prompt-cache-anthropic-tasks.md` before starting.

## Tasks

### Prerequisites

- [ ] Bruno CLI present
- [ ] ascend-ai-agent `/actuator/health` returns 200
- [ ] Postgres responds to `SELECT 1`
- [ ] Redis `PING` returns `PONG`
- [ ] `ASCEND_ANTHROPIC_API_KEY` is configured for the ascend-ai-agent container

### Reset state

- [ ] Truncated `chat_history` rows for user `frostyPromptCacheAnthropicTest`
- [ ] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`
- [ ] Deleted Redis key `user:frostyPromptCacheAnthropicTest:instructions`

### Run

- [ ] Step 1: sent `prompt-cache-anthropic.yml` (cache-miss / cache-write call), HTTP 200, captured `usage`
- [ ] Step 2: sent `prompt-cache-anthropic.yml` again within 5 minutes, HTTP 200, captured `usage`

### Expected

- [ ] Step 1: HTTP 200
- [ ] Step 1: `usage.nativeUsage.cache_creation_input_tokens > 0` (write to ephemeral cache)
- [ ] Step 1: `usage.nativeUsage.cache_read_input_tokens == 0` (or absent)
- [ ] Step 2: HTTP 200
- [ ] Step 2: `usage.nativeUsage.cache_read_input_tokens > 0`

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostyPromptCacheAnthropicTest'`
- [ ] Deleted Redis key `chat:frostyPromptCacheAnthropicTest`
- [ ] Deleted Redis key `user:frostyPromptCacheAnthropicTest:instructions`
- [ ] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyPromptCacheAnthropicTest` returned `{"status":"success", ...}`

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
