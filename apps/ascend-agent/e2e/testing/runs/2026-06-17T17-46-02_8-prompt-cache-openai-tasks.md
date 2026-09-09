# Prompt cache: OpenAI: run tasks template

Spec: [8-prompt-cache-openai-test.md](8-prompt-cache-openai-test.md)

## Tasks

### Prerequisites

- [x] Bruno CLI present
- [x] AscendAgent `/actuator/health` returns 200
- [x] Postgres responds to `SELECT 1`
- [x] Redis `PING` returns `PONG`
- [x] `OPENAI_API_KEY` is configured for the AscendAgent container

### Reset state

- [x] Truncated `chat_history` rows for user `frostyPromptCacheOpenaiTest`
- [x] Deleted Redis key `chat:frostyPromptCacheOpenaiTest`

### Run

- [x] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [x] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [x] Step 1: HTTP 200
- [x] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold) — observed 2799
- [x] Step 1: `usage.nativeUsage.prompt_tokens_details.cached_tokens == 0` (or absent on a fresh-cache run; non-zero acceptable when OpenAI's server-side TTL hasn't expired from a prior local run) — observed 2688 (non-zero; spec permits this)
- [x] Step 2: HTTP 200
- [x] Step 2: `usage.nativeUsage.prompt_tokens_details.cached_tokens > 0` — observed 2944

### Verdict

- [x] Verdict: PASS

## Result summary

Both calls returned HTTP 200. Step 1 showed `promptTokens=2799` (well above the 1024 threshold), confirming OpenAI's auto-cache can fire. Step 1 also showed `cached_tokens=2688` — non-zero, which the spec explicitly permits when the server-side TTL from a prior local run has not expired. Step 2 showed `cached_tokens=2944 > 0`, confirming the prompt cache is wired end-to-end. The `nativeUsage` block is present in both responses with the correct snake_case field names (`prompt_tokens_details.cached_tokens`). Both responses have full `usage` blocks with stable structure.

Input tokens (call 1): 2799

Cached tokens (call 2): 2944

Output tokens: 247 (call 1), 242 (call 2)

Start (UTC): 2026-06-17T17:46:02Z

End (UTC): 2026-06-17T17:47:51Z

Duration: 00:01:49

---

## Additional tasks I did

- Used direct `curl` calls instead of `bru run` for Steps 1 and 2 in order to capture the full response body (Bruno CLI does not print response body in `--env` mode without a `--output` flag or assertions). The requests were byte-identical to those in `prompt-cache-openai.yml` (same URL, headers, form fields). Bruno CLI was still verified working via the spec's Bruno prereq check and was used for the initial sanity run of Step 1 (confirmed 200). The curl calls are authoritative for the observable assertions.
- Checked `prompt-cache-openai.yml` to confirm the exact prompt text and form fields before constructing the curl commands, ensuring byte-identical payloads between Step 1 and Step 2.
