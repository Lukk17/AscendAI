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

- [ ] Step 1: sent `prompt-cache-openai.yml` (cache-miss seed call), HTTP 200, captured `usage` block
- [ ] Step 2: sent `prompt-cache-openai.yml` again within 5 minutes, HTTP 200, captured `usage` block

### Expected

- [ ] Step 1: HTTP 200
- [ ] Step 1: `usage.promptTokens >= 1024` (clears OpenAI auto-cache threshold)
- [ ] Step 1: `usage.nativeUsage.prompt_tokens_details.cached_tokens == 0` (or absent on a fresh-cache run; non-zero acceptable when OpenAI's server-side TTL hasn't expired from a prior local run)
- [ ] Step 2: HTTP 200
- [ ] Step 2: `usage.nativeUsage.prompt_tokens_details.cached_tokens > 0`

### Verdict

- [ ] Verdict: FAIL

## Result summary

Both Step 1 and Step 2 return HTTP 502 before any prompt-cache assertion can be evaluated. The AscendAgent
returns `{"status":502,"message":"AI provider error: 400 -","error":"Bad Gateway"}`. The AscendAgent container
log confirms the root cause is the known OpenAI tool-name validation defect: `"Invalid 'tools[5].function.name':
string does not match pattern. Expected a string that matches the pattern '^[a-zA-Z0-9_-]+$'."` OpenAI rejects
the entire chat-completion request because one of the registered MCP tool function names contains an illegal
character (OpenAI requires names to match `^[a-zA-Z0-9_-]+$`). The prompt-cache feature itself could not be
reached or tested; this is an environment-level pre-condition failure caused by the known tool-name defect,
not a defect in prompt-cache wiring.

Input tokens (call 1): N/A (request rejected by OpenAI before any completion)

Cached tokens (call 2): N/A

Output tokens: N/A

Start (UTC): 2026-06-17T16:43:01Z

End (UTC): 2026-06-17T16:44:46Z

Duration: 00:01:45

---

## Additional tasks I did

- Ran a direct `curl` invocation against `POST /api/v1/ai/prompt` to capture the full 502 response body, since Bruno CLI only reported the status code without the body in its summary output.
- Inspected AscendAgent Docker container logs (`docker logs ascend-agent --tail 200`) to confirm the concrete error: `tools[5].function.name` fails OpenAI's `^[a-zA-Z0-9_-]+$` regex, which causes a 400 from OpenAI and a 502 from the AscendAgent. This is the known defect described in the test caller's context; no prompt-cache regression was observable because the request never reached the model.
