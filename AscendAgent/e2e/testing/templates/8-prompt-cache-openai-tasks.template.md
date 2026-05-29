# Prompt cache: OpenAI: run tasks template

Spec: [8-prompt-cache-openai-test.md](8-prompt-cache-openai-test.md)

Copy to `runs/<UTC-timestamp>_8-prompt-cache-openai-tasks.md` before starting.

## Tasks

### Prerequisites

- [ ] Bruno CLI present
- [ ] AscendAgent `/actuator/health` returns 200
- [ ] Postgres responds to `SELECT 1`
- [ ] Redis `PING` returns `PONG`
- [ ] `OPENAI_API_KEY` is configured for the AscendAgent container

### Reset state

- [ ] Truncated `chat_history` rows for user `frostyPromptCacheOpenaiTest`
- [ ] Deleted Redis key `chat:frostyPromptCacheOpenaiTest`

### Run

- [ ] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [ ] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [ ] Step 1: HTTP 200
- [ ] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold)
- [ ] Step 1: `usage.promptTokensDetails.cachedTokens == 0` (or absent)
- [ ] Step 2: HTTP 200
- [ ] Step 2: `usage.promptTokensDetails.cachedTokens > 0`

### Verdict

- [ ] Verdict: PASS / FAIL

## Result summary



Input tokens (call 1):

Cached tokens (call 2):

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did
