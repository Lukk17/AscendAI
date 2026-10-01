# ADR-009: A finished result is a Markdown file in object storage, and the state carries its address

## Status

Accepted — 2026-09-24.

## Context

[ADR-008](ADR-008-every-request-is-a-job.md) makes every request a job, which raises a question that a synchronous
response never had to answer: where does the recognised text live between the moment the reading finishes and the
moment a caller collects it?

The first draft of that change had the status answer carry the complete result inline, so that collecting cost no
further call. That was sized against a forty page ceiling and an estimated 100 KB result. At a hundred pages of a
dense scan the result is megabytes, and a caller polls the status resource every few seconds, so every poll would
carry the risk of a multi-megabyte body and the last one would certainly carry it.

The platform already runs S3-compatible object storage, locally Floci on port 9070. The ascend-ai-agent already
addresses it with the AWS SDK: `AppConfig.s3Client()` builds a client with an endpoint override, `us-east-1` because
the local emulator reports that region, static credentials and path-style addressing, `BucketInitConfig` heads the
bucket at startup and creates it when missing, and `S3PresignedUrlService` signs GET URLs against a separately
configured public endpoint. This service's own SSRF allowlist already names the host that storage lives on.

## Decision

A successful reading writes one Markdown object, `{job_id}.md`, to `OCR_RESULT_S3_BUCKET`, and the status answer
carries its address rather than its content.

- The object is written **before** the terminal record, so a record never claims success with no result behind it.
- The Markdown is the document's text and nothing else: one level-two heading per page naming the page number, then
  that page's recognised lines in reading order, one per line. No front matter, because whatever fetches it indexes
  it as the document's text and would index a YAML block as body text, and because the record already carries the
  metadata.
- The status answer for successful work carries the bucket, the key, a presigned GET URL, and the description that
  does not grow with the document: `schema_version`, `filename`, `language`, `page_count` and
  `processing_time_seconds`. The rule is one line long and worth stating as a rule: what is bounded stays in the
  status body, what grows goes to the object.
- The presigned URL is signed against `OCR_RESULT_S3_PUBLIC_ENDPOINT` for the record's remaining retention, so it can
  never outlive the object it points at, and it is regenerated on each status read rather than stored.
- Deleting the job deletes the object. The retention sweep deletes the object. Both delete the object before the
  record that names it, so a failure part-way through leaves a record pointing at nothing rather than an object
  nothing points at.
- The bucket is headed at startup and created when missing, the way `BucketInitConfig` does it in the agent, and a
  failure is a `WARNING` in the startup banner rather than a refusal to boot, which is the same "warn, do not refuse"
  posture the module already takes for the cgroup memory check.
- Five settings, each mirroring the property the agent already uses for the same store:
  `OCR_RESULT_S3_ENDPOINT`, `OCR_RESULT_S3_PUBLIC_ENDPOINT`, `OCR_RESULT_S3_BUCKET`, `OCR_RESULT_S3_ACCESS_KEY` and
  `OCR_RESULT_S3_SECRET_KEY`.

**Its own bucket, `ocr-results`, and not the agent's `knowledge-base`.** The agent's `ManualIngestionService` lists
and ingests whatever it finds in `knowledge-base`, so an OCR result written there would be picked up as a new source
document and indexed as if a human had uploaded it. A dedicated bucket also makes a lifecycle rule safe to write:
because nothing else writes to it, expiring everything older than the retention window is correct there and is how an
object left behind by a partial failure is eventually collected.

**The job record stays local.** It is a JSON file under `OCR_JOBS_DIR`, written on every transition and read on every
poll. That is a chatty small-object workload a local file serves better than a bucket, and keeping it local is what
lets the service record that a job failed even when the bucket is the thing that failed.

## Consequences

**This module gains an external service dependency it did not have.** That is the real price, and the split above is
what contains it: a bucket outage cannot stop the service accepting work, reading it, or recording that something
failed. What a bucket outage stops is delivery.

**An upload that fails after bounded retries fails the job** with a record-level `RESULT_STORE_UNAVAILABLE` reason,
marked retryable in the same way `SERVICE_RESTARTED` is, because nothing was learned about the document. Losing
seventeen minutes of reading to a bucket blip is the failure mode, and the bounded retries are what keep it rare.

**Readiness is deliberately not wired to the bucket.** A blip would flap `/ready` for a queue that is perfectly able
to keep reading, and [ADR-004](ADR-004-liveness-readiness-split.md)'s rule is that not-ready means the service cannot
take work. The startup check and the job metrics are where a bucket problem shows.

**Collecting costs one more fetch**, against the object store rather than against this service.

**Per-line `confidence` and `bounding_box` are not in the Markdown.** `OcrTextLine` still carries both inside the
service, and nothing in the platform reads either: the agent flattens to text, the Bruno requests assert substrings
and the e2e specs assert canaries. A caller that needs them later gets a structured sibling object beside the
Markdown, which is an addition rather than a change.

**The text the agent indexes changes shape slightly**, because the Markdown carries page headings the flattened JSON
did not. That is an improvement for attribution and it is still a caller-visible difference.

**The bucket must allow neither anonymous listing nor anonymous reads.** The object key is the job identifier, which
is the only credential a result has. Listing would enumerate every result, and a public read would leave that
identifier's unguessability as the only thing between the internet and a document's text, with no rate limit in front
of it. The deployment view states this as a requirement of the bucket rather than as advice.

**A result is a document's own text, sitting in the platform's storage for up to an hour** on a service with no
authentication. The retention window is one setting, a caller can delete earlier, and the identifier is 128 bits from
a cryptographic source, never derived from the filename or the content.

## Alternatives considered

**The inline result the first draft chose.** Collecting costs no further call, which is genuinely nicer for a small
document. It loses on the large one it exists to serve: a multi-megabyte body on a resource designed to be polled
every few seconds.

**The agent's `knowledge-base` bucket.** Rejected above: the agent's own ingestion would index OCR results as source
documents.

**Bucket and key only, with every caller bringing credentials.** Rejected because Bruno, curl and the e2e suite then
cannot collect a result at all, and the whole change becomes untestable from outside Java.

**A presigned URL only.** Rejected because the agent already holds an S3 client for that endpoint, and bucket and key
is the cheaper path for it.

**Redis for the record instead of files.** The platform runs one. A job store that is unreachable would make every
request fail while the OCR engine itself is perfectly healthy, and after ADR-008 every request goes through the store.
Accepting a dependency for the result is a trade this ADR makes deliberately; accepting a second one for the record
would mean the service could not even tell a caller that its work had failed.

**SQLite for the record.** There is exactly one writer, no query beyond fetch by identifier and enumerate the
non-terminal ones, and at most a few hundred records inside a retention window. It would buy transactions this design
has no use for and add a schema to migrate.
