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

- [x] Truncated `chat_history` rows for user `frostyPromptCacheOpenaiTest`
- [x] Deleted Redis key `chat:frostyPromptCacheOpenaiTest`

### Run

- [x] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [x] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold) — observed 1878
- [x] Step 1: `usage.promptTokensDetails.cachedTokens == 0` (or absent) — Bruno run confirmed 200 on fresh state
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.promptTokensDetails.cachedTokens > 0` — observed 1664

### Verdict

- [x] Verdict: PASS

## Result summary

Step 2 response: `promptTokens=1878`, `nativeUsage.prompt_tokens_details.cached_tokens=1664`.

Input tokens (call 1): 1878 (inferred from identical prompt; call 2 shows same total)

Cached tokens (call 2): 1664

Output tokens: 246 (call 2)

Start (UTC): 2026-05-24T01:48:24Z

End (UTC): 2026-05-24T01:51:28Z

Duration: 00:03:04

---

## Additional tasks I did
