## MODIFIED Requirements

### Requirement: Provider 429 and 502 handling is checked end to end

The ascend-ai-agent end-to-end suite SHALL check, with the scripted model and no real model, how the agent answers a provider that refuses a chat request: a provider answer of 429 SHALL be retried up to the provider client's default retry count and SHALL then reach the caller as HTTP 429 with the agent's provider error problem body, a provider answer of 502 SHALL be retried, so a provider that recovers on the next attempt gives the caller its answer, and a provider that answers 502 on every attempt SHALL be given up on after the provider client's default retry count, with HTTP 502 within a bounded time (owner answer 73.2 of 2026-10-06). No configuration SHALL set a retry count for the provider `scripted` or any other provider (owner answer 90 of 2026-10-08), and the provider client SHALL be the only layer that retries, so a 429 or a 502 on every attempt counts exactly three chat requests and a 502 that recovers counts exactly two (the provider SDK's default is two retries after the first request, measured on 2026-10-06). The checks SHALL read the scripted model's request log to count the chat requests the agent sent, never a log line of the agent. A memory extraction request, which carries the system prompt of `SemanticMemoryExtractor`, SHALL NOT be counted. The checks SHALL stay rows of the one existing provider error spec, updated in place, never a new spec.

#### Scenario: Provider answers 429

- **WHEN** a prompt is sent with `provider=scripted` and the message `E2E-SCRIPT-HTTP-429`, and the scripted model answers 429 to every request
- **THEN** the answer is HTTP 429 with an `application/problem+json` body whose `code` is `provider_rate_limited` and whose `detail` starts with `AI provider error:` and contains no `{`
- **AND** the scripted model's request log holds exactly three chat requests with that marker

#### Scenario: Provider answers 502 once and then recovers

- **WHEN** a prompt is sent with `provider=scripted` and the message `E2E-SCRIPT-HTTP-502`, and the scripted model answers 502 to the first request and `E2E-SCRIPT-RECOVERED` to the next
- **THEN** the answer is 200 and its content holds `E2E-SCRIPT-RECOVERED`
- **AND** the scripted model's request log holds exactly two chat requests with that marker, not counting the memory extraction request that follows the successful turn

#### Scenario: Provider answers 502 on every attempt

- **WHEN** a prompt is sent with `provider=scripted` and the message `E2E-SCRIPT-HTTP-502-ALWAYS`, and the scripted model answers 502 to every request
- **THEN** the answer is HTTP 502 with an `application/problem+json` body whose `code` is `provider_error` and whose `detail` starts with `AI provider error:` and contains no `{`
- **AND** the answer arrives within 30 seconds of the request
- **AND** the scripted model's request log holds exactly three chat requests with that marker
