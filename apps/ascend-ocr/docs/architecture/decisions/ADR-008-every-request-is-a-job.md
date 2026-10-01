# ADR-008: Every request is a job, at every length, on both surfaces

## Status

Accepted — 2026-09-24.

## Context

Ask this service to read a twenty five page document and, before this decision, it refused before any work started:
`FILE_TOO_LARGE` and a 400, with an accepted limit of two pages. That limit was not a memory bound. It fell out of two
deadlines. `OCR_MAX_PAGES` was a derived property, `floor(OCR_REQUEST_TIMEOUT / OCR_PAGE_TIMEOUT_SECONDS)`, and the
deployed values were 300 s and 150 s, so the answer was two.

That was defensible when a page cost 51 to 94 seconds. After
[ADR-007](ADR-007-explicit-ocr-model-selection.md) moved the service to the `PP-OCRv6_small` pair, a page costs 4.1 s
at six lines and 10.0 s at fifty, and peaks at about 440 MB rather than 9.76 GB. (Corrected 2026-09-25: the 440 MB
figure missed the peak. Measured as a Linux container's cgroup peak, one A4 page at 300 dpi peaks at 1016 MiB and
takes 20.5 s on 4 CPUs, which still makes the argument below. See "Memory model and the single worker" in
[07-deployment-view.md](../arc42/07-deployment-view.md).) A limit of two pages derived from a
150 s per-page allowance was refusing a four minute job on the grounds that it might take an hour.

The ceiling existed for a good reason and this decision keeps the protection behind it. A twenty page document once
failed at 300 seconds while the worker carried on for a further thirty minutes computing an answer nobody would
receive, which is the incident `stop-ocr-getting-stuck-on-large-jobs` exists to end.

## Decision

Every request is a job. A submission is answered immediately with an identifier, the caller polls for the state, and
the recognised text is written to object storage
([ADR-009](ADR-009-results-in-object-storage.md)). There is no page count, no flag and no header at which the service
behaves differently, so there is one queue, one set of bounds and one refusal vocabulary.

Concretely:

- Four operations on each surface. REST: `POST /v1/ocr/jobs` (202 with the identifier and a relative `Location`),
  `GET /v1/ocr/jobs/{job_id}`, `GET /v1/ocr/jobs`, `DELETE /v1/ocr/jobs/{job_id}`. MCP: `ocr_submit`,
  `ocr_job_status`, `ocr_list_jobs`, `ocr_cancel_job`, taking the same arguments, returning the same records and
  raising the same codes.
- One service layer beneath both, so neither surface can offer an operation, a state or a bound the other does not.
- One queue, strict submission order, no priority classes, and no path to the worker except through its single
  consumer.
- The page ceiling becomes `OCR_JOB_MAX_PAGES`, a configured value with a stated derivation, and the reading ceiling
  is derived from it rather than the reverse. `OCR_REQUEST_TIMEOUT` and the derived `OCR_MAX_PAGES` are deleted.
- `OCR_PAGE_TIMEOUT_SECONDS` becomes the service's only configured time input, settled at 45 s, and every other
  duration the service enforces is a multiple of it. (Amended 2026-09-24 by
  [ADR-010](ADR-010-quality-modes-and-service-side-rendering.md): one allowance could not cover engines 8.5 times
  apart, so the only configured time input is now `OCR_PAGE_ALLOWANCE_HEADROOM`, a page is allowed that multiple of
  its own engine's worst measured page, and every duration is derived from that allowance.)

## Consequences

**What this buys.** A document's length stops being a function of any client's timeout, so the ceiling can be set from
what the service can afford rather than from what a caller will wait for. No reading is ever spent on a caller that
went away, because no caller is connected while a document is read. A caller that loses its connection at any moment
loses nothing: the identifier is enough to collect the result later.

**What it costs.** A one page image goes from one round trip to two against this service, plus one fetch against the
object store. That is the honest price of the property above, and it is paid by the common case to buy it for the
uncommon one.

**It is breaking on both surfaces**, and deliberately not softened the same way on each.
[ADR-003](ADR-003-versioning-strategy.md)'s own table makes removing an endpoint, removing a tool and changing what a
submission's answer means each breaking on its own. `POST /v1/ocr` is removed and answers 404 like any unknown
path. The first draft kept it answering 410 with an `ENDPOINT_REMOVED` code for one release window, and the owner
decided on 2026-10-01 to delete it outright instead, so no stub and no test of it remain. The `ocr_process` tool is removed outright, because a tool catalogue is discovered on every
connection, so a removed tool is simply a tool the model stops being offered, and a stub that only raises would cost
every caller context on every request.

**Waiting is bounded and reported, never failed.** The queue is bounded in pages, which converts directly into the
longest possible wait, and in documents, which bounds the disk the waiting submissions hold. A submission beyond
either bound is refused with `QUEUE_FULL` and a 503 rather than accepted into an unbounded wait. Nothing is ever
failed for having waited.

**A restart fails work in flight rather than resuming it**, with a distinct `SERVICE_RESTARTED` reason that marks the
work as safe to resubmit. Resuming is wrong for the reason the previous change already established: the service
cannot know whether the document it was reading is what brought it down, and a resume feeds the killer its input
again. Re-queueing work that was merely waiting is safer and was still rejected, because the service cannot
distinguish a deliberate restart from a crash loop.

**Cancelling actually stops the work.** A queued document is removed from the queue. A running one goes through the
same pool replacement path reclamation already uses, with `cancel` as a third trigger, and that path kills the worker
rather than draining it, because one work item is a whole document and `shutdown(wait=True)` alone would wait for the
document a cancel is asking to stop.

## Alternatives considered

**Keep the synchronous request and raise the ceiling.** The obvious cheap answer, and the speedup made it less
ridiculous than it was: twenty five clean pages now fit inside the agent's own 300 s read timeout. It loses on three
counts the speedup does not touch. The ceiling this change sets is a hundred pages, about seventeen minutes at the
measured cost, far outside every client timeout in the platform. The queue, not the reading, is now the dominant term:
one worker serving first in first out means a held connection waits for everything ahead of it, and that wait does not
shrink when inference gets faster. And FastAPI does not notice that a client has gone for an ordinary request handler,
so any held connection can be abandoned while the service keeps inferring pages for nobody.

**Two paths, with a page count deciding which a caller gets.** An earlier draft of this decision did exactly that.
Two paths mean two sets of bounds, two ceilings, two queue rules and two refusal vocabularies that have to be kept in
agreement forever, distinguished only by a threshold nobody can defend. The speedup makes the threshold movable,
which makes it worse rather than better: the honest place to draw it is wherever the slowest real page happens to sit
this month.

**Stream the result page by page.** Holds the connection for the whole reading and loses everything on a disconnect,
changes the response shape so it is a new endpoint under ADR-003 anyway, has no MCP equivalent, and contradicts the
existing requirement that an expired request returns nothing partial.

**Split the document caller-side.** What the agent already does. It pushes ordering and reassembly onto every caller,
does nothing for a raw image, and does nothing for an MCP client holding one PDF.

**Deliver by callback.** Requires this service to make an outbound request to a caller-supplied URL, which is exactly
the capability its SSRF guard exists to deny, and brings retries, delivery failure states and a shared secret with it.

**A blocking MCP tool that polls internally.** Attractive because a model has no sleep primitive, so anything that
asks it to wait costs turns. Rejected: it is the removed synchronous path wearing a tool's name, and the ceiling it
hides behind is the client's own request timeout, 300 s in `spring.ai.mcp.client.request-timeout`. A hundred page
document needs about a thousand seconds, so the client gives up and the model is left holding an error and no handle
while the work continues. It would also make the two surfaces disagree about what a submission returns.

**A cooperative cancel signal instead of replacing the worker.** It mirrors the deadline and costs up to one page of
continued inference rather than a 5 to 15 s warm-up. Rejected because it needs a new cross-process signal that has to
survive a pool rebuild and be cleared correctly between jobs, where replacement needs no new machinery at all. On
stopping time the two are level, and replacement wins on machinery.

**An idempotency key on submission.** The `/api-design` skill asks for one on a non-idempotent POST. What keeps
duplicates out here is a rule rather than a store: the agent retries a submission only on a definitive 503
`QUEUE_FULL`, never on a timeout or a connection error, because a lost response may be hiding an accepted job. A retry
that only ever follows a definitive refusal cannot duplicate anything, and the queue bound is the backstop for callers
that do not follow the rule. One observation of a caller submitting the same document twice changes this.
