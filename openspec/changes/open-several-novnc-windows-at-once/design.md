## Context

The single-flow constraint is enforced by `_NoVNCFlowLock`, a module-level singleton in
`apps/ascend-web-hunter/src/reader/strategies/novnc_strategy.py`. Its docstring gives two reasons for being global
rather than per site: only one physical browser window exists, and a second flow for the same site is not safely
joinable because the human driving the first window does not know a second caller is waiting on it.

The first reason is a property of the implementation, not of the display. `supervisord.conf` runs
`Xvfb :99 -screen 0 1920x1080x24` with `fluxbox` as a window manager and `x11vnc` plus `websockify` in front. A window
manager is exactly the component that makes several windows on one display workable: it draws title bars, it raises a
window on click, and it lets a human close one window without touching another. Nothing above the display layer
forces one browser.

The second reason inverts once each flow is identified. A second caller for the same registrable domain and profile
is waiting on the same session record as the first. Its outcome is the first flow's outcome, so joining is not a
compromise, it is the correct answer.

What genuinely could not be shared was the CDP port. Both launches passed `--remote-debugging-port=9222`, and the
second Chromium could not bind a port the first already held. That is what F22 records, and it is fixed by not using
a fixed port rather than by allowing only one launch.

## Goals

- Several intervention windows visible at once on the one display, one per waiting site and profile.
- A configurable maximum, with 409 reserved for that maximum and for nothing else.
- Complete failure isolation: one flow dying costs one flow and one capture that was never made.
- The lease-based self-healing kept, and extended so reclaiming a slot also removes the dead window.
- The session key scheme unchanged.

## Non-Goals

- More than one display, more than one VNC endpoint, or more than one tunnel.
- Authenticating the VNC URL.
- Any waiting or queueing behind the cap.

## Decisions

### Decision 1: A slot registry replaces the global lock

`src/reader/novnc/flow_registry.py` holds `NoVNCFlowRegistry`, a single module-level instance, and `NoVNCFlow`, the
record of one live flow.

A `NoVNCFlow` carries: `flow_id` (12 hex characters from `uuid4`), `key` (registrable domain and profile),
`url`, `profile`, `intervention_type`, `slot`, `window`, `vnc_url`, `started_at` (from `time.monotonic()`),
`request_id` (from the existing `RequestIdMiddleware` context) and `task` (the monitor, attached immediately after
creation).

The registry's surface:

- `find(key)` returns a live flow for that key after sweeping expired leases, or `None`.
- `reserve(key, url, profile, intervention_type)` takes the lowest free slot and returns a flow, or raises
  `NoVNCFlowBusyException` when every slot is taken.
- `attach_task(flow_id, task)` binds the monitor to the record.
- `release(flow_id)` frees the slot. It is idempotent and it ignores an unknown identifier, so a monitor's `finally`
  can call it unconditionally.
- `active()` returns the live flows, ordered by `started_at`.
- `sweep()` cancels every flow whose lease has expired and returns them.
- `shutdown()` cancels every live flow and waits, bounded, for each teardown.

Every mutating method is synchronous and contains no `await`. That is the whole concurrency argument: the registry is
touched only from the event loop thread, and a function with no suspension point inside it cannot interleave with
another, so `reserve` is atomic without a lock. Adding an `asyncio.Lock` here would buy nothing and would introduce a
second thing that can be held across an await.

Between `reserve` and the monitor being created there is one await, the VNC URL resolution, which reaches Ngrok's API
with a 5 second timeout. The slot is already reserved across that await, so the cap holds. If the resolution raises,
the slot is released before the exception propagates. That is the shape the lock already uses and it is kept
deliberately.

Rejected: keeping the lock and raising its capacity to N with a counter. A counter cannot answer which slot a window
belongs to, cannot list live flows, cannot cancel a specific wedged monitor, and cannot key a join. Every one of those
is required here.

### Decision 2: The flow key is the session key

The flow key is the registrable domain plus the profile, which is exactly what `CookieManager` keys its Redis record
on (`session:{domain}:{profile}`). Two consequences follow directly and neither needs enforcement anywhere else:

- Two live flows can never write the same session record, because two live flows can never share a key.
- A second request for a key that already has a live flow is asking for a record another flow is already producing.

Today `_get_domain` is a private static method on `CookieManager`, reached from `session_manager.py` with
`# noqa: SLF001`. It is promoted to a module-level `registrable_domain(url)` in `cookie_manager.py`, with the static
method delegating to it so no existing caller changes behaviour. The registry uses the public function, and the two
existing `# noqa: SLF001` call sites for this one function are cleaned up in the same task. This is DRY on a rule that
would otherwise have a third implementation.

### Decision 3: A duplicate joins, it does not get a 409

When `find(key)` returns a live flow, the caller receives that flow's `vnc_url` and `flow_id`, with `joined: true` in
the 428 body. No second window opens, no second monitor starts, no second browser launches.

The URL may differ from the one the window is showing, when two callers ask for two pages of the same site. The window
stays on the first URL. That is correct rather than merely tolerable: a clearance or a login for a registrable domain
is stored per registrable domain, so solving it on one page of that domain produces the record the other page needs.

This is what keeps 409 meaning one thing. A caller that genuinely wants a separate window for the same site asks for
a different profile, which is a different key, a different slot and a different session record.

Rejected: 409 on a duplicate. It spends the cap's error on a case that can be served, and it would make the 409 body's
meaning ambiguous between "the service is full" and "someone else asked for this site".

### Decision 4: One browser process per flow, and no fixed CDP port

Each flow calls `chromium.launch()` for itself, inside its own `async with async_playwright()`. Nothing is shared.

`--remote-debugging-port=9222` becomes `--remote-debugging-port=0`, which asks the operating system for a free
ephemeral port, so two launches cannot contend. `--remote-debugging-address=127.0.0.1` is added, which binds that port
to loopback inside the container instead of to every interface. ADR-003 records the all-interfaces binding as an
accepted exposure on the grounds that no untrusted sibling container shares the network. Closing it costs one argument
and removes the assumption, so it is closed here rather than re-accepted.

Nothing in the repository connects to port 9222. The only references are the launch argument itself, ADR-003's
security paragraph, and one run record describing the collision. So removing the fixed number breaks no caller.

Profile isolation comes from using a separate `launch()` per flow and from nothing else. Playwright creates a fresh
temporary profile directory per launch and manages its lifetime, and passing an explicit `--user-data-dir` to
`launch()` is not the supported way to control that (`launch_persistent_context` is). No explicit profile directory is
passed, and no scratch-directory sweep is added, because there is no directory of ours to sweep.

Rejected: one shared browser process with a `BrowserContext` per flow. It removes the port question entirely and costs
less memory, and it fails the isolation requirement outright: one crashed browser process takes every window with it,
and a `finally` that closes the browser would close every sibling's window. The requirement is that a flow that dies
must not take the others down, so a shared process is disqualified.

Rejected: one shared Playwright driver with N `launch()` calls against it. This is the middle option and it saves one
node bridge process per flow, roughly 50 to 80 MiB each. It reintroduces a shared-fate component, it couples every
flow's lifetime to a driver that has to be owned and restarted by somebody, and the existing `BrowserPool` already
owns a driver it relaunches on disconnect, which is precisely the kind of coupling that must not reach these windows.
At a cap of 4 the saving is under 320 MiB against total isolation. Isolation wins.

Rejected: reusing `BrowserPool`. It launches with `headless=settings.PLAYWRIGHT_HEADLESS` and relaunches transparently
on disconnect, which would silently destroy every open intervention window whenever the headless tier had a bad
minute.

### Decision 5: The display is shared by placement, not by partition

Each slot maps to a deterministic window rectangle. Size is `NOVNC_WINDOW_WIDTH_PX` by `NOVNC_WINDOW_HEIGHT_PX`,
constant for every slot. Position cascades:

```text
x = (slot * NOVNC_WINDOW_CASCADE_OFFSET_PX) mod (NOVNC_DISPLAY_WIDTH_PX  - NOVNC_WINDOW_WIDTH_PX  + 1)
y = (slot * NOVNC_WINDOW_CASCADE_OFFSET_PX) mod (NOVNC_DISPLAY_HEIGHT_PX - NOVNC_WINDOW_HEIGHT_PX + 1)
```

The modulus is what makes this safe at any cap. However large the cap is set, no window is ever placed partly or
wholly off screen, and the arithmetic is pure, total and trivially testable at every slot from 0 to the cap.

Cascade rather than tile, for one reason: a captcha has to be solvable. At the default cap of 4, a tile is 960 by 540
before browser chrome, which is a cramped surface for a reCAPTCHA image grid. The cascade keeps every window at
1280 by 800 whatever the cap is, and pays for that with overlap that fluxbox lets the human resolve with a click. At a
raised cap the stack gets deeper, and that is stated as accepted behaviour rather than hidden.

Windows are identified to the caller by the `window` object in the 428 body and by the intervention listing, both of
which carry the slot index and the rectangle alongside the target URL. Each window's title is the page's own title,
which fluxbox draws, so a human looking at the display already sees the site name.

Rejected: injecting a fixed banner overlay into each page to label the window. It would label the window
unambiguously, and it modifies the page a human is about to interact with, which is a poor idea on a page whose whole
purpose is an anti-bot challenge that inspects the DOM. The page is left alone.

Rejected: one Xvfb, x11vnc and websockify per flow, with a port and a tunnel each. It gives per-flow display isolation
that the window manager already gives at the window level, and it multiplies the ports, the tunnels and the VNC URLs
the human has to juggle by the cap. The whole point is one display the human already has open.

### Decision 6: The monitor owns one flow and cleans up only after itself

`_monitor_for_cookies` takes a `NoVNCFlow` rather than loose arguments. Its structure is unchanged: launch, navigate,
poll until resolved or until `NOVNC_TIMEOUT_SECONDS` elapses, record an outcome. What changes is the teardown
contract:

- `finally` closes its own browser and calls `registry.release(flow.flow_id)`, both wrapped so a failure in one
  cannot skip the other.
- `asyncio.CancelledError` is caught explicitly, records the outcome `cancelled`, closes the browser, releases the
  slot, and re-raises. Without the explicit catch, reclamation and shutdown would leave the browser running.
- The monitor never calls anything that could reach another flow's browser, task or session key.
- The monitor never clears a session record. It only writes, and only under its own key. A capture already persisted
  survives any subsequent failure of the flow that made it.

The strong-reference set `_active_monitor_tasks` is no longer needed as a separate structure: the registry holds the
task on the flow record, which is the strong reference, and the record is only dropped on release.

### Decision 7: The lease is per flow, it cancels, and it is swept on a timer

Each flow's lease is `NOVNC_TIMEOUT_SECONDS + NOVNC_FLOW_LEASE_GRACE_SECONDS`, measured from that flow's own
`started_at`. The grace covers the gap between the monitor's own timeout firing and its `finally` actually completing,
which is what the original constant's comment says and it remains true per flow.

Two changes to how expiry is handled:

- Expiry cancels the monitor rather than only freeing the slot. The cancellation runs the monitor's teardown, which
  closes the browser and removes the window. The old lock freed the slot and left the wedged browser running, which
  with one window was invisible and with four would fill the display with dead windows.
- The sweep runs on a timer, `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS`, from a task started in the existing lifespan, as
  well as lazily at the top of `find` and `reserve`. A lazy-only sweep leaves a dead window on the display
  indefinitely when no further request arrives, which is exactly the situation after a burst.

A cancelled monitor that does not finish within `NOVNC_FLOW_CANCEL_GRACE_SECONDS` has its slot freed anyway, its
record dropped, and an orphan logged and counted. The registry never blocks on a process that will not die.

### Decision 8: Shutdown drains

The lifespan's `finally` calls `registry.shutdown()` before the browser pool is stopped. It cancels every live monitor
and waits up to `NOVNC_FLOW_CANCEL_GRACE_SECONDS` in total for the teardowns. Today monitors are simply abandoned at
shutdown, which leaks Chromium processes on every restart while an intervention is open.

### Decision 9: The contract grows, and nothing in it moves

The 428 body keeps `status`, `intervention_type`, `vnc_url` and `message` exactly as ADR-003 specifies, because the
MCP tool docstring names `vnc_url` and `intervention_type` and every downstream agent reads them. It gains:

```json
{
  "status": "human_intervention_required",
  "intervention_type": "captcha",
  "vnc_url": "https://abc123.ngrok.io/vnc.html?autoconnect=true",
  "message": "Manual Captcha resolution required. Please visit: ...",
  "flow_id": "9f2c41ab77de",
  "joined": false,
  "window": { "slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800 }
}
```

The 409 body keeps `status`, `message`, `holder_url` and `holder_profile`. `holder_url` and `holder_profile` now
describe the oldest live flow, which is the one whose slot frees next, so a caller that already reads them still gets
a true and useful answer. It gains:

```json
{
  "status": "novnc_busy",
  "message": "All 4 intervention windows are in use. ...",
  "holder_url": "https://nowsecure.nl",
  "holder_profile": "default",
  "active_flows": 4,
  "max_concurrent_flows": 4,
  "flows": [
    { "flow_id": "9f2c41ab77de", "url": "https://nowsecure.nl", "profile": "default", "expires_in_seconds": 412.7 }
  ]
}
```

`Retry-After` stays a short fixed poll interval rather than the remaining lease. A human can free a slot at any
instant, so the remaining lease is an upper bound of up to ten minutes and telling a caller to wait that long would be
accurate and useless. The value is promoted from a module constant to `NOVNC_BUSY_RETRY_AFTER_SECONDS` with its
existing default of 30.

The 409 body is deliberately not RFC 7807, for the same reason the 428 is not: both are established
`status`-keyed shapes that agents already parse by name, and `exception_handlers.py` documents that choice at the
handler. The RFC 7807 handlers in that file are untouched.

`GET /api/v2/session/interventions` returns:

```json
{
  "active": 2,
  "max_concurrent": 4,
  "flows": [
    {
      "flow_id": "9f2c41ab77de",
      "url": "https://nowsecure.nl",
      "domain": "nowsecure.nl",
      "profile": "default",
      "intervention_type": "captcha",
      "slot": 0,
      "window": { "x": 0, "y": 0, "width": 1280, "height": 800 },
      "age_seconds": 12.4,
      "expires_in_seconds": 617.6,
      "vnc_url": "https://abc123.ngrok.io/vnc.html?autoconnect=true"
    }
  ]
}
```

It is a GET because it takes no input, unlike the other session operations which POST a URL in a body. It is not
paginated and does not need to be: the collection is bounded by `NOVNC_MAX_CONCURRENT_FLOWS`, which is stated in the
response itself. It returns no cookies, no storage state and no page content. It does return the `vnc_url`, which the
428 body already returns unauthenticated on the same service, so the disclosure is not new, and it is recorded in
ADR-009 alongside the rest of the posture.

### Decision 10: Readiness does not change

A full registry means interventions are capped, not that the service is unwell. Search works, every non-intervention
read tier works, and the correct answer to a caller over the cap is the 409 it already receives. Adding the registry
to `/ready` would take the whole service out of rotation because four humans are busy. This is written into the
observability spec as a requirement so it is not added later by reflex.

## Configuration

| Setting | Default | Derivation |
| :-- | :-- | :-- |
| `NOVNC_MAX_CONCURRENT_FLOWS` | `4` | Four is what the 2026-09-10 run needed (rows n, o, p and t all queued behind one human). Four 1280x800 windows fit the 1920x1080 display under the cascade with every title bar reachable. Four headful Chromium plus four Playwright drivers is the memory the host can carry beside the headless pool, SearXNG and FlareSolverr. The setting is a memory constraint as much as a display one and its documentation says so. |
| `NOVNC_WINDOW_WIDTH_PX` | `1280` | Wide enough for a reCAPTCHA image grid and a full login form without horizontal scrolling. |
| `NOVNC_WINDOW_HEIGHT_PX` | `800` | Leaves 280 px of the 1080 display for the cascade and for browser chrome. |
| `NOVNC_WINDOW_CASCADE_OFFSET_PX` | `48` | Wider than a fluxbox title bar, so every earlier window keeps a clickable strip. |
| `NOVNC_DISPLAY_WIDTH_PX` | `1920` | Matches `Xvfb :99 -screen 0 1920x1080x24` in `supervisord.conf`. |
| `NOVNC_DISPLAY_HEIGHT_PX` | `1080` | Same source. |
| `NOVNC_FLOW_LEASE_GRACE_SECONDS` | `30.0` | Promoted unchanged from `_NOVNC_LOCK_LEASE_GRACE_SECONDS`, whose comment already derives it as teardown time rather than a second timeout window. |
| `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS` | `30.0` | One grace period. A dead window leaves the display within about the time the grace already allows for teardown. |
| `NOVNC_FLOW_CANCEL_GRACE_SECONDS` | `10.0` | Bounds reclamation and shutdown. A browser that has not closed in ten seconds is not going to, and the slot is worth more than the wait. |
| `NOVNC_BUSY_RETRY_AFTER_SECONDS` | `30` | Promoted unchanged from `_NOVNC_BUSY_RETRY_AFTER_SECONDS`, with its existing rationale: a short actionable poll, not the flow's own timeout. |

Two validators run at settings construction, so a bad combination fails at startup and not at the first intervention:
the window must fit the display on both axes, and the cap must be at least 1.

`NOVNC_TIMEOUT_SECONDS` and `NOVNC_COOKIE_SYNC_POLL_SECONDS` keep their names, defaults and meanings, now applied per
flow.

## Observability

| Signal | Type | Labels | Meaning |
| :-- | :-- | :-- | :-- |
| `novnc_active_flows` | Gauge | none | Live intervention flows. Set on every reserve, join is not counted, decremented on every release. |
| `novnc_flows_started_total` | Counter | `intervention_type` | A window was opened. |
| `novnc_flow_joined_total` | Counter | `intervention_type` | A caller joined an existing window instead of opening one. |
| `novnc_flow_busy_total` | Counter | none | Kept. Now counts exactly one thing: refused because the cap was reached. |
| `novnc_flows_reclaimed_total` | Counter | `reason` | `lease_expired`, `shutdown` or `cancel_timeout`. |
| `strategy_attempts_total` | Counter | `strategy`, `outcome`, `domain` | Kept, with `6-novnc-monitor` gaining the outcome `cancelled` beside `resolved`, `timeout` and `rejected`. |
| `human_intervention_total` | Counter | `intervention_type` | Kept, unchanged. |

Every log line from the registry, the strategy and the monitor carries `flow_id` and `slot`, and the reserve line also
carries the originating request identifier from `RequestIdMiddleware`. That is what lets an operator take a 428 a
caller reported, find the window it opened, and find the capture it eventually produced.

## Migration from the global lock

1. `_NoVNCFlowLock`, `_novnc_flow_lock` and `_active_monitor_tasks` are deleted rather than deprecated. All three are
   module-private and their only references outside `novnc_strategy.py` are its own tests.
2. `_NOVNC_LOCK_LEASE_GRACE_SECONDS` and `_NOVNC_BUSY_RETRY_AFTER_SECONDS` become settings with the same values, and
   `_CDP_REMOTE_DEBUGGING_PORT` is deleted with the fixed port.
3. `NoVNCFlowBusyException` keeps its class name and its `holder_url` and `holder_profile` attributes, so
   `main.py`'s handler registration, `mcp_server.py`'s two catch sites and `rest_endpoints.py`'s docstring stay
   valid. It gains `active_flows`, `max_concurrent_flows` and `flows`, and its message is reworded to name the cap.
4. `tests/reader/strategies/test_novnc_flow_lock.py` is deleted with the class it tests.
   `tests/reader/strategies/test_novnc_concurrency.py` is rewritten: its first case becomes "two concurrent flows both
   get their own window", its second becomes "the fifth is refused at the cap", and its lease case is kept and moved
   onto the per-flow lease.
5. Behaviour at `NOVNC_MAX_CONCURRENT_FLOWS=1` is today's behaviour, with one intended difference: a duplicate for the
   same key joins rather than receiving a 409. That is the rollback path, and it needs no code change and no different
   image.
6. F22 stays closed. The collision it records was two flows sharing one browser process and one fixed CDP port.
   Neither exists after this change, and section 9 of `tasks.md` proves it with a test rather than an assertion.

## Open Questions

1. The default cap of 4 is derived from the display geometry and from the four rows that collided, not from a
   measured memory figure for four concurrent headful Chromium on this host. Task 12.2 measures it and either
   confirms 4 or lowers it, before the change is called done.
2. Whether the intervention listing should also report the flows that finished recently, with their outcome, so a
   human who solved a window can confirm the capture landed without reading Redis directly. Deliberately not built
   here. The e2e suite reads the session key directly, which is a stronger check.
3. On 2026-09-10 the headed NoVNC browser cleared the scrapingcourse.com Cloudflare wall on its own, with nobody at
   the keyboard, twice within three minutes, while headless FlareSolverr and headless Playwright stealth could not,
   and the clearance the headed browser captured (`produced_by` `6-novnc`, `cf_clearance` present, same user agent)
   did not replay through headless Playwright. Whether an unattended headed slot should become an automated tier
   before the human is asked, and whether a clearance produced by a headed browser must be replayed by a headed
   browser, is left to this change's implementation to measure.
