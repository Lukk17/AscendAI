## MODIFIED Requirements

### Requirement: Six dashboards cover platform, AI pipeline, infrastructure, cost, quality, cache

Six Grafana dashboards SHALL be checked into `infra/observability/grafana/dashboards/` and provisioned at startup.

| Dashboard | Required panels |
|---|---|
| Platform Overview | request rate per service, error rate per service, p95 latency per service, JVM heap (Java services), Python process memory (Python services) |
| AI Pipeline | tokens per minute by model, provider mix (pie / bar), RAG hit-rate (above_threshold / total), memory parse-failure rate, MCP tool call rate by tool |
| Infrastructure | Qdrant collection sizes, Redis ops/sec and memory, Postgres connection count |
| Token Cost (L1) | Per-provider $/day computed via `gen_ai_client_token_usage_total` multiplied by the price series `token_price_usd_per_1k` that Prometheus records from `infra/pricing/pricing.yaml`. The dashboard holds no rate of its own |
| RAG Quality (L2) | Heatmap of `rag_top_score_bucket` over time; time-series of retrieval miss-rate; bar chart of ingestion-events-per-hour by source type; embedded Loki logs panel |
| Cache Hit Rate (L3) | `rate(prompt_cache_tokens_read_total[5m])` divided by the input series of `gen_ai_client_token_usage_total` (`gen_ai_token_type="input"`) per provider; absolute saved-token panel; 0%-flatline annotation per provider |

#### Scenario: Cache Hit Rate dashboard renders after representative traffic

- **WHEN** the stack has been running for 5 minutes and at least 4 chat prompts have been sent (2 against `provider=openai`, 2 against `provider=anthropic`)
- **AND** the `Cache Hit Rate` dashboard is opened
- **THEN** the per-provider cache-hit-rate panel reports a non-zero ratio for both `openai` and `anthropic` rows
- **AND** the absolute-saved-tokens panel reports a non-zero count

#### Scenario: Token Cost dashboard reflects pricing.yaml updates

- **WHEN** an operator edits `infra/pricing/pricing.yaml` to change a provider's `input_per_1k` rate
- **AND** Prometheus is restarted (`docker compose restart prometheus`)
- **THEN** the Token Cost dashboard's $/day panel for that provider reflects the new rate
- **AND** no other dashboard is affected

#### Scenario: Platform Overview renders non-empty data after stack startup

- **WHEN** the stack has been running for 1 minute and any prompt request has been served
- **AND** the `Platform Overview` dashboard is opened
- **THEN** every panel reports at least one data point

### Requirement: Pricing rates committed in version control

The per-provider $/1k-token pricing rates consumed by the L1 Token Cost dashboard SHALL be committed to `infra/pricing/pricing.yaml`. The file SHALL be a YAML map with a top-level `providers:` map keyed by provider name, each entry with the numeric fields `input_per_1k` and `output_per_1k`. It SHALL be the only place a rate is written: no dashboard and no rule file in git SHALL hold a copy. Updates SHALL go through git review. The agent SHALL read the same file for subagent run cost, so one file serves the dashboard and the run limits.

#### Scenario: Pricing file shape

- **WHEN** `infra/pricing/pricing.yaml` is read
- **THEN** it parses as a YAML map with a top-level `providers` map
- **AND** at minimum `providers` contains entries for `anthropic`, `openai`, `gemini`, `minimax`, `lmstudio`
- **AND** every entry has numeric `input_per_1k` and `output_per_1k` fields
