# ADR-007: Auto-ingestion Defaults to OFF

## Status

Accepted — 2026-05-08

## Context

AscendAgent has two ingestion paths into the Qdrant RAG store:

1. **Manual** — operator uploads via `POST /api/v1/ingestion/upload` (or drops files into MinIO directly), then explicitly calls `POST /api/v1/ingestion/run` to scan and embed.
2. **Auto-poller** — a background Spring Integration `@InboundChannelAdapter` polls the MinIO bucket on a fixed interval and ingests new or changed files without operator action.

Both paths share the same downstream pipeline (`DocumentRouter` → splitter → embedder → vector store). The question is which one is the default.

## Decision

The auto-poller is gated behind `app.ingestion.auto.enabled` and **defaults to `false`**. Operators must explicitly opt in by setting this flag to `true` (env var or `application.yaml` override).

## Consequences

### Why off by default

- **No surprise embedding spend.** The auto-poller picks up *every* file that lands in the bucket. With paid embedding APIs (OpenAI, Gemini paid tier), an operator who drops a 500-page corpus into MinIO during exploration would burn a noticeable amount of credit before realizing it. Manual `/run` puts that decision in the operator's hands.
- **No surprise startup latency.** The poller contributes work to the startup path. Off by default keeps `bootRun` fast for development.
- **Predictable test behavior.** End-to-end tests assume the corpus is what the test set up, not whatever Spring Integration happened to ingest in the background. Manual-only ingestion makes test state deterministic.
- **Aligns with the "explicit > implicit" principle.** Auto-ingestion is a power user feature; making it opt-in keeps the default safer and the failure modes simpler to reason about.

### Trade-offs

- **Manual step required.** Operators who want a "drop file and forget" workflow have to flip the flag once. Documented in `docs/INGESTION.md` under *Auto-poller (opt-in)*.
- **Forgotten ingestion.** A new operator who drops a file into MinIO and waits will see nothing happen until they call `/run` or read the docs. Mitigated by surfacing the manual flow as the primary path in `docs/INGESTION.md` and making the curl examples obvious in the testing docs.
- **Two code paths.** Both `ManualIngestionService` and `IngestionPipelineConfig` (the auto-poller channel adapter) carry near-identical ingest logic. We accept the duplication today; if a third trigger appears (webhook, schedule), they should be consolidated behind a single ingest service.

### Alternatives considered

- **Default ON.** Rejected on cost-surprise grounds.
- **Default ON with a "dry-run" first scan.** Adds complexity for marginal benefit; an operator who can read a startup log can also flip a flag.
- **Remove the auto-poller entirely.** Rejected because long-running deployments (production, shared dev box) genuinely benefit from automatic ingestion of dropped documents. Keeping it as opt-in preserves the option without imposing the cost.

## Related

- `app.ingestion.auto.enabled` — `application.yaml`
- `IngestionPipelineConfig.IngestionFlow` — `@ConditionalOnProperty(prefix = "app.ingestion.auto", name = "enabled", havingValue = "true")`
- `ManualIngestionService` — manual `/run` path
- `docs/INGESTION.md` — operator-facing description of both paths
- OpenSpec change `fix-ascend-agent-bugs`, Bug 11
