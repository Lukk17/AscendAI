# Prompt cache: OpenAI: run tasks template

Spec: [8-prompt-cache-openai-test.md](8-prompt-cache-openai-test.md)

Copy to `runs/<UTC-timestamp>_8-prompt-cache-openai-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `OPENAI_API_KEY` is configured for the AscendAgent container (confirmed by user context)

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheOpenaiTest`
- [x] Deleted Redis key `chat:frostyPromptCacheOpenaiTest`

### Run

- [x] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [x] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.promptTokens >= 1024` — observed 1536
- [x] Step 1: `usage.promptTokensDetails.cachedTokens == 0` — observed 0
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.promptTokensDetails.cachedTokens > 0` — observed 1664

### Verdict

- [x] Verdict: PASS

## Result summary

Both calls HTTP 200. Call 1 seeded OpenAI prefix cache (promptTokens=1536, cachedTokens=0). Call 2 confirmed cache hit (promptTokens=1883, cachedTokens=1664).

Input tokens (call 1): 1536

Cached tokens (call 2): 1664

Output tokens: 255 (both calls)

Start (UTC): 2026-05-23T23:09:25Z

End (UTC): 2026-05-23T23:11:43Z

Duration: 00:02:18

---

## Additional tasks I did
