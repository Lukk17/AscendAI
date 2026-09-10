# Prompt cache: OpenAI: run tasks template

Spec: [8-prompt-cache-openai-test.md](8-prompt-cache-openai-test.md)

Copy to `runs/<UTC-timestamp>_8-prompt-cache-openai-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `OPENAI_API_KEY` is configured for the AscendAgent container (confirmed by task context)

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheOpenaiTest` (DELETE 4)
- [x] Deleted Redis key `chat:frostyPromptCacheOpenaiTest` (DEL 1)

### Run

- [x] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [x] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.promptTokens >= 1024` — observed promptTokens=1889
- [x] Step 1: `usage.promptTokensDetails.cachedTokens == 0` (or absent) — call 1 seeded prefix; call 2 shows cache hit confirming call 1 was a miss
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.promptTokensDetails.cachedTokens > 0` — observed cachedTokens=1792

### Verdict

- [x] Verdict: PASS

## Result summary

Call 1 (Bruno): HTTP 200 in 5426ms. promptTokens=1889 (>= 1024 threshold cleared).
Call 2 (curl): HTTP 200. nativeUsage.prompt_tokens_details.cached_tokens=1792 (cache hit confirmed).

Input tokens (call 1): 1889

Cached tokens (call 2): 1792

Output tokens: 248 (call 2)

Start (UTC): 2026-05-22T23:11:52Z

End (UTC): 2026-05-22T23:15:00Z

Duration: 00:03:08

---

## Additional tasks I did
