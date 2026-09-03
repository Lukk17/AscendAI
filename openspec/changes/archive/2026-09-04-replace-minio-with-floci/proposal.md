## Why

The owner's local development machine no longer runs MinIO. The object store on host ports `9070` / `9071` is now [Floci](https://floci.io) ([floci-io/floci](https://github.com/floci-io/floci)), an MIT-licensed local AWS emulator and an open-source alternative to LocalStack Community. It runs as containers `floci` (`floci/floci:2.0.1`) and `floci-ui` (`floci/floci-ui:0.4.0`) inside a separate compose project named `local-dev` that belongs to a different repository, so for AscendAI it is an external prerequisite in exactly the way MinIO was.

The swap is already done on the machine, and this repository has not caught up. The consequences are not cosmetic. MinIO's health path `/minio/health/live` now returns 404, so every runbook precondition check fails. There is no container named `minio` and no `mc` client, so every reset and cleanup step in the e2e suite fails. Two Prometheus scrape jobs point at MinIO metrics paths that no longer exist, so they are permanently down and one Grafana dashboard row renders empty forever. And 139 files across the monorepo still tell a reader that the object store is MinIO.

## What Changes

The application code needs no structural change. Every S3 call already goes through AWS SDK v2 (`software.amazon.awssdk:s3` 2.42.34) and there is no `io.minio` dependency anywhere in the repository. Floci speaks the same S3 API on the same host port, reports the same `us-east-1` region the client hardcodes, and does not validate credentials at all. So the runtime surface is unchanged and the work is naming, tooling, observability, and documentation.

Runtime configuration and Java:

- Rename the MinIO references in `AscendAgent/src/main/resources/application.yaml` (the `app.s3` block at `:91-100`, the presigned-URL comment at `:283-285`) and `AscendAgent/src/main/resources/application-docker.yaml:8-13`. The values themselves do not move: endpoint stays `http://localhost:9070`, bucket stays `knowledge-base`, credentials stay `admin` / `password`.
- Rename the comment in `config/AppConfig.java:104` and the startup banner label `"S3 (MinIO):   "` in `config/StartupLogConfig.java:126`. No wiring changes in `AppConfig.java:62-132`, `BucketInitConfig.java`, `IngestionPipelineConfig.java`, `service/storage/StorageService.java`, `service/rag/S3PresignedUrlService.java`, or `service/ingestion/ManualIngestionService.java`.

Tests:

- Replace the `MinIOContainer` in `AscendAgent/src/test/java/com/lukk/ascend/ai/agent/integration/TestcontainersBase.java:57-59` with a `GenericContainer` running `floci/floci:2.0.1` exposing `4566`, and drop the now-unused `testcontainers-minio` dependency from `AscendAgent/gradle/libs.versions.toml:91` and `AscendAgent/build.gradle.kts:105`. The point is that any Floci-specific gap fails in the integration suite rather than at runtime.
- Follow the rename through `StartupBannerIT.java:80`, `StartupLogConfigTest.java:208`, `BackingServicesIT.java`, `IngestionEndToEndIT.java`, `AppConfigVectorStoreInitTest.java:132-135`, `S3PresignedUrlServiceTest.java`, and `src/test/java/com/lukk/ascend/ai/agent/integration/README.md`.

Observability:

- Delete the `minio` and `minio-bucket` scrape jobs at `observability/prometheus/prometheus.yaml:76-92`, and delete the MinIO row and its two panels at `observability/grafana/dashboards/infrastructure.json:70-124` along with the dashboard description at `:8`. Floci publishes no Prometheus metrics on any path, so there is nothing to repoint them at. This is a removal, not a replacement.

Compose:

- Remove the literal `minio` hostname from `MCP_ALLOWED_HOSTS` at `docker-compose.yaml:236` and rewrite the SSRF-allowlist comments at `:65-67` and `:233-236`. No compose file in this repository defines a MinIO service today, and none will define a Floci service either. Floci stays an external prerequisite.

Operator runbooks, which carry the deepest coupling:

- **BREAKING** for anyone running the e2e suite against a MinIO-backed stack. Every reset, seed, and cleanup step in the AscendAgent, PaddleOCR, and AudioScribe e2e specs and their tasks-templates uses the `mc` client inside a container named `minio`, and every precondition check curls `/minio/health/live`. Those are replaced with plain HTTP calls against `http://localhost:9070` and a health probe against `http://localhost:9070/_floci/health`. The old commands stop working, and the new ones will not work on a MinIO host.

Documentation:

- Sweep 77 files outside `openspec/` that name MinIO. The sweep runs in two halves that follow opposite naming rules, and task group 8 is split along that line.
- The architecture half is vendor-neutral. `docs/architecture/decisions/ADR-M003-external-infrastructure-prerequisites.md`, its index entry, and every arc42 chapter and diagram under `docs/architecture/` and `AscendAgent/docs/architecture/`, `PaddleOCR/docs/architecture/`, and `AudioScribe/docs/architecture/` describe the prerequisite as S3-compatible object storage. The concrete implementation is named only as an aside, for example "S3-compatible object storage, provided locally by Floci and by Amazon S3 in production". The reason is that the vendor is a local-development detail that has already changed once and will change again, and an architecture document that hardcodes it goes stale on the next swap.
- The operator half names Floci concretely, because the reader needs to know what to open and what to type. That is the quick-start sections of `README.md`, `AscendAgent/README.md`, `PaddleOCR/README.md`, and `AudioScribe/README.md`, plus `docs/TROUBLESHOOTING.md`, `docs/INGESTION.md`, `AscendAgent/docs/CONFIGURATION.md`, `docs/DEPLOYMENT.md`, `docs/OBSERVABILITY.md`, `observability/README.md`, the external-prerequisite tables in `AGENTS.md` and `AscendAgent/AGENTS.md`, and every e2e runbook and README. The MinIO console on `9071` becomes the Floci UI on `9071`, so console instructions are rewritten rather than deleted.

## Capabilities

### New Capabilities

None. Floci occupies the same architectural slot MinIO did, behind the same S3 API on the same port, so no new behavior is introduced.

### Modified Capabilities

- `rag-source-attachments`: the presigned-URL requirements name MinIO as the signing backend, and one scenario pins `app.s3.endpoint=http://minio:9000`. Both become object-store-neutral, and the scenario moves to the Floci topology where the agent and the caller reach the same host endpoint.
- `ascend-agent-containerization`: the external-prerequisite list names MinIO in the `docker` profile requirement and in the `extra_hosts` requirement. Both become Floci.
- `ai-driven-e2e-runner`: the reset-tooling requirement mandates `docker exec <container> <cmd>` for clients not guaranteed on the host and carries a scenario whose expected output is literally `docker exec minio sh -c 'mc alias set local http://localhost:9000 "$MINIO_ROOT_USER" "$MINIO_ROOT_PASSWORD"'`. Object-store reset moves to host-side HTTP against the S3 endpoint, which needs no client and no container name.
- `rag-documentation`: the `AscendAgent/README.md` content requirement describes putting files into "the `knowledge-base` MinIO bucket". The bucket name is unchanged, the product name is not.

## Impact

Code and configuration:

- `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/` (`AppConfig.java`, `StartupLogConfig.java`), comments only.
- `AscendAgent/src/main/resources/application.yaml`, `application-docker.yaml`, comments only.
- `AscendAgent/src/test/java/com/lukk/ascend/ai/agent/` (7 files plus one README), one of which is a real container swap.
- `AscendAgent/gradle/libs.versions.toml`, `AscendAgent/build.gradle.kts`, one dependency removed.
- `docker-compose.yaml`, one environment value and three comments.
- `observability/prometheus/prometheus.yaml`, `observability/grafana/dashboards/infrastructure.json`, deletions.

Python services: naming only. `AudioScribe/src/config/config.py:79-82`, `AudioScribe/src/adapters/download_service.py:19-22,61-63`, `AudioScribe/tests/config/test_config.py`, `AudioScribe/tests/adapters/test_download_service.py`, `AudioScribe/mcp_requests.http`, and the same comment-only pattern in PaddleOCR. Neither service has any MinIO SDK coupling.

Runbooks: 6 e2e specs and 5 tasks-templates across three modules, plus 5 e2e README files. Historical run records under `*/e2e/testing/runs/` are evidence of past executions and are deliberately left untouched.

Dependencies: `org.testcontainers:minio` is removed. Nothing is added, because Floci is driven through `GenericContainer` and the AWS SDK already present.

Out of scope, deliberately:

- `openspec/changes/archive/**` (12 files across 3 archived changes). Archived changes are historical records.
- `.agents/skills/e2e-runbooks/SKILL.md` and `openspec/schemas/e2e-runbooks/**` (3 files). `AGENTS.md` states these are generated artifacts pulled from the [agent-standards](https://github.com/Lukk17/agent-standards) repository and must not be hand-edited. They are left entirely alone, and no upstream follow-up is raised either. No task in this change may touch them. See settled decision 3.
- `AscendWebSearch/src/assets/fanboy-annoyance.txt`. A vendored ad-blocklist whose matches are the substring inside domains such as `unicasacondominio.it`.
- Nine of the 11 pending, unimplemented OpenSpec changes that name MinIO. Only `harden-cloud-deployment` and `add-observability` are corrected, because only those two state something this change directly contradicts. See settled decision 2.

## Settled Decisions

The four judgement calls this proposal originally left open have been answered. They are recorded here as settled so no implementer has to ask again, and design.md carries the reasoning behind each one.

1. ADR-M003 is renamed in place, and architecture documents stop naming the vendor at all. No ADR-M004 is written. `docs/architecture/decisions/ADR-M003-external-infrastructure-prerequisites.md` keeps its identity and its index entry at `docs/architecture/decisions/README.md:11` is edited rather than superseded, because ADR-M003 decided the pattern that infrastructure lives outside compose, and the product behind the S3 API is an implementation detail of that pattern. On top of the rename, the ADR and every arc42 chapter and architecture diagram describe the prerequisite generically as S3-compatible object storage, naming the concrete implementation only as an aside, for example "S3-compatible object storage, provided locally by Floci and by Amazon S3 in production". Operator-facing documents are the opposite case and name Floci concretely, because their reader needs to know what to open and what to type. Task group 8 is split along that line and lists which files fall on which side.

2. Only the two pending changes that directly contradict what this change ships are corrected. `harden-cloud-deployment` specifies an environment variable named `MINIO_SECRET_KEY` and an `MCP_ALLOWED_HOSTS` default of `minio`, and `add-observability` specifies a `minio` Prometheus scrape target as a required health check. Both are corrected in task 9.3. The other nine pending changes that mention MinIO are left untouched, and each is corrected naturally when it is implemented.

3. The generated agent-standards artifacts are left entirely alone. `.agents/skills/e2e-runbooks/SKILL.md`, `openspec/schemas/e2e-runbooks/README.md`, and `openspec/schemas/e2e-runbooks/templates/proposal.md` are not edited here, and no upstream follow-up is raised in [agent-standards](https://github.com/Lukk17/agent-standards) either. They illustrate a reset pattern rather than describing this stack, so the example does not need to change. No task in this change may touch them, and task 10.1 lists them as expected remainders of the final sweep.

4. Bucket-level deletion stays in the runbooks, scoped to an explicitly named bucket. Deleting `knowledge-base` or `e2e-fixtures` by name is no more dangerous than it was under MinIO, whose instance was equally shared between this project's services, and the agent recreates `knowledge-base` at startup through `BucketInitConfig` anyway. What must not appear anywhere is an operation that is not scoped to a named bucket: no wildcard, no "delete every bucket", and no reset that enumerates the endpoint's buckets and removes what it finds. The reason is scoping rather than destructiveness, because this Floci instance also holds `local-dev-bucket`, which belongs to a different repository's compose project, so an unscoped command would destroy something outside this repository.

## Relevant Skills

Load these before implementing the matching task group.

- `springboot-verification`: task groups 1, 3 and 10, the Floci contract probes, the Testcontainers swap, and the final build.
- `springboot-patterns`: task group 2, the agent configuration and the startup banner.
- `python-patterns`: task group 4, the AudioScribe and PaddleOCR naming pass.
- `deployment-patterns`: task groups 5 and 8, the observability removal and the deployment documentation.
- `docker-patterns`: task groups 6 and 7, the compose allowlist edit and the container-facing runbook commands.
- `e2e-runbooks`: task group 7, the e2e specs and tasks-templates.
- `markdown-writer`: task group 8, both halves of the documentation sweep.
