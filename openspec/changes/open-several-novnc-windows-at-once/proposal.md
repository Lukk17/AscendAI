## Why

The human-intervention flow can serve exactly one site at a time, and the cost of that showed up in a real test run
three days after it shipped.

On 2026-09-07, commit `02bacdb` added `_NoVNCFlowLock` to
[novnc_strategy.py](../../../apps/ascend-web-hunter/src/reader/strategies/novnc_strategy.py). It closed a real defect,
registered as F22 in [DEFECT_REGISTER.md](../../../docs/DEFECT_REGISTER.md): two concurrent flows shared one Chromium
process, one Xvfb display and one fixed CDP port (`--remote-debugging-port=9222`), collided on that port, and one
launch timed out. The session the human had already captured was lost in silence. The lock made that impossible by
allowing one flow at a time, and a second caller now receives HTTP 409 with `status: novnc_busy` and a `Retry-After`
header from
[exception_handlers.py](../../../apps/ascend-web-hunter/src/api/exception_handlers.py).

On 2026-09-10, the run record
[2026-09-10T11-30-00_7-authenticated-realworld-scraping-tasks.md](../../../apps/ascend-web-hunter/e2e/testing/runs/2026-09-10T11-30-00_7-authenticated-realworld-scraping-tasks.md)
shows four rows of the Part 1 matrix in
[7-authenticated-realworld-scraping-test.md](../../../apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md)
answering 409: `nowsecure.nl` (row n), `indeed.com/jobs` (row o), `g2.com` (row p) and `secure.indeed.com/auth`
(row t). None of them failed for a reason of its own. Each failed because Part 3's reCAPTCHA window was still open
while a human worked on it, and the spec's accept-set for a best-effort row is `{success, intervention}`, so a 409 is
not a terminal verdict at all. One human working on one site made four unrelated sites untestable.

This was predicted. ADR-003's own risk section, written on 2026-05-31, says: "No cap on concurrent tasks exists
today." The lock answered that by setting the cap to one. One is the wrong number. The right answer is a cap that is
configurable, several windows visible at once on the display the service already runs, and none of the sharing that
made two flows collide in the first place.

The display already supports it. `supervisord.conf` runs Xvfb on `:99` at 1920x1080 with fluxbox as a window manager,
so several browser windows can be open, placed, raised and closed independently by a human over the one NoVNC
connection. Nothing about the display forces one window. What forced one window was one browser process, one fixed
CDP port and one global lock, and all three of those are ours to change.

## What Changes

One flow, one of everything it needs:

- Each waiting site gets its own Chromium process, its own browser context, its own page and its own monitor task.
  Nothing is shared between two flows except the X display they draw on and the Redis the session store lives in,
  and both of those already handle concurrent users.
- No launch uses a fixed CDP port. The fixed `--remote-debugging-port=9222` is replaced with
  `--remote-debugging-port=0`, so the operating system assigns a free ephemeral port per launch and two launches can
  never contend for one. `--remote-debugging-address=127.0.0.1` is added at the same time, which also closes the
  sibling-container exposure ADR-003 records as accepted.
- Each flow writes only its own session key. The key scheme is unchanged: registrable domain plus profile, exactly as
  [cookie_manager.py](../../../apps/ascend-web-hunter/src/reader/cloudflare/cookie_manager.py) computes it today. The
  flow key is that same pair, which is what guarantees no two live flows can write the same record.
- Each flow's window is placed at its own deterministic position on the shared display, cascaded so every open
  window's title bar stays visible and clickable under fluxbox. The human raises and clears them in any order, and
  the order they are cleared in has no effect on any other flow.

A cap that is a number rather than an accident:

- `NOVNC_MAX_CONCURRENT_FLOWS` replaces the global lock, defaulting to 4. A request that arrives when every slot is
  taken still gets HTTP 409 with `status: novnc_busy` and `Retry-After`, and that is the only case that produces a
  409. The response now says how many flows are live, what the maximum is, and what each live flow is working on.
- A second request for a site and profile that already has a live window joins that window instead of opening a
  second one or being refused. It receives the same `vnc_url` and the same flow identifier, and the capture the human
  produces satisfies both callers, because both were waiting on the same session record. This is why a duplicate is
  never a 409: refusing it would spend a 409 on a case the service can serve.

Failure that stays inside one flow:

- A monitor that raises, times out, is cancelled or loses its browser closes its own browser, frees its own slot,
  records its own outcome, and touches nothing else. It cannot cancel a sibling, close a sibling's browser, or
  overwrite a sibling's session record.
- A capture already written stays written. A flow's teardown never clears the session store.
- The lease-based self-healing is kept and made stronger. Each flow carries its own lease of
  `NOVNC_TIMEOUT_SECONDS + NOVNC_FLOW_LEASE_GRACE_SECONDS` from its own start. An expired lease now cancels that
  flow's monitor, which closes its browser and removes its window from the display, rather than only marking the slot
  free and leaving a wedged window behind for the human to look at.
- A periodic sweep runs the lease check on a timer rather than only when the next caller arrives, so a dead window
  leaves the display within one sweep interval even when no further request is ever made.
- Shutdown cancels every live monitor and waits, bounded, for each to close its browser. Today they are abandoned.

A contract that lets a caller and a human tell the windows apart:

- The 428 body gains `flow_id`, `joined` and `window` (slot index and pixel rectangle), alongside the existing
  `status`, `intervention_type`, `vnc_url` and `message`. Every existing field keeps its name, its type and its
  meaning, so ADR-003's field-shape contract and every agent that reads it are untouched.
- The 409 body keeps `status`, `message`, `holder_url` and `holder_profile`, and gains `active_flows`,
  `max_concurrent_flows` and a `flows` array. `holder_url` and `holder_profile` now describe the oldest live flow,
  which is the one whose slot frees next, so the fields stay truthful for a caller that already reads them.
- A new read-only listing, `GET /api/v2/session/interventions` on REST and `session_interventions` on MCP, returns
  the live flows with their windows and remaining lease. This is what turns "clear them in any order" from a hope
  into something a human or an agent can actually do, and it is what lets the e2e suite assert the window count
  deterministically instead of inferring it.

Observability that names the flow:

- Every NoVNC log line carries the flow identifier, the slot and the originating request identifier, so a 428 a
  caller saw, the window the human worked in, and the capture that landed can be tied together after the fact.
- A gauge for live flows, counters for flows started, joined, refused at the cap, and reclaimed by reason.
  `novnc_flow_busy_total` keeps its name and now counts exactly one thing: a request refused because the cap was
  reached.

## Scope

- `apps/ascend-web-hunter/src/reader/novnc/`: a new package holding the flow registry, the flow record and the window
  layout calculation. Pure enough to test to the module's 100 percent branch gate without launching a browser.
- `apps/ascend-web-hunter/src/reader/strategies/novnc_strategy.py`: the global lock is deleted, the strategy reserves
  or joins a flow, and the monitor becomes per-flow.
- `apps/ascend-web-hunter/src/reader/cloudflare/cookie_manager.py`: the registrable-domain calculation is promoted to
  a module-level function so the registry can key on the same value the session store keys on, without a third copy
  of the rule and without two more `# noqa: SLF001` call sites.
- `apps/ascend-web-hunter/src/api/`: the two exception bodies, the new listing endpoint on both surfaces, and the
  exception's own fields.
- `apps/ascend-web-hunter/src/config/config.py`: nine settings, listed with their derivations in
  [design.md](design.md).
- `apps/ascend-web-hunter/src/main.py`: the sweeper task and the shutdown hook in the existing lifespan.
- `apps/ascend-web-hunter/src/observability/metrics.py`: one gauge and three counters.
- `apps/ascend-web-hunter/tests/`: the rewritten concurrency tests and the new registry and layout tests, to the
  module's configured `--cov-fail-under=100` with `--cov-branch`.
- `apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md` and its sidecar template: the four
  rows that answered 409 get a stated expectation, and a new gated Part 4 exercises several windows at once.
- Docs: `AGENTS.md`, `README.md`, `docs/configuration.md`, a new ADR-009, an amendment to ADR-003, and one evidence
  line on F22.

## Out of Scope

- One display per flow. That would need an Xvfb, an x11vnc and a websockify per flow, plus a port per flow through
  Ngrok, to buy isolation the window manager already provides. Rejected in [design.md](design.md).
- Authenticating or tokenising `vnc_url`. ADR-003 records the unauthenticated URL as an accepted posture, and this
  change widens what that posture exposes without changing the posture itself. The widening is stated under Risks and
  belongs in its own change.
- A waiting room, a queue or a retry-after-wait behind the cap. A caller over the cap still gets 409 immediately.
  Making the caller wait would hold a connection open for up to the full intervention timeout for a slot that may
  never free.
- Any change to the session store key scheme, to the TTL model, or to what a capture contains.
- Any change to `/ready`. A full intervention registry is not unreadiness: search and every non-intervention read
  tier still work. Stated as a requirement so nobody adds it later by reflex.
- Automated captcha solving, and the pending anti-bot interstitial fix that rows v, w, x and y of e2e spec 7 already
  depend on. Neither is touched here.

## Risks

- Memory. Four headful Chromium processes plus their Playwright driver processes cost roughly four times what one
  costs, on a host that is also running the headless browser pool, SearXNG and FlareSolverr. Mitigated by making the
  cap a setting whose documentation says it is a memory constraint and not only a display one, and by defaulting it
  to 4 rather than to something ambitious. The number is derived in [design.md](design.md).
- Display crowding. The cascade guarantees every window is fully on screen and that earlier windows stay clickable,
  but it does not guarantee they do not overlap. At a raised cap the human will be clicking through a stack. Stated
  in the display spec as the accepted behaviour rather than left to be discovered.
- A wider unauthenticated surface. With one window, anyone holding the `vnc_url` could see one site. With four, they
  can see four, including any login a human is part way through. This is a real widening of ADR-003's accepted
  posture, it is recorded in ADR-009 rather than buried, and the ADR states plainly that `VNC_PASSWORD` should be set
  on any deployment where the tunnel is reachable by anyone but the operator.
- A joined flow couples two callers. Caller B's outcome now depends on a window that was opened for caller A and on
  whether the human finishes it. This is the deliberate trade that keeps 409 meaning only one thing, and it is safe
  precisely because both callers were already waiting on the same session record. A caller that needs its own window
  can ask for a different profile.
- Reclamation cannot force-kill a Chromium that ignores its close. The cancel path is bounded by
  `NOVNC_FLOW_CANCEL_GRACE_SECONDS`, after which the slot is freed and an orphan is logged and counted rather than
  the registry blocking on it forever. The orphan window may remain on the display. This is the same residual risk
  the lock had, now named, bounded and measured.
- Regression risk against F22 itself. The defect this change reverses the shape of is real and was expensive. Task
  section 9 exists only to prove it stays closed: two concurrent flows produce two distinct launches, no shared port
  argument, distinct window positions, and two captures under two distinct keys.
- Rollback. Setting `NOVNC_MAX_CONCURRENT_FLOWS=1` restores one window at a time without a code change or a redeploy
  of a different image. The only residual difference at a cap of 1 is that a duplicate request joins rather than
  receiving a 409, which is the intended behaviour at every cap.

## Capabilities

### New Capabilities

- `web-search-concurrent-human-intervention`: how many intervention flows may run at once, what each flow owns
  exclusively, when a request joins an existing flow, when it is refused, how a flow's failure is contained, and how
  a flow that dies without releasing is reclaimed.
- `web-search-intervention-display`: how the single NoVNC display is shared between several windows, where each
  window is placed, how a caller and a human identify which window belongs to which site, and what the service
  guarantees about a window still being usable at the configured cap.
- `web-search-intervention-observability`: what the service reports about live flows, over the metrics surface, the
  logs and the intervention listing, so an operator can tell a busy service from a stuck one.

### Modified Capabilities

None. No capability under `openspec/specs/` covers ascend-web-hunter today. The three above stand on their own, and
they deliberately do not restate anything from the unarchived `web-search-authenticated-sessions` delta, which owns
the session store, its keys and its TTLs and is left untouched by this change.

## Impact

API: additive on both surfaces. Three fields are added to the 428 body and three to the 409 body, no existing field
changes name, type or meaning, and one read-only endpoint is added. A caller that ignores every new field behaves
exactly as it does today. The behaviour a caller sees does change in one way worth naming: with the shipped default
of 4, three requests that would each have received a 409 now each receive a 428 with a window of their own.

Operational: the default cap of 4 raises the service's worst-case memory by roughly three additional headful browsers
against today's one. An operator who cannot afford that sets the cap to 1 and is back to today's footprint with
today's behaviour.

Tests: `apps/ascend-web-hunter` runs `--cov=src --cov-branch --cov-fail-under=100`, so every branch added below needs
a test before the suite goes green. `tests/reader/strategies/test_novnc_flow_lock.py` is deleted with the lock it
tests, and `test_novnc_concurrency.py` is rewritten against the registry.

Docs: the environment variable tables in `apps/ascend-web-hunter/AGENTS.md`, `README.md` and `docs/configuration.md`,
a new ADR-009 for the concurrency model and its security widening, an amendment to ADR-003 whose single-flow and
fixed-CDP-port paragraphs this change supersedes, and one evidence line on F22 in `docs/DEFECT_REGISTER.md` recording
that its collision cannot recur under the new model. F22 is not reopened.

## Relevant Skills

Load before implementing:

- `/python-patterns`, `/python-testing`, `/tdd-workflow`
- `/api-design` for the two response bodies, the new listing endpoint and the 409 semantics
- `/docker-patterns` for the display, the window manager and the per-flow browser process footprint
- `/security-review` for the CDP port change, the widened unauthenticated VNC surface and the new listing endpoint
- `/e2e-runbooks` for the spec 7 changes and its sidecar tasks template
- `/coding-standards`, `/code-reviewer`
- `/architecture-decision-records` for ADR-009 and the ADR-003 amendment
