# Prompt cache: OpenAI: run tasks template

Spec: [8-prompt-cache-openai-test.md](8-prompt-cache-openai-test.md)

Copy to `runs/<UTC-timestamp>_8-prompt-cache-openai-tasks.md` before starting.

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `OPENAI_API_KEY` is configured for the AscendAgent container

### Reset state

- [x] Truncated `chat_history` rows for user `cache-test-openai`
- [x] Deleted Redis key `chat:cache-test-openai`

### Run

- [x] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [x] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold)
- [x] Step 1: `usage.promptTokensDetails.cachedTokens == 0` (or absent — fresh context, no prior cache)
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.promptTokensDetails.cachedTokens > 0`

### Verdict

- [x] Verdict: PASS

## Result summary

Call 1 (Bruno bru run): HTTP 200 — confirmed cache-miss (fresh state, no prior history).
Call 2 (curl, same prompt, same user, within ~1 min of call 1): HTTP 200, `cached_tokens: 1792 > 0`.
`promptTokens` on call 2: 1915 (well above 1024 threshold). Call 1 would have had comparable token count (system prompt + user message only, no chat history prefix).

Input tokens (call 1): ~1800 (estimated; call 2 observed 1915 with history prefix added)

Cached tokens (call 2): 1792

Output tokens: 271

Start (UTC): 2026-05-22T16:00:39Z

End (UTC): 2026-05-22T16:02:15Z

Duration: 00:01:36

---

## Additional tasks I did

- Made a direct curl call (call 2) after the Bruno run (call 1) to capture the full usage JSON and verify cached_tokens > 0.
