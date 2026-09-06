## Context

See [proposal.md](proposal.md) for the motivation and the measurements. The constraints below were each verified
against the repository or the module's own `.venv`, never assumed.

- One inference worker. `_WORKER_POOL_SIZE = 1` in
  [ocr_service.py](../../../PaddleOCR/src/service/ocr_service.py), a `ProcessPoolExecutor` on a `spawn` context.
  The docstring gives the reason: PaddleOCR's CPU inference holds the GIL continuously, so running it in the API
  process would freeze the event loop.
- The timeout is `asyncio.wait_for(loop.run_in_executor(...), timeout=settings.OCR_REQUEST_TIMEOUT)` in both
  [rest_endpoints.py](../../../PaddleOCR/src/api/rest/rest_endpoints.py) and
  [mcp_server.py](../../../PaddleOCR/src/api/mcp/mcp_server.py). It cancels the awaiting coroutine and nothing else.
- The library offers a page-by-page seam. `PaddleOCR.predict()` in
  `paddleocr/_pipelines/ocr.py` is `list(self.predict_iter(...))`, and `predict_iter` is public and returns the
  paddlex generator, which yields one result per page. Consuming that generator instead of the list is what makes a
  per-page deadline possible without taking over rasterization.
- PDF pages are rendered at a fixed scale. `PDF_RENDER_SCALE = get_flag_from_env_var("PADDLE_PDX_PDF_RENDER_SCALE",
  2.0, float)` in `paddlex/utils/flags.py`, passed as `PDFReader(zoom=PDF_RENDER_SCALE, ...)` in
  `paddlex/inference/common/batch_sampler/image_batch_sampler.py`. A scale of 2.0 on PDF points is 144 dpi. The
  only other bound on that path is `DEFAULT_MAX_IMAGE_PIXELS = 178_956_970`, which no real page approaches.
- Raw images bypass rasterization entirely. The same sampler appends the image path straight to the batch. The only
  thing between an image and the detector is the detection resize, configured `limit_side_len: 64`,
  `limit_type: min`, `max_side_limit: 4000` in `paddlex/configs/pipelines/OCR.yaml`. With `limit_type: min` that
  resize only ever upscales an image whose shorter side is below 64 px, so for every real image the ratio is 1.0
  until the 4000 px long side clamp fires.
- Pillow's own bomb guard is weaker than it looks. `MAX_IMAGE_PIXELS` defaults to 89,478,485, and
  `_decompression_bomb_check` only raises above twice that, warning in between. It cannot be the guard on its own.
- The error model is fixed: `OCR_FAILED` 422, `FILE_TOO_LARGE` 400, `UNSUPPORTED_FILE_TYPE` 400, `UNSAFE_URI` 400,
  `DOWNLOAD_FAILED` 502, `INTERNAL_ERROR` 500 (`src/api/exception_handlers.py`, ADR-002).
- The liveness and readiness split is already decided in ADR-004: `/health` is liveness and carries the Docker
  healthcheck, `/ready` answers 200 in both states with the condition in the body.
- Container limits are 12 GiB and 4.0 CPUs (`docker-compose.yaml`), and `apply_cpu_thread_limit()` already caps the
  intra-op thread pool to the CPU limit, so one inference already saturates the cores.
- The test gate is `--cov-fail-under=100` with `--cov-branch`.

## Goals / Non-Goals

Goals:

- A budget that a healthy document can meet, and that a pathological one cannot exceed.
- A stop that stops. Bounded, stated, and measured in pages rather than in hope.
- A queue whose waiting requests cannot become orphaned work.
- One statement, in one place, of the concurrency the memory ceiling depends on.
- A readiness answer that is false exactly when the service cannot take work, and true when it is merely busy.
- A refusal that happens before allocation, using the error model that already exists.
- Every number derived, and every number that depends on the running memory investigation marked provisional
  against the task that confirms it.

Non-Goals:

- Making OCR faster. Nothing here changes what inference costs. It changes what happens when that cost exceeds the
  budget.
- Deciding the memory fix. The investigation is a task with a decision rule, and the rule's inputs are being
  measured now.
- Changing the model pipeline. All five models stay, by the owner's decision.
- Asynchronous job submission. A caller still holds the connection for the duration. If the measured per-page cost
  makes that untenable for large documents, that is a separate change and this one surfaces the evidence for it.
- Reading a page at higher quality than the library's fixed rendering resolution. Decision 10 records why, and
  building a knob for it is explicitly out of scope.
- Raising the worker count. Decision 5 makes the cap explicit rather than removing it.

## The numbers, and where each comes from

Every default below is derived. The provisional ones rest on the memory and timing investigation and must not be
frozen before the task named in the last column reports.

| Value | Default | Where it comes from | Provisional? |
|---|---|---|---|
| Worker count | 1 | Today's `_WORKER_POOL_SIZE`, unchanged. Raising it multiplies peak memory by the count. | No |
| Per-page allowance | 120 s | The one live observation: a twenty page document had consumed more than 2100 s of worker time without finishing, so the average page on that document cost at least 105 s. 120 s is the first round value above the observed floor. | Yes, task 1.2 |
| Absolute request ceiling | 300 s, unchanged for now | Today's deployed `OCR_REQUEST_TIMEOUT` in `docker-compose.yaml`. Kept until measured, because changing it is a product decision about how long a caller holds a connection. | Yes, task 1.3 |
| Dispatch margin | 5 s | The worker must give up before the parent does. Covers pickling the arguments, the spawn-context handoff, and the result trip back. | Yes, task 1.2 |
| Maximum pages | derived, not configured | `floor(ceiling / per-page allowance)`. At the provisional values that is 2, which is a finding for the owner rather than a shipped answer. See Decision 8. | Follows its two inputs |
| Reclamation grace | derived, not configured | `per-page allowance + dispatch margin`. The latest a healthy worker can legitimately return is one page's inference after its own budget expired, plus the trip back. | Follows its two inputs |
| Pixel ceiling for one inference | 2,500,000 | The largest standard page the service exists to read, rendered at the library's fixed 144 dpi: US Legal is 1224x2016, 2.47 MP. A4 is 2.00 MP and US Letter 1.94 MP, both comfortably inside. It sits at 57% of the 4.35 MP raw image that was actually OOM-killed, which is the only negative evidence there is. | Yes, tasks 1.1 and 1.4 |

Two numbers deliberately are not configuration. The maximum page count and the reclamation grace are computed from
the two time settings, so they cannot drift out of agreement with them. An operator tunes them by tuning the times.

## Decisions

### Decision 1: a per-page allowance under an absolute ceiling, not one number for both

The present budget is one number covering an entire document, which fails a healthy twenty page job for being
twenty pages long. A per-page deadline is the obvious replacement and, on its own, it is worse: it lets a thousand
page document run for a thousand allowances, which is days.

So both, and the effective budget for a request is `min(pages x per_page_allowance, absolute_ceiling)`. The per-page
allowance is what makes a long healthy document legal. The ceiling is what makes an absurd one illegal. Neither
alone does both jobs.

The page count is not known at the request boundary for a raw image, which is always one page, nor is it worth
guessing for a document. It is read from the document header by the same inspection that enforces the pixel
ceiling and the page count limit (Decision 7), so it costs nothing extra.

Alternative considered: per-page only, with no ceiling. Rejected above.

Alternative considered: ceiling only, raised to a large value such as an hour. Rejected. It admits the thousand
page document, and it makes every failure mode take an hour to appear.

### Decision 2: the worker enforces its own deadline, page by page, from a duration

`asyncio.wait_for` cannot stop a `ProcessPoolExecutor` task. Nothing outside the worker process can, short of
killing it. So the stop has to be cooperative, and cooperative means the worker holds the deadline and checks it.

Three properties of that, each load-bearing:

- The parent passes a remaining duration, not a wall clock deadline. `time.monotonic()` is per-process and its zero
  point is arbitrary, so a timestamp taken in the API process means nothing in the worker. The worker reads its own
  `time.monotonic()` on entry and adds the duration it was given.
- The worker's budget is the request's effective budget minus the dispatch margin, so the worker gives up slightly
  before the parent rather than slightly after. That is the safe direction: the parent then sees a clean failure
  from a live worker instead of a cancellation against a worker it has to reason about.
- The check happens between pages, which is the only seam the library offers. `predict()` is
  `list(predict_iter(...))`, so switching to `predict_iter` and consuming it page by page costs nothing and gives a
  check point per page. The honest consequence is that the granularity of the stop is one page: a worker that
  blows its budget in the middle of a page keeps going until that page finishes. Decision 3 covers the case where
  that overrun is unbounded.

Alternative considered: a watchdog thread inside the worker that raises into the inference thread. Rejected. The
inference call is native code holding the GIL, so an asynchronous exception is not delivered until it returns,
which is the same page boundary with more machinery.

Alternative considered: `signal.alarm` inside the worker. Rejected for the same reason on the same grounds, plus it
does not exist on Windows, where the module's tests run.

### Decision 3: a worker that will not return is replaced, and the queue design makes that cheap

Once the parent's budget has fired, the worker has at most one page's inference plus the trip back before it should
be finished. Past the reclamation grace it is not coming back, and it is holding the only worker.

The parent then discards the pool and builds a new one. The cost is the engine warm-up, five to fifteen seconds by
ADR-004's measurement. What it explicitly does not cost is other people's queued work, and that is a consequence of
Decision 4: because requests wait on an admission gate in the API process rather than inside the pool's own queue,
the pool queue is always empty, so there is never anything in it to lose. The two decisions hold each other up.

Readiness reports not-ready for the duration of the replacement, which is the honest answer and is the one case
`/ready` exists for.

Alternative considered: restart the container on a stuck worker, by making `/health` reflect worker state. Rejected.
It is a strictly larger hammer for the same nail: it throws away the warm engine, every queued request and the HTTP
listener, to fix something a worker replacement fixes on its own. It also contradicts ADR-004, whose `/health`
means "the process is wedged so badly it cannot respond", which is not true here.

Alternative considered: terminate the individual child process and let `ProcessPoolExecutor` heal itself. Rejected.
Reaching into the executor's private process list to do that couples this service to a CPython implementation
detail, and with a pool of one there is nothing to save by being surgical.

### Decision 4: requests queue on an explicit gate in the API process, holding their own deadlines

Today a request is submitted to the pool immediately and waits in the pool's queue, invisible, while its
`asyncio.wait_for` counts down. When it finally reaches the worker, the worker has no idea how much of the budget
was spent queuing, so it starts a job whose caller may already have given up. That is the mechanism by which one
abandoned job poisons everything behind it.

Instead, requests wait on an admission gate in the API process, with as many permits as there are workers. Three
things follow, and each of them is a defect fixed:

- A request that runs out of budget while waiting fails at the gate and is never dispatched. No inference is ever
  started for a caller who has already been told the request failed.
- A request that is admitted after waiting is dispatched with the budget it has left, computed at the moment of
  dispatch, not with a fresh one. The duration the worker receives is therefore truthful.
- The pool's own queue is always empty, which is what makes replacing a worker cheap (Decision 3).

Queue depth is exposed as a metric and in the readiness body, because "how many are waiting" is the number an
operator needs to tell a busy service from a stuck one.

Alternative considered: bounding the queue by count and refusing beyond it. Rejected as unnecessary machinery. The
queue is already bounded by time, since every waiter fails at its own deadline, and a count bound would need a
response for the overflow case, which means either a new error code or overloading the rate limiter's 429. Time is
the honest bound here, and it needs nothing new.

### Decision 5: the worker count is one setting, and it governs both the pool and the gate

The safety of everything above rests on there being one job in flight. That fact currently lives in a private
module constant with a comment, which is not where a load-bearing constraint belongs.

It becomes a setting with a derived meaning: the pool size and the gate's permit count are both read from it, so
they cannot disagree, and a test asserts they agree. The memory ceiling in the documentation is stated as one job's
peak multiplied by that value, so raising it is visibly a memory decision rather than a throughput tweak.

The owner's position is recorded rather than reinterpreted: "we can always limit max worker to 1 so we will have
fixed size at all times only reading will took longer which is not a problem". Whether that fixed size is genuinely
fixed is the question task 1.1 answers, and Decision 9 sets out what happens in each case.

### Decision 6: readiness gains a second condition, liveness gains nothing

ADR-004 already separates the two questions and this design does not redefine either. It adds the condition ADR-004
did not need at the time, because the service could not previously be stuck.

`/health` stays exactly as it is: the API process answers, therefore it is alive. It never consults the worker.
Making it fail on a stuck worker would restart the container, and Decision 3 explains why that is the wrong
response.

`/ready` reports ready only when the engine is warm and the service is accepting work. It is not accepting work
when the engine never warmed, when the pool is unusable, when a replacement is in progress, or when the in-flight
job is past its budget and has not been reclaimed yet.

Being busy is not the same as being unable, and readiness must not confuse them. A service that flipped to
not-ready for the duration of every ordinary job would be pulled out of rotation on every request, which is absurd
for a service whose normal state is one long job at a time. So a healthy in-budget job leaves readiness ready, and
the body carries `accepting_work` and `queue_depth` so an operator can see the difference without inferring it.

The endpoint keeps answering 200 in both states, with the condition in the body, because that is ADR-004's contract
and consumers already read `status`. The general convention of answering 503 when not ready was considered and
rejected here on that ground alone: it would be a breaking change to an existing contract, made in passing, in a
change about something else.

### Decision 7: the pixel ceiling is checked on the header, at the boundary, and refuses with `FILE_TOO_LARGE`

Where. At the request boundary in the API process, beside the existing `sniff_mime` call, which already has the
bytes in hand on both surfaces. Refusing there means the worker is never occupied by a request that was never going
to work, which is the entire point of refusing rather than crashing.

When. Before decode. The inspection opens the header only and reads the declared dimensions. A 40 KB PNG can
declare 100 megapixels, so bytes are not a proxy and the existing 50 MB check does not help. Pillow's own bomb
guard is set as defence in depth, but it cannot be the guard on its own: it warns above `MAX_IMAGE_PIXELS` and only
raises above twice that, so the service enforces its own ceiling explicitly on the size it read and sets Pillow's
constant to the same number as a backstop.

What is measured. The pixels one inference will receive. For a raw image that is its decoded dimensions. For a
document it is the page box rendered at the library's fixed 144 dpi, which is computable from the same header read
that yields the page count, so both limits come from one inspection. Measuring the inference input rather than the
file makes one number cover both input types, which is what makes it possible to reason about at all.

Which error. `FILE_TOO_LARGE` and its 400, the code the service already has for oversized input, with a detail
naming the measured pixel count and the ceiling. No new code, per the brief.

Alternative considered: downscale the image to the ceiling instead of refusing it. It is not absurd, because the
document path already does exactly that at 144 dpi and Decision 10 accepts it there. Rejected here because the
brief asks for a ceiling, because a resize path on the image surface is a behaviour change that deserves its own
decision rather than arriving inside a change about timeouts, and because refusing is the reversible choice: a
caller who is refused can resize and retry, whereas a caller whose page was silently shrunk cannot tell it happened.
It is the natural follow-up if task 1.1 finds the ceiling has to stay low.

Alternative considered: put the check in the worker. Rejected. It would occupy the only worker in order to say no.

### Decision 8: a document that provably cannot finish is refused before it starts

`floor(ceiling / per-page allowance)` is the largest page count that can finish inside the service's own budget.
Beyond it, accepting the job means holding the only worker for the entire ceiling and then telling the caller it
failed, which is the exact behaviour this change exists to remove. So it is refused at the boundary, with the same
`FILE_TOO_LARGE` code and a detail naming the page count and the limit.

At the provisional numbers the limit is `floor(300 / 120) = 2` pages, and that is worth stating plainly rather than
shipping quietly. It means the service as currently configured cannot read a three page document, which was already
true and simply invisible: it would have accepted the job, held the worker, and failed. The change makes it say so
in milliseconds instead of five minutes, and it makes the underlying trade legible, which is that the deployed
ceiling and the per-page cost together decide how large a document this service accepts.

Task 1.3 sets the deployed pair, and it is an owner decision because it trades document size against how long a
caller holds a connection.

### Decision 9: the memory ceiling is a question with a decision rule, not a fix

What is known: a small image costs about 3 GiB, a twenty page document climbs to about 10 GiB over six minutes and
then plateaus, the limit is 12 GiB, and one 4.35 MP raw image was OOM-killed. What is not known is why a call costs
ten gigabytes. The plateau is consistent with the allocator retaining arenas it has finished with rather than with
genuine demand, and that is a hypothesis, not a finding.

A separate investigation is running and will produce the curve. This change carries the question as a task with the
decision written in advance, so the result slots in rather than reopening the design:

- If peak resident memory is flat across page count, the ceiling is one job's cost, the single worker cap
  (Decision 5) is the whole safety story, and the outcome is to record the measured ceiling in the documentation
  and close the question.
- If it rises with page count, the ceiling is not fixed and the fix is chosen then. The lever this change already
  builds is worker replacement (Decision 3): recycling the worker every N pages would bound the growth without any
  new mechanism, at the cost of one warm-up per recycle. It is named here as the obvious candidate, not as the
  decision.
- Either way the pixel ceiling default (Decision 7) is set from the measured curve rather than from the bracket
  between the one page size known to survive and the one known to die.

Two things are ruled out in advance. Cutting models is not a candidate: all five stay, by the owner's decision that
correctness beats memory on a service that reads documents. Raising the container limit is not a candidate either,
because it moves the cliff without bounding anything.

### Decision 10: the fixed 144 dpi rendering resolution is accepted, recorded, and not exposed

This is the decision the proposal asks to have written down, and it is the reason documents are survivable at all.
It lands as an ADR under `PaddleOCR/docs/architecture/decisions/` in the format of the existing four, written in
task 8.4. The content is settled here.

The constraint. PaddleOCR rasterizes every PDF page at `PDF_RENDER_SCALE = 2.0`, which is 144 dpi, and neither the
service nor the caller has any say in it. A page's cost therefore depends on its physical size and not at all on
the resolution it was scanned at, which is why a 300 dpi and a 600 dpi scan of the same page cost the same to read.

What it buys. A hard, predictable memory bound per page for every document, with no work by this service. A4 is
2.00 MP, US Letter 1.94 MP, US Legal 2.47 MP, whatever the caller sends.

What it costs, named rather than buried. A dense scan cannot be read at higher quality even when the caller knows
it needs to be, and there is no way to ask. A rule of thumb is that a line needs roughly 20 px of height to be
recognised dependably, which at 144 dpi puts the smallest reliable type at about 10 pt. Body text sits right at
that edge, so small print and dense tables are where this constraint will be felt. Large format pages are also
affected the other way: an A0 poster at 144 dpi is 32 MP, far above the pixel ceiling, so it is refused rather than
downscaled.

Rejected: raising `PADDLE_PDX_PDF_RENDER_SCALE`. Cost grows with the square of the scale, so 300 dpi is a little
over four times the pixels and therefore roughly four times the memory of a path whose memory is already the live
problem. Revisit when Decision 9's measurement is in, not before.

Rejected: exposing the scale as a per-request parameter. It hands a caller a lever that multiplies the memory cost
of a shared single worker, which is the failure mode this whole change exists to close. It is also a future need
rather than a current one, and the brief says not to build it.

Rejected: rasterizing in this service instead of letting the library do it. It takes on ownership of rasterization
across every library upgrade in exchange for a knob nobody has asked for yet.

## Risks / Trade-offs

The stop is only as fine-grained as one page. A worker that overruns badly inside a single page keeps computing
until that page finishes. Mitigation: the reclamation grace bounds the total exposure and replaces the worker past
it, and the exposure is one page rather than the thirty minutes and counting that was measured.

Worker replacement costs a warm-up, five to fifteen seconds, during which the service is honestly not ready.
Mitigation: it only happens after a job has already failed and refused to stop, the empty pool queue means nothing
else is lost, and readiness says so rather than accepting work it cannot serve.

The page count limit at the provisional numbers is two pages, which is a visible restriction on what the service
accepts. Mitigation: it is provisional, it is derived rather than chosen, task 1.3 sets the deployed pair, and the
alternative is accepting jobs that cannot finish. This is disclosure of an existing limit, not a new one.

The pixel ceiling refuses ordinary phone photographs at its provisional value, since a 12 MP photo is far above
2.5 MP. Mitigation: it is provisional against task 1.1, the refusal is deterministic and names the numbers, and
Decision 7 records downscaling as the follow-up if the measured curve does not let the ceiling rise. The status quo
is an OOM kill that takes the worker with it, so a refusal is strictly better even at a low value.

The header inspection parses untrusted input in the API process. Mitigation: it is a header read only, no pixel
buffer is allocated, the existing 50 MB byte cap still bounds the input, and Pillow's bomb guard is set to the
service's own ceiling as a backstop. The `/security-review` skill is listed for the implementation of exactly this
part.

`pypdfium2` becomes a declared dependency of this module. Mitigation: it is already installed as a paddlex
dependency, so there is no new install and no version conflict, and declaring it is the correct response to relying
on it rather than a cost.

The memory ceiling is still unexplained when this change ships. Mitigation: nothing in this design depends on
knowing the answer, the single worker cap holds the peak at one job's cost whatever that cost is, and the question
is carried as a task with its decision rule already written.

## Migration Plan

A normal image rebuild. No schema migration, no persisted state, no data migration. The readiness body gains two
fields and every other response is untouched, so consumers that ignore unknown fields are unaffected.

Configuration is the one ordered part. The new settings all have defaults, so the image starts without any compose
change, but `OCR_REQUEST_TIMEOUT=300` and the per-page allowance together decide the page limit, so ship the
compose value task 1.3 derives in the same deploy as the image. Deploying the image alone is safe and simply keeps
today's ceiling.

Rollback is reverting the image. Nothing persists, and no caller has to change anything to go back, because no
request parameter was added.

## Open Questions

1. What is the p95 per-page inference time on the deployment's 4.0 CPU allocation, and what should the deployed
   ceiling therefore be? Task 1.2 measures it and task 1.3 turns it into the deployed pair with the owner. It
   changes three defaults and no behaviour, so it is deferrable in the sense that the mechanism is correct whatever
   the numbers are, but the pair must be decided before the change is called done.
2. Does peak memory rise with page count or plateau? Decision 9 states the rule for both answers. The separate
   investigation running now produces it. It changes the pixel ceiling default and possibly adds a worker recycling
   policy, neither of which alters the specs.
3. If the measured per-page cost makes documents of a realistic size take longer than a caller can hold a
   connection, the answer is asynchronous job submission, which is a separate change. This one produces the
   evidence that would justify it, and deliberately does not pre-empt it.
