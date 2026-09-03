## Context

See proposal.md, section Why, for motivation. This section records only the measured facts about the target that shape the approach.

Floci was probed live on the owner's machine before this change was written. The findings below are established and are the premise of every decision here, not assumptions to be tested during implementation.

- Containers `floci` (`floci/floci:2.0.1`) and `floci-ui` (`floci/floci-ui:0.4.0`) run in a compose project named `local-dev` owned by a different repository. Host port `9070` maps to the emulator's internal AWS edge port `4566`, and host port `9071` maps to the UI's `4500`. These are the same host ports MinIO used, so no endpoint value in this repository changes.
- The S3 API answers unauthenticated. A plain `GET http://localhost:9070/` returns a valid `ListAllMyBucketsResult`. Credentials are not validated at all, so any value works.
- Bucket region reports `us-east-1`, which matches the hardcoded `Region.US_EAST_1` in the agent's S3 client at `AscendAgent/src/main/java/com/lukk/ascend/ai/agent/config/AppConfig.java:62-132`.
- The `knowledge-base` bucket does not exist on it yet. Only `local-dev-bucket` does.
- MinIO's health path `/minio/health/live` returns 404. Floci's own health endpoint is `GET http://localhost:9070/_floci/health`, which returns JSON of per-service status including `"s3":"running"`.
- Floci exposes no Prometheus metrics anywhere. `/q/metrics`, `/metrics` and `/_floci/metrics` on port 9070 all return 404, and `/metrics` on 9071 is only the UI's HTML fallback.
- The unauthenticated write contract was probed on 2026-09-03 against a scratch bucket named `floci-contract-probe`, and every verb the runbook rewrite depends on answers without credentials. `PUT` of a bucket returns 200, `PUT` of an object returns 200, `GET` returns the bytes byte-for-byte, `DELETE` of an object returns 204, and `DELETE` of an emptied bucket returns 204. Listing with `?list-type=2` returns `ListBucketResult` and honours `&prefix=`. Repeating `PUT` of an existing bucket returns 200 rather than the `409 BucketAlreadyOwnedByYou` that real S3 sends, so a bucket-create step is idempotent on a plain 200. Absent resources return proper S3 error XML with HTTP 404, `<Code>NoSuchKey</Code>` for a missing object and `<Code>NoSuchBucket</Code>` for a missing bucket, which is what lets a runbook distinguish "absent" from "broken". The full command and status list is in implementation-notes.md.

Two constraints follow from the environment rather than from Floci. The AWS CLI is not installed on this machine, and the `mc` client only ever existed inside the MinIO container, which no longer exists. So any replacement for the runbook commands has to work with tooling that is already present.

## Goals / Non-Goals

Goals:

- Every operator path in the repository works against Floci without the operator installing anything.
- A Floci-specific S3 behavior gap fails in the integration test suite rather than at runtime.
- The repository stops naming a product it no longer runs, in code, in configuration, in dashboards, and in prose.
- Nothing in the running system changes shape: same endpoint, same bucket, same credentials, same presigned-URL contract.

Non-Goals:

- Adding Floci to any compose file in this repository. It stays an external prerequisite exactly as MinIO was, and defining it here would collide with the `local-dev` project that already owns it.
- Abstracting the object store behind an interface so both MinIO and Floci are supported. There is one object store on this machine and the AWS SDK is already the abstraction.
- Replacing the deleted MinIO Prometheus scrape jobs with equivalent Floci scraping. Floci publishes no metrics, so there is nothing to point at, and inventing an exporter is a separate piece of work nobody asked for.
- Changing bucket names, credentials, ports, or the `app.s3` property shape.

## Decisions

### Decision 1: the object store stays an external prerequisite, not a compose service

Floci already runs, owned by another repository's `local-dev` compose project. Defining a `floci` service here would create two containers competing for host ports `9070` and `9071`, and the memory note on always using the main `docker-compose.yaml` exists precisely because parallel projects collide on shared names.

Alternative considered: vendor a Floci service definition into `docker-compose.yaml` so the stack is self-contained. Rejected because it contradicts ADR-M003, which deliberately moved the data layer out of compose, and because it would break the owner's machine the moment both projects are up.

### Decision 2: the runbooks talk to the S3 REST API directly with `curl`

Every `mc` invocation in the e2e suite and in `docs/TROUBLESHOOTING.md` gets a direct HTTP equivalent. Floci does not validate credentials, so no request signing is needed and `curl` alone is sufficient. The mapping is exact for every command in use today.

| Current command | Replacement |
| --- | --- |
| `mc alias set local ...` | Deleted. There is no alias to register when every call carries the full URL. |
| `mc --version` (client-present probe) | Deleted. Replaced by the health probe below, which is what the step was actually checking. |
| `curl -fsS http://localhost:9070/minio/health/live` | `curl -fsS http://localhost:9070/_floci/health` |
| `mc ls local/knowledge-base/markdown/` | `curl -fsS "http://localhost:9070/knowledge-base?list-type=2&prefix=markdown/"`, which returns `ListBucketResult` XML |
| `mc rm --force local/knowledge-base/documents/<key>` | `curl -fsS -X DELETE "http://localhost:9070/knowledge-base/documents/<key>"` |
| `mc cp <file> local/e2e-fixtures/<key>` | `curl -fsS -X PUT --data-binary "@<file>" "http://localhost:9070/e2e-fixtures/<key>"` |
| `mc mb --ignore-existing local/e2e-fixtures` | `curl -sS -o /dev/null -w '%{http_code}' -X PUT "http://localhost:9070/e2e-fixtures"`, treating both `200` and the `409 BucketAlreadyOwnedByYou` response as success |
| `mc anonymous set download local/e2e-fixtures` | Deleted. Floci does not authenticate reads, so objects are already anonymously readable and there is no policy to set. |
| `mc rb --force local/knowledge-base` | `curl -sS -X DELETE "http://localhost:9070/knowledge-base"`, after deleting the objects under it, since S3 requires an empty bucket. The bucket is always named explicitly. See decision 5. |

Alternative considered: install the AWS CLI and use `aws s3` with dummy credentials. Rejected because it adds a prerequisite to every runner host purely to restate what `curl` already does against an endpoint that ignores the credentials the CLI would attach. Alternative considered: run `mc` from a throwaway `minio/mc` container. Rejected for the same reason, plus it reintroduces the MinIO name into a stack that no longer has MinIO.

The mapping originally rested on write behavior that had not been probed, since only unauthenticated `GET` of the bucket list had been exercised. Task 1.1 has now probed the rest against the live instance and every verb in the table answers unauthenticated, so the mapping stands as written and no fallback is needed. The one deviation from real S3 is that repeating a bucket `PUT` returns 200 rather than 409, which only widens what counts as success for the bucket-create row. The measured statuses are in implementation-notes.md.

### Decision 3: integration tests run Floci, not MinIO

`TestcontainersBase.java:57-59` swaps `MinIOContainer` for a `GenericContainer` on `floci/floci:2.0.1` exposing `4566`, and `org.testcontainers:minio` is dropped from `AscendAgent/gradle/libs.versions.toml:91` and `AscendAgent/build.gradle.kts:105`.

The reason is coverage of the real risk. The application talks to the object store through the AWS SDK, and the SDK's behavior is identical against both. What is not identical is Floci's own S3 implementation, which is a young project. `BucketInitConfig` calls `CreateBucket` at startup, `StorageService` puts and gets objects, `S3PresignedUrlService` signs URLs and issues `HEAD`, and `ManualIngestionService` lists a prefix. If Floci implements any of those differently, that must surface in `./gradlew integrationTest` rather than the first time someone uploads a document.

The container needs a readiness strategy, and the natural one is the same health endpoint the runbooks use: wait for `GET /_floci/health` on the mapped port to return 200. `MinIOContainer` supplied `getS3URL()`, `getUserName()` and `getPassword()`, and `GenericContainer` does not, so the three `registry.add` calls at `TestcontainersBase.java:80-82` become an explicit URL built from `getHost()` and `getMappedPort(4566)` plus literal credentials. Since Floci ignores credentials, the literals can match `application.yaml` (`admin` / `password`) so test and runtime configuration read the same.

Alternative considered: keep MinIO in Testcontainers because it is a known-good S3 and the tests are about the agent, not the store. Rejected, and this is the central call of the change: keeping MinIO in tests would mean the suite is green while the developer's actual stack is the one thing never exercised.

### Decision 4: MinIO observability is deleted, not repointed

Floci publishes nothing to scrape. Both Prometheus jobs at `observability/prometheus/prometheus.yaml:76-92` and both Grafana panels plus their row at `observability/grafana/dashboards/infrastructure.json:70-124` come out, and the dashboard description at `:8` loses its MinIO clause.

Alternative considered: leave the scrape jobs in place so the intent survives for a future exporter. Rejected because a permanently-down target is noise that trains an operator to ignore the target list, which is worse than an honest gap. Alternative considered: write a small exporter that polls `/_floci/health` and the bucket listing and exposes object counts. Rejected as unrequested scope, and it belongs to the pending `add-observability` change if anyone wants it.

Object-count and bucket-size panels are lost. That is the accepted cost.

### Decision 5: every destructive object-store command names the bucket it acts on

The rule is about scoping, not about destructiveness. Deleting a bucket by its explicit name is fine and stays in the runbooks where they already have it, because it is no more dangerous than it was under MinIO, whose instance was equally shared between this project's services. The only buckets a step may delete are `knowledge-base` and `e2e-fixtures`, both of which this repository owns, and `knowledge-base` is recreated at startup by `BucketInitConfig` anyway, so `docs/TROUBLESHOOTING.md:39-55` keeps its bucket-level recipe and only changes client. In S3 a bucket must be emptied before it is deleted, so the recipe deletes the objects first and then the named bucket.

What is banned is any operation that is not scoped to a bucket named in the command: no wildcard, no "delete every bucket", and no reset that lists the endpoint's buckets and removes what it finds. The reason is that this Floci instance also holds `local-dev-bucket`, which belongs to a different repository's compose project, so an unscoped command reaches outside AscendAI and destroys something this repository never created.

This is written into the `ai-driven-e2e-runner` delta as a normative constraint rather than left to discipline, because it is exactly the kind of rule that erodes.

### Decision 6: naming convention in prose and identifiers

Where the text is about the contract, use "the S3-compatible object store" or just "S3". Where the text is about the concrete local dependency an operator must have running, name Floci and its version. So `application.yaml` comments say S3, the prerequisite tables in `README.md` and the `AGENTS.md` files say Floci with the port pair, and the startup banner label at `StartupLogConfig.java:126` becomes `"S3 (Floci):   "` with the exact column padding preserved, because `StartupBannerIT.java:80` asserts on the literal.

Architecture documents sit firmly on the contract side and do not name the vendor at all, because the vendor is a local-development detail that has already changed once and will change again, and a diagram or an arc42 chapter that hardcodes it goes stale on the next swap. So `docs/architecture/decisions/ADR-M003-external-infrastructure-prerequisites.md`, its index entry, and every arc42 chapter and architecture diagram under `docs/architecture/`, `AscendAgent/docs/architecture/`, `PaddleOCR/docs/architecture/`, and `AudioScribe/docs/architecture/` say S3-compatible object storage, and name the implementation only as an aside, for example "S3-compatible object storage, provided locally by Floci and by Amazon S3 in production". ADR-M003 is renamed in place for the same reason and no ADR-M004 supersedes it, since what it decided was the pattern of keeping infrastructure outside compose and the product behind the S3 API is an implementation detail of that pattern.

Operator-facing documents are the opposite case and name Floci concretely, because their reader needs to know what to open and what to type. That is the quick-start sections of the READMEs, `docs/TROUBLESHOOTING.md`, `docs/INGESTION.md`, and every e2e runbook. Task group 8 is split along this line and names the files on each side.

Test identifiers follow the same rule. `BackingServicesIT.minio_isReachableAndBucketCreated` becomes `objectStore_isReachableAndBucketCreated` rather than `floci_...`, because the assertion is about the S3 contract and would still hold if the backing product changed again. The placeholder hosts in `S3PresignedUrlServiceTest` move from `https://minio.example/...` to `https://s3.example/...` for the same reason, and the `minioadmin` credential fixtures at `AppConfigVectorStoreInitTest.java:132-135` become `admin` / `password` to match the real configuration.

### Decision 7: this change does not rewrite other pending OpenSpec changes wholesale

Eleven pending changes name MinIO across 42 files. Two of them state things that directly contradict what this change ships: `harden-cloud-deployment` specifies `MCP_ALLOWED_HOSTS` defaulting to `minio` and an environment variable named `MINIO_SECRET_KEY`, and `add-observability` specifies a `minio` Prometheus scrape target as a required health check. Those two get a targeted correction in task 9.3. The other nine are incidental prose that will be corrected naturally when each change is implemented, and editing an unapproved proposal on someone else's behalf is not this change's business. That is settled, not open.

## Risks / Trade-offs

- Floci does not implement `CreateBucket` the way the SDK expects, so `BucketInitConfig` never creates `knowledge-base` and every ingestion path fails silently until someone looks. → Task 1.2 verifies it explicitly against a Floci with no `knowledge-base` bucket, which is the current state of the machine, and this is checked before any other task runs.
- Unauthenticated `PUT` or `DELETE` is rejected even though unauthenticated `GET` works, which would invalidate most of the command mapping in decision 2. → Retired. Task 1.1 probed bucket create, object put, object get, listing, object delete, and bucket delete against the live instance on 2026-09-03 and all six answer unauthenticated, so the mapping in decision 2 holds.
- Floci's presign verification differs from MinIO's, so `S3PresignedUrlService` produces URLs that Floci rejects. → The endpoint ignores credentials entirely, so a signed URL should resolve as a plain GET with extra query parameters. Task 1.3 asserts an actual presigned URL fetch against the running agent before anything is rewritten, and task 3.7 pins it in the integration suite.
- The `floci/floci:2.0.1` image is slow to become ready under Testcontainers and lengthens `integrationTest`. → The readiness wait targets `/_floci/health` rather than a fixed sleep, and task 3.10 records the before-and-after wall-clock time of the suite so a regression is visible rather than folklore.
- The e2e suite is rewritten against command shapes that were verified once, then drift when Floci is upgraded past `2.0.1`. → The version is pinned in the Testcontainers base class, so a Floci upgrade that breaks the S3 surface fails the integration suite before anyone runs the e2e suite.
- Deleting the MinIO Grafana row leaves the infrastructure dashboard thinner, and nobody notices the object store is full until ingestion fails. → Accepted. The health probe at `/_floci/health` is the remaining signal, and restoring quantitative panels is scoped to whoever picks up `add-observability`.
- The sweep is 77 files and a partial pass leaves the repository describing two different object stores at once, which is worse than describing one wrong one. → Task 10.1 is a repository-wide grep with an explicit expected-remainder list, so "done" is a number rather than a feeling.

## Migration Plan

There is no data migration. Floci starts empty and the RAG corpus is re-ingestible from source files, so the sequence is a configuration and documentation catch-up, not a cutover.

Order matters only at the front. Task group 1 proves Floci actually satisfies the contract the code assumes. If it does not, the whole approach changes and nothing later is worth doing. After that, groups 2 through 9 touch disjoint file sets and can be handed to separate implementers in parallel, with group 7 gated on group 1 alone, and group 10 running last.

Rollback is `git revert` of the range. Nothing here writes to a datastore, changes a schema, or alters an API contract, so reverting restores the previous documentation and test wiring exactly. The one thing a revert does not restore is MinIO on the owner's machine, which is outside this repository either way.
