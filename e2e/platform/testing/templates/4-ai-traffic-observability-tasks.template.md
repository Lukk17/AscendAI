# AI traffic observability: run tasks template

Spec: [../4-ai-traffic-observability-test.md](../4-ai-traffic-observability-test.md)

Copy this file to `../runs/<UTC-timestamp>_4-ai-traffic-observability-tasks.md` before starting a run. Tick boxes as you go. Add anything you did beyond the spec under **Additional tasks I did**.

## Tasks

### Prerequisites

- [ ] Bruno CLI present (`bru --version` returns a version)
- [ ] Prometheus `/-/ready` prints `200`
- [ ] Grafana `/api/health` prints `200`
- [ ] Tempo search answers through Grafana
- [ ] `OPENAI_API_KEY` is configured for the ascend-ai-agent container
- [ ] `ASCEND_ANTHROPIC_API_KEY` is configured for the ascend-ai-agent container

### Reset state

- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostyAiTrafficTest'`
- [ ] Deleted Redis key `chat:frostyAiTrafficTest`
- [ ] Deleted Redis key `user:frostyAiTrafficTest:instructions`
- [ ] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyAiTrafficTest` returned `{"status":"success", ...}`

### Run

- [ ] `bru run "platform/observability/openai-prompt.yml" --env ascend-local` passes
- [ ] `bru run "platform/observability/anthropic-prompt-1.yml" --env ascend-local` passes
- [ ] `bru run "platform/observability/anthropic-prompt-2.yml" --env ascend-local` passes
- [ ] `bru run "platform/observability/weather-tool-prompt.yml" --env ascend-local` passes
- [ ] Waited 30 seconds
- [ ] Queried `gen_ai_client_token_usage_total` and `prompt_cache_tokens_read_total` on Prometheus
- [ ] Searched Tempo for `service.name=ascend-agent` and fetched the weather trace
- [ ] Ran every panel query of the six dashboards against `http://localhost:7077/api/v1/query`

### Post-run cleanup

Run regardless of Run-step verdict. Every command is idempotent.

- [ ] Deleted Postgres `chat_history` rows where `user_id = 'frostyAiTrafficTest'`
- [ ] Deleted Redis key `chat:frostyAiTrafficTest`
- [ ] Deleted Redis key `user:frostyAiTrafficTest:instructions`
- [ ] `POST http://localhost:7020/api/v1/memory/wipe?user_id=frostyAiTrafficTest` returned `{"status":"success", ...}`

### Expected

- [ ] All four Bruno requests answer HTTP 200 with non-empty `content`, and the weather answer carries a temperature and a condition word, never a live-data refusal
- [ ] `gen_ai_client_token_usage_total` holds a series for provider `openai` and a series for provider `anthropic`
- [ ] `prompt_cache_tokens_read_total{provider="anthropic"}` grew after the second Anthropic prompt
- [ ] The weather trace holds a span whose name starts with `chat` or `spring_ai` and a span for the MCP tool call
- [ ] Every panel query of the six dashboards returns at least one series or names an unused provider in `docs/OBSERVABILITY.md`
- [ ] No assertion matched the text of a log line

### Verdict

- [ ] Verdict: PASS / FAIL (delete the wrong one)

## Result summary



Input tokens:

Output tokens:

Start (UTC):

End (UTC):

Duration:

---

## Additional tasks I did

<!-- Optional. List anything outside the spec, e.g. diagnostic curls, manual log inspection, retries with different inputs. Leave empty if nothing extra. -->
