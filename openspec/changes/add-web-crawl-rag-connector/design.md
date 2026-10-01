## Context

`add-document-connectors` defines a connector contract: land bytes in object storage under the tenant prefix, then
trigger the existing ingestion. `enhance-web-search-crawl-at-scale` writes crawl output to its own bucket and prefix
with a `pages.ndjson` index that marks each page new, changed or `unchanged`.

## Decisions

### D1: The connector copies, it does not parse

The connector reads `pages.ndjson`, copies the page files of new and changed pages into the tenant prefix, and calls
the framework's ingestion trigger. Parsing, chunking and embedding stay in the existing pipeline.

### D2: Polling with a bounded wait

The connector polls the crawl job with the `poll_after_seconds` hint until a terminal state or the run's deadline from
the framework. A timed-out run cancels the crawl with `DELETE /api/v1/crawl/jobs/{job_id}` and records the run failed.

### D3: Deletion by comparison

A URL present in the previous run's index and absent from this run's is deleted through the single-document deletion
path, recorded as `DELETED`.

## Risks

- A crawl that runs longer than the schedule interval: the framework's one-run-at-a-time rule per connector applies.
