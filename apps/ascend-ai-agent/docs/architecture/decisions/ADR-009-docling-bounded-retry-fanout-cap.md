# ADR-009: Bounded Retry and Fan-out Cap for Docling Page Conversion

## Status

Accepted, 2026-09-03

## Context

ascend-ai-agent splits a PDF into one conversion request per page and dispatches those requests to Docling Serve in parallel (`DocumentRouter.dispatchPagesInParallel`), so a large document converts faster than one page at a time. Docling Serve runs behind a supervisor whose liveness watchdog kills a worker process outright the moment its heartbeat thread misses a five second window. Page conversion is CPU-bound work running in the same process as that heartbeat thread, so a page that takes long enough to convert starves the heartbeat and the supervisor kills the worker mid-request. The client then sees a connection reset, and that one dead page discarded the whole document rather than just itself.

Docling Serve's own configuration caps its usable throughput: it runs two uvicorn worker processes, each with a two-slot conversion queue (`eng_loc_num_workers=2`), for a real capacity of four concurrent CPU-bound conversions. The agent's page fan-out had no cap matching that number, so a document with more than four pages routinely exceeded Docling Serve's capacity and made a heartbeat miss likely.

This surfaced during the 2026-09-03 end-to-end sweep as the PDF summarization spec's only failure among all 45 specs run outside the storage group.

## Decision

Two changes address this, both scoped to the conversion path:

1. `DoclingClient.postWithRetry` retries only on `ResourceAccessException`, the exception Spring's `RestClient` raises for a connection-level failure such as the reset the watchdog produces. A bounded three attempts with a 500ms backoff between them is enough to land the retried request on a worker that has not been killed. Any other `RestClientException`, meaning a genuine HTTP 4xx or 5xx response from a worker that is still alive, is rethrown immediately with no retry, since that response already answered the request and retrying it would not change the outcome.
2. `DocumentRouter.pdfParallelPages` bounds the parallel page dispatch to four, matching Docling Serve's measured capacity of two workers times two conversion slots per worker. Dispatching within that bound keeps every in-flight conversion on a worker that can still service its own heartbeat.

Both changes were verified together across five consecutive clean end-to-end runs of the PDF summarization spec after the fix landed.

## Consequences

- A page killed by the watchdog now recovers within about a second (up to two retries at 500ms) instead of failing the whole document.
- A genuine conversion error, such as a corrupt page Docling Serve rejects with a 4xx, still fails immediately rather than being retried three times and delaying the failure.
- Throughput on documents with more than four pages is capped by `pdfParallelPages` rather than by page count, so a very large document converts in batches of four instead of all at once.
- The fan-out limit is tied to Docling Serve's current worker configuration. If that configuration changes, meaning the worker count, the queue depth per worker, or the watchdog's heartbeat window, `app.document-router.pdf-parallel-pages` needs re-tuning to match.
- The retry is scoped narrowly on purpose. Widening the catch to `RestClientException` would retry on every failure including genuine 4xx and 5xx responses, defeating the fail-fast behavior this decision exists to preserve. `DoclingClientTest.process_WhenRestClientFails_ThenThrowsIngestionException` asserts the fail-fast path makes exactly one attempt, so that regression fails the test suite rather than reaching production.

## Related

- `DoclingClient.MAX_ATTEMPTS`, `DoclingClient.RETRY_BACKOFF_MILLIS`, `DoclingClient.postWithRetry`
- `DocumentRouter.pdfParallelPages` (`app.document-router.pdf-parallel-pages`, default 4)
- Commit `0748356` ("test(e2e): run the full suite and fix what it exposed")
