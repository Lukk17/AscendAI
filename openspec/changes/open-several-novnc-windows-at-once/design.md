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
- A configurable maximum per container, with 409 reserved for that maximum and for nothing else.
- Safe with several ascend-web-hunter containers at once: a request that reaches any container joins a live flow for
  its site and profile, wherever that flow runs.
- Complete failure isolation: one flow dying costs one flow and one capture that was never made.
- The lease-based self-healing kept, and extended so reclaiming a slot also removes the dead window.
- The session key scheme unchanged.

## Non-Goals

- More than one display, more than one VNC endpoint, or more than one tunnel.
- Authenticating the VNC URL.
- Any waiting or queueing behind the cap.

## Decisions

### Decision 1: A slot registry per container, with the flow records in Redis

Several ascend-web-hunter containers run at once (owner answer 87 of 2026-10-08, rule R1). Each container has its own
Xvfb display, its own browsers and its own NoVNC address, so what a flow holds on a screen belongs to one container.
What another container or a retried request must see is the flow itself, so the flow record lives in Redis, the store
the session records already live in.

`src/reader/novnc/flow_registry.py` holds `NoVNCFlowRegistry`, a single module-level instance per process, and
`NoVNCFlow`, the record of one live flow.

A `NoVNCFlow` carries: `flow_id` (12 hex characters from `uuid4`), `key` (registrable domain and profile),
`url`, `profile`, `intervention_type`, `window` (the slot and its rectangle, Decision 5), `vnc_url`, `started_at` (wall
clock, so every container reads the same age), `request_id` (the correlation id of the `ascend-python-common` request
context) and, in the process that runs it only, `task` (the monitor, attached immediately after creation) and the
monotonic start its lease is measured from.

Two stores, each with one job:

- Redis holds one record per live flow under the key `novnc_flow:{registrable_domain}:{profile}`, in the key style of
  `session:{domain}:{profile}` and `tier_memory:{registrable_domain}`. The value is the flow as JSON without the task,
  and the key expires after the flow's lease (Decision 7). It is written with `SET NX PX`, so when two containers
  reserve the same key at the same moment exactly one write wins. This record is what makes a join work across
  containers and what the listing reads.
- The process holds the slot pool of its own display, `NOVNC_MAX_CONCURRENT_FLOWS` slots, and the monitor task of each
  flow it runs. A slot is a place on this container's display, so it is never shared with another container, and the
  cap is a per container cap, which is what its memory and display arguments are about.

The registry's surface:

- `find(key)` returns the live flow for that key from its Redis record, or `None`.
- `reserve(key, url, profile, intervention_type)` takes the lowest free local slot, then writes the Redis record with
  `SET NX PX`. It raises `NoVNCFlowBusyException` when every local slot is taken. When the write loses because another
  request on this or another container wrote the key first, it frees the slot and returns the existing flow as a join.
- `attach_task(flow_id, task)` binds the monitor to the local record.
- `release(flow_id)` frees the local slot and deletes the Redis record only while that record still holds this
  `flow_id`, in one compare and delete script, so a flow never deletes a record a later flow wrote. It is idempotent
  and it ignores an unknown identifier, so a monitor's `finally` can call it unconditionally.
- `active()` returns the live flows of every container, read from Redis by the `novnc_flow:` key prefix, ordered by
  `started_at`.
- `local()` returns the flows this process runs, ordered by `started_at`. The 409 and the sweep read it.
- `sweep()` cancels every local flow whose lease has expired and returns them.
- `shutdown()` cancels every local flow and waits, bounded, for each teardown.

The local slot choice is synchronous and contains no `await`, so two requests in one process can never take the same
slot: the registry is touched only from the event loop thread, and a function with no suspension point inside it
cannot interleave with another. Two requests in two containers never compete for a slot, because each container has
its own. The only shared decision, which request owns a key, is made by the `SET NX` write in Redis. No in-process lock
decides anything another container must agree with.

Between `reserve` and the monitor being created there is one await, the VNC URL resolution, which reaches Ngrok's API
with a 5 second timeout. The slot and the Redis record are already reserved across that await, so the cap holds and a
second caller joins. If the resolution raises, the slot is released and the Redis record deleted before the exception
propagates. That is the shape the lock already uses and it is kept deliberately.

A Redis error never fails the read. The registry writes one WARNING line and keeps the flow in the process only, which
is the behaviour of a single container, so a join then works only inside the same container until Redis answers
again. This is the rule the session store and the tier memory already follow. A container that dies without a
shutdown leaves its records in Redis until their lease runs out, so for at most one lease a join can answer a window
on a display that is gone. The lease bounds it, and the caller asks again after it.

Rejected: keeping the lock and raising its capacity to N with a counter. A counter cannot answer which slot a window
belongs to, cannot list live flows, cannot cancel a specific wedged monitor, and cannot key a join. Every one of those
is required here.

### Decision 2: The flow key is the session key

The flow key is the registrable domain plus the profile, which is exactly what `CookieManager` keys its Redis record
on (`session:{domain}:{profile}`). Two consequences follow directly and neither needs enforcement anywhere else:

- Two live flows can never write the same session record, on one container or on several, because two live flows can
  never share a key: the `SET NX` write of Decision 1 admits one flow per key in the whole deployment.
- A second request for a key that already has a live flow is asking for a record another flow is already producing.

`CookieManager.registrable_domain(url)` is already a public static method in `cookie_manager.py`, and
`rest_endpoints.py` and `mcp_server.py` already call it without any `# noqa: SLF001`. The registry calls the same
public method. No promotion and no clean-up is needed, and the rule keeps one implementation.

### Decision 3: A duplicate joins, it does not get a 409

When `find(key)` returns a live flow, or `reserve` loses the `SET NX` write to one, the caller receives that flow's
`vnc_url`, `flow_id` and `window`, with `joined: true` in the 428 body, whichever container the caller reached. No
second window opens, no second monitor starts, no second browser launches.

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

Each slot maps to a deterministic window rectangle. Size is `WINDOW_WIDTH_PX` by `WINDOW_HEIGHT_PX`, constant for
every slot. Position cascades:

```text
x = (slot * WINDOW_CASCADE_OFFSET_PX) mod (display width  - WINDOW_WIDTH_PX  + 1)
y = (slot * WINDOW_CASCADE_OFFSET_PX) mod (display height - WINDOW_HEIGHT_PX + 1)
```

`WINDOW_WIDTH_PX`, `WINDOW_HEIGHT_PX` and `WINDOW_CASCADE_OFFSET_PX` in the formula are the settings
`NOVNC_WINDOW_WIDTH_PX` (default 1280), `NOVNC_WINDOW_HEIGHT_PX` (default 800) and `NOVNC_WINDOW_CASCADE_OFFSET_PX`
(default 48), and the display size is the setting `NOVNC_DISPLAY_SIZE` (default `1920x1080`), all read through
`config.py` and passed by compose as `${VAR:-default}` (owner rule 98 of 2026-10-08). `window_layout.py` holds no size
of its own. The display size has one variable: supervisord starts Xvfb with
`-screen 0 %(ENV_NOVNC_DISPLAY_SIZE)sx24` and the service reads the same variable, so compose sets it for both. The
Dockerfile keeps `ENV NOVNC_DISPLAY_SIZE=1920x1080` as the image's own value for a container started without compose,
and a test keeps it equal to the default in `config.py`.

The modulus is what makes this safe at any cap. However large the cap is set, no window is ever placed partly or
wholly off screen, and the arithmetic is pure, total and trivially testable at every slot from 0 to the cap.

Cascade rather than tile, for one reason: a captcha has to be solvable. At the default cap of 4, a tile is 960 by 540
before browser chrome, which is a cramped surface for a reCAPTCHA image grid. The cascade keeps every window at
1280 by 800 whatever the cap is, and pays for that with overlap that fluxbox lets the human resolve with a click. At a
raised cap the stack gets deeper, and that is stated as accepted behaviour rather than hidden.

Windows are identified to the caller by the `window` object in the 428 body, in the 409 `flows` entries and in the
intervention listing, all of which carry the same `window` object (the slot index and the rectangle) alongside the
target URL. The rectangle stays, because the e2e spec of task 11.3 checks with it that every window lies inside the
display. Each window's title is the page's own title,
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

- `finally` closes its own browser and calls `registry.release(flow.flow_id)`, which frees the local slot and
  deletes the flow's own Redis record, both wrapped so a failure in one cannot skip the other.
- `asyncio.CancelledError` is caught explicitly, records the outcome `cancelled`, closes the browser, releases the
  slot, and re-raises. Without the explicit catch, reclamation and shutdown would leave the browser running.
- The monitor never calls anything that could reach another flow's browser, task or session key.
- The monitor never clears a session record. It only writes, and only under its own key. A capture already persisted
  survives any subsequent failure of the flow that made it.

The strong-reference set `_active_monitor_tasks` is no longer needed as a separate structure: the registry holds the
task on the flow record, which is the strong reference, and the record is only dropped on release.

### Decision 7: The lease is per flow, it cancels, and it is swept on a timer

Each flow's lease is `NOVNC_TIMEOUT_SECONDS` plus the setting `NOVNC_FLOW_LEASE_GRACE_SECONDS` (default 30 seconds,
the value of today's constant `_NOVNC_LOCK_LEASE_GRACE_SECONDS`, which it replaces), measured from that flow's own
start. The grace covers the
gap between the monitor's own timeout firing and its `finally` actually completing, which is what the original
constant's comment says and it remains true per flow. The Redis record of the flow expires after the same lease, so a
record whose owner died disappears on its own and no container ever sweeps another container's records.

Two changes to how expiry is handled:

- Expiry cancels the monitor rather than only freeing the slot. The cancellation runs the monitor's teardown, which
  closes the browser and removes the window. The old lock freed the slot and left the wedged browser running, which
  with one window was invisible and with four would fill the display with dead windows.
- The sweep runs on a timer only, every `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS` (a setting, default 30 seconds, one grace
  period), from a task started in the existing lifespan. A lazy-only sweep leaves a dead window on the display
  indefinitely when no further request arrives, which is exactly the situation after a burst. The lazy sweep at the
  top of `find` and `reserve` is dropped (owner answer 93 of 2026-10-08): `find` reads Redis, where an expired record
  is already gone, and a local slot whose lease ran out is held at most one sweep interval longer.
- Each container sweeps only its own flows, because only it holds their browsers and their windows. This is local
  timed work that is correct when every container runs it for itself, so it takes no Redis lock (owner answer 87 of
  2026-10-08, CANON rule for local timed work).

A cancelled monitor that does not finish within `NOVNC_FLOW_CANCEL_GRACE_SECONDS` (a setting, default 10 seconds) has its
slot freed anyway, its records dropped, and an orphan logged and counted. The registry never blocks on a process that
will not die.

### Decision 8: Shutdown drains

The lifespan's `finally` calls `registry.shutdown()` before the browser pool is stopped. It cancels every live monitor
of this container, which deletes their Redis records, and waits up to `NOVNC_FLOW_CANCEL_GRACE_SECONDS` in total for the
teardowns. The flows of other containers are not touched. Today monitors are simply abandoned at
shutdown, which leaks Chromium processes on every restart while an intervention is open.

### Decision 9: The contract grows, and nothing in it moves

This change lands after `add-ascend-python-common`, which lands before every later change that touches a Python
service. That change turns the REST 428 and 409 into RFC 7807 problem bodies built by the shared library (owner answer
60.2 of 2026-10-03), supersedes the body shape ADR-003 recorded, and keeps the MCP status objects of `web_read` and
`session_establish` as they are. This change builds on that shape and adds fields to it. It renames, retypes or
removes nothing.

The REST 428 body keeps `code` `human_intervention_required`, `detail`, and the extension members `intervention_type`
and `vnc_url`, because the MCP tool docstring names `vnc_url` and `intervention_type` and every downstream agent reads
them. It gains three extension members:

```json
{
  "type": "https://ascend.ai/errors/human-intervention-required",
  "title": "Precondition Required",
  "status": 428,
  "detail": "Manual Captcha resolution required. Please visit: ...",
  "instance": "/api/v2/web/read",
  "code": "human_intervention_required",
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
  "intervention_type": "captcha",
  "vnc_url": "https://abc123.ngrok.io/vnc.html?autoconnect=true",
  "flow_id": "9f2c41ab77de",
  "joined": false,
  "window": { "slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800 }
}
```

The MCP status object of `web_read` keeps `status`, `intervention_type`, `vnc_url` and `message`, and gains the same
`flow_id`, `joined` and `window`.

The REST 409 body keeps `code` `novnc_busy`, `detail`, and the extension members `holder_url` and `holder_profile`.
`holder_url` and `holder_profile` now describe the oldest live flow of the container that refused, which is the one
whose slot frees next, so a caller that already reads them still gets a true and useful answer. It gains three
extension members, which describe the container that refused, because the cap is per container:

```json
{
  "type": "https://ascend.ai/errors/novnc-busy",
  "title": "Conflict",
  "status": 409,
  "detail": "All 4 intervention windows are in use. ...",
  "instance": "/api/v2/web/read",
  "code": "novnc_busy",
  "traceId": "4bf92f3577b34da6a3ce929d0e0e4736",
  "holder_url": "https://nowsecure.nl",
  "holder_profile": "default",
  "active_flows": 4,
  "max_concurrent_flows": 4,
  "flows": [
    {
      "flow_id": "9f2c41ab77de",
      "url": "https://nowsecure.nl",
      "domain": "nowsecure.nl",
      "profile": "default",
      "intervention_type": "captcha",
      "window": { "slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800 },
      "age_seconds": 207.3,
      "expires_in_seconds": 412.7,
      "vnc_url": "https://abc123.ngrok.io/vnc.html?autoconnect=true"
    }
  ]
}
```

Every entry of `flows` has one shape, the flow shape, in the 409 body and in the listing below (owner answer 93 of
2026-10-08, review item B9).

The MCP `novnc_busy` status object keeps `status`, `message`, `holder_url` and `holder_profile`, and gains the same
three fields.

`Retry-After` stays a short fixed poll interval rather than the remaining lease. A human can free a slot at any
instant, so the remaining lease is an upper bound of up to ten minutes and telling a caller to wait that long would be
accurate and useless. The value is the setting `NOVNC_BUSY_RETRY_AFTER_SECONDS` (default 30 seconds, the value of
today's constant `_NOVNC_BUSY_RETRY_AFTER_SECONDS` in `exception_handlers.py`, which it replaces, owner rule 98 of
2026-10-08), and the `novnc_busy` entry of the service's `ErrorRegistry` takes the header from it. A retry may reach another container, which may have a free slot.

Both REST bodies are built by the library's problem builder from the registry entries of
`human_intervention_required` and `novnc_busy` in `exception_handlers.py`, which read the new fields from the
exception as extension members. This change adds no handler and no body builder of its own.

`GET /api/v2/session/interventions` returns:

```json
{
  "active_flows": 2,
  "max_concurrent_flows": 4,
  "flows": [
    {
      "flow_id": "9f2c41ab77de",
      "url": "https://nowsecure.nl",
      "domain": "nowsecure.nl",
      "profile": "default",
      "intervention_type": "captcha",
      "window": { "slot": 0, "x": 0, "y": 0, "width": 1280, "height": 800 },
      "age_seconds": 12.4,
      "expires_in_seconds": 617.6,
      "vnc_url": "https://abc123.ngrok.io/vnc.html?autoconnect=true"
    }
  ]
}
```

The listing reads `active()`, so it holds the live flows of every container, each with the `vnc_url` of the display
it is on, and `active_flows` counts them all. `max_concurrent_flows` is the cap of each container. The field names are
the ones of the 409 body, and each entry is the flow shape of the 409 `flows` (owner answer 93 of 2026-10-08, review
item B9). `expires_in_seconds` is the remaining expiry of the flow's Redis record.

It is a GET because it takes no input, unlike the other session operations which POST a URL in a body. It is not
paginated and does not need to be: the collection is bounded by `NOVNC_MAX_CONCURRENT_FLOWS` times the number of
containers, and the cap is stated in the response itself. It returns no cookies, no storage state and no page content. It does return the `vnc_url`, which the
428 body already returns unauthenticated on the same service, so the disclosure is not new, and it is recorded in
ADR-013 alongside the rest of the posture.

### Decision 10: Readiness does not change

A full registry means interventions are capped, not that the service is unwell. Search works, every non-intervention
read tier works, and the correct answer to a caller over the cap is the 409 it already receives. Adding the registry
to `/ready` would take the whole service out of rotation because four humans are busy. This is written into the
observability spec as a requirement so it is not added later by reflex.

### Decision 11: The NoVNC address of a flow names the container that owns its window (owner answers 94.4 and 95.1 of 2026-10-08)

With several ascend-web-hunter containers, each container has its own display and its own NoVNC server on container
port 7900 (Decision 1). `NOVNC_PUBLIC_URL` is one base address shared by every ascend-web-hunter container: the
address of the web-hunter edge proxy `ascend-web-hunter-edge` of `scale-web-hunter-across-containers` (build group 2,
position 11, owner answer 96 of 2026-10-08), or of a gateway that forwards `/novnc/` to it, an absolute `http` or
`https` URL with no path. No container
publishes a NoVNC port of its own, and ascend-web-hunter scales as one compose service (owner answer 95.1). When the VNC
URL of a new flow is resolved (the one await between `reserve` and the monitor, Decision 1), the container that owns
the window builds it from the base and its own host name, read from the container itself with `socket.gethostname()`
(the same value as `HOSTNAME`), and writes it into the flow record:

`<NOVNC_PUBLIC_URL>/novnc/<hostname>/vnc.html?autoconnect=true&path=novnc/<hostname>/websockify`

The `path` parameter is needed because the noVNC of the image opens its WebSocket at `/<path>` from the root of the
host, not next to `vnc.html`. Checked on 2026-10-08 in the image `ascend-ai-ascend-web-hunter:latest`: package
`novnc` 1:1.3.0-2, `/usr/share/novnc/app/ui.js` line 175 sets the default `path` to `websockify` and line 1025
appends `'/' + path` to the host. Without it the WebSocket of every window would go to `<NOVNC_PUBLIC_URL>/websockify`,
which the edge proxy does not route.

The edge proxy of `scale-web-hunter-across-containers` (its design D2) routes `/novnc/<name>/*` to `http://<name>:7900`
on the Docker network, with the prefix `/novnc/<name>` removed, only for names of ascend-web-hunter containers, and keeps
the VNC password of each display. The NoVNC site of the platform gateway of `harden-cloud-deployment` (build group 3,
its task 2.7) forwards to that proxy and routes no name itself (owner answer 96 of 2026-10-08). This change only adds
the setting and the rule, and lands before the proxy, so until `scale-web-hunter-across-containers` lands
`NOVNC_PUBLIC_URL` stays unset and one container runs. The owner answer named port 6080. The NoVNC server of the image listens on 7900
(`supervisord.conf` line 21, `Dockerfile` line 46), so the route uses 7900.

When `NOVNC_PUBLIC_URL` is unset (one container and no gateway), today's resolution through `PUBLIC_VNC_URL` (a fixed
address or the Ngrok API) and the one Ngrok tunnel `ngrok-ascend-web-hunter` stay as they are.

The flow record in Redis carries that `vnc_url`, so every answer about a flow names the address of the container that
owns its window, never the address of the container that answers: the 428 of a new flow, the 428 with `joined: true`
that a request on another container receives (Decision 3), the `flows` of the 409 and every entry of the listing
(Decision 9). A container never builds a `vnc_url` for a flow it does not own. The fields of the 428 body, the 409 body
and the listing do not change.

Closed by owner answer 95.1: no host port for NoVNC on any container, so no bind address for it either, and one
compose service for ascend-web-hunter, scaled by its replica count. `PUBLIC_VNC_URL` and the one Ngrok tunnel stay for
the single container without a gateway. This change adds the setting and the rule, and the compose files pass
`NOVNC_PUBLIC_URL` through unset by default.

A consequence for the compose file, checked on 2026-10-08: the `ascend-web-hunter` service of
`compose.ascend-web-hunter.yaml` fixes `container_name: ascend-web-hunter` and `hostname: ascend-web-hunter` (lines
176 and 177) and publishes the host port `7021:7021`. Several replicas of one service need all three gone, because a
fixed host name would give every replica the same name. Without them Docker gives each replica its short container ID
as host name, and the compose network resolves that ID (checked on 2026-10-08: `docker inspect` lists the short ID
among the `DNSNames` of a container on `ascend-ai_default`). While this change is the latest one, the one container
keeps the host name `ascend-web-hunter` and the route works the same. `scale-web-hunter-across-containers` (build group
2, position 11) removes the three lines in both compose files (owner answer 96 of 2026-10-08), and from then on a single
copy also has its short container ID as host name.

## Configuration

| Setting | Default | Derivation |
| :-- | :-- | :-- |
| `NOVNC_MAX_CONCURRENT_FLOWS` | `4` | Per container. Four is what the 2026-09-10 run needed (rows n, o, p and t all queued behind one human). Four 1280x800 windows fit the 1920x1080 display under the cascade with every title bar reachable. Four headful Chromium plus four Playwright drivers is the memory the host can carry beside the headless pool, SearXNG and FlareSolverr. The setting is a memory constraint as much as a display one and its documentation says so. |
| `NOVNC_DISPLAY_SIZE` | `1920x1080` | The one variable of the display size (Decision 5). supervisord starts Xvfb from it and the service reads it, so compose sets it for both. The Dockerfile also sets `1920x1080` for a container started without compose, and a test keeps the two equal. Today's Xvfb geometry. |
| `NOVNC_PUBLIC_URL` | none (unset) | One base address shared by every ascend-web-hunter container, the address of the web-hunter edge proxy of `scale-web-hunter-across-containers` (or of a gateway that forwards `/novnc/` to it), with no path. Each container builds the `vnc_url` of every flow it owns from it and its own host name (Decision 11, owner answers 94.4 and 95.1 of 2026-10-08). Unset keeps today's `PUBLIC_VNC_URL` resolution and the one Ngrok tunnel, which serve one container. |
| `NOVNC_WINDOW_WIDTH_PX` | `1280` | Wide enough for a reCAPTCHA image grid and a full login form without horizontal scrolling. |
| `NOVNC_WINDOW_HEIGHT_PX` | `800` | Leaves 280 px of the 1080 display for the cascade and for browser chrome. |
| `NOVNC_WINDOW_CASCADE_OFFSET_PX` | `48` | Wider than a fluxbox title bar, so every earlier window keeps a clickable strip. |
| `NOVNC_FLOW_LEASE_GRACE_SECONDS` | `30.0` | Today's `_NOVNC_LOCK_LEASE_GRACE_SECONDS` unchanged, whose comment already derives it as teardown time rather than a second timeout window. |
| `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS` | `30.0` | One grace period. A dead window leaves the display within about the time the grace already allows for teardown. |
| `NOVNC_FLOW_CANCEL_GRACE_SECONDS` | `10.0` | Bounds reclamation and shutdown. A browser that has not closed in ten seconds is not going to, and the slot is worth more than the wait. |
| `NOVNC_BUSY_RETRY_AFTER_SECONDS` | `30` | Today's `_NOVNC_BUSY_RETRY_AFTER_SECONDS` of `exception_handlers.py` unchanged, with its existing rationale: a short actionable poll, not the flow's own timeout. |

Every row is a setting (owner rule 98 of 2026-10-08, which replaces the module constants of owner answer 93 for these
values): `config.py` carries the default, the `ascend-web-hunter` service of both compose files passes it as
`${VAR:-default}` with the same value, and the sync rule puts each name into both `.env.example` files and the bundle
README (task 1.6). The rows of `docs/configuration.md` end with "Added by `open-several-novnc-windows-at-once`." (task
10.1).

Two validators run at settings construction, so a bad combination fails at startup and not at the first intervention:
every number has its minimum (the cap at least 1, the window sizes and the offset at least 1, the three durations above
0, the `Retry-After` at least 1), and `NOVNC_DISPLAY_SIZE` must read `<width>x<height>` with the window settings fitting
inside it on both axes.

`NOVNC_TIMEOUT_SECONDS` and `NOVNC_COOKIE_SYNC_POLL_SECONDS` keep their names, defaults and meanings, now applied per
flow.

## Observability

| Signal | Type | Labels | Meaning |
| :-- | :-- | :-- | :-- |
| `novnc_active_flows` | Gauge | none | Live intervention flows of this container. Set on every reserve, join is not counted, decremented on every release. Each container reports its own, and the sum over containers is the deployment's figure. |
| `novnc_flow_busy_total` | Counter | none | Kept. Now counts exactly one thing: refused because the cap was reached. |
| `novnc_flows_reclaimed_total` | Counter | `reason` | `lease_expired`, `shutdown` or `cancel_timeout`. |
| `strategy_attempts_total` | Counter | `strategy`, `outcome`, `domain` | Kept, with `6-novnc-monitor` gaining the outcome `cancelled` beside `resolved`, `timeout` and `rejected`. |
| `human_intervention_total` | Counter | `intervention_type`, `joined` | Kept, and the one counter of 428 answers. It gains the label `joined` (`true` or `false`): `joined="false"` counts the flows started and `joined="true"` the requests that joined a flow. No second counter counts the same 428s (owner answer 93 of 2026-10-08, review item C12). |

Every log line from the registry, the strategy and the monitor carries `flow_id` and `slot`, and the reserve line also
carries the originating correlation id of the `ascend-python-common` request context. That is what lets an operator take a 428 a
caller reported, find the window it opened, and find the capture it eventually produced.

## Migration from the global lock

1. `_NoVNCFlowLock`, `_novnc_flow_lock` and `_active_monitor_tasks` are deleted rather than deprecated. All three are
   module-private and their only references outside `novnc_strategy.py` are its own tests.
2. `_NOVNC_LOCK_LEASE_GRACE_SECONDS` becomes the setting `NOVNC_FLOW_LEASE_GRACE_SECONDS` and
   `_NOVNC_BUSY_RETRY_AFTER_SECONDS` becomes the setting `NOVNC_BUSY_RETRY_AFTER_SECONDS`, each with the same value as
   its default (owner rule 98 of 2026-10-08), and `_CDP_REMOTE_DEBUGGING_PORT` is deleted with the fixed port.
3. `NoVNCFlowBusyException` keeps its class name and its `holder_url` and `holder_profile` attributes, so
   `main.py`'s handler registration, `mcp_server.py`'s two catch sites and `rest_endpoints.py`'s docstring stay
   valid. It gains `active_flows`, `max_concurrent_flows` and `flows`, and its message is reworded to name the cap.
4. `tests/reader/strategies/test_novnc_flow_lock.py` is deleted with the class it tests.
   `tests/reader/strategies/test_novnc_concurrency.py` is rewritten: its first case becomes "two concurrent flows both
   get their own window", its second becomes "the fifth is refused at the cap", and its lease case is kept and moved
   onto the per-flow lease.
5. Behaviour at `NOVNC_MAX_CONCURRENT_FLOWS=1` on one container is today's behaviour, with one intended difference: a
   duplicate for the same key joins rather than receiving a 409. That is the rollback path, and it needs no code change
   and no different image. With several containers the cap of 1 holds per container.
6. F22 stays closed. The collision it records was two flows sharing one browser process and one fixed CDP port.
   Neither exists after this change, and section 9 of `tasks.md` proves it with a test rather than an assertion.

## Open Questions

All three were closed by owner decision 65.28 of 2026-10-04: the cap stays 4 until task 12.2 measures it, the
intervention listing reports no finished flows, and an unattended headed tier is a later change. The texts below keep
the reasoning.

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
   browser, is out of scope for this change. The owner recorded it on 2026-10-01 as a possible follow-up change.
   Nothing here builds or measures it.

## Owner decisions of 2026-10-08

The owner approved on 2026-10-08 the fixes of the review of the group 1 and group 2 changes of 2026-10-07.

- Item 5: the concurrent intervention spec of task 11.3 reads the listing field `max_concurrent` of Decision 9. The
  409 body keeps `max_concurrent_flows`. (Superseded by answer 93 below: the listing now uses the 409 names
  `active_flows` and `max_concurrent_flows`, and task 11.3 reads those.)
- Item 6: the captcha wall page the spec of task 11.3 reads is `/turnstile-wall`, which task 11.9 adds to the shared
  fake site. `detect-challenge-walls-in-any-language` keeps it a wall under the scored detector (its task 11.12).
- Item 19: tasks 9.3 and 9.4 run every tool as `python -m <tool>` through the module's `.venv`, never a console
  script, and mypy checks `src tests`, the same gate as `add-ascend-python-common` D14.
- Item 20: spec 7 carries one cap rule. Task 11.1 writes "at least 4", and `detect-challenge-walls-in-any-language`
  task 11.5 replaces it in place with "at least 5".
- Owner decision of 2026-10-08, "one named version per change, in build order": this change ships as
  ascend-web-hunter 0.0.9, one patch step after 0.0.8 of `add-python-runtime-upgrades` (build group 2, position 2).
  It no longer shares a version with `detect-challenge-walls-in-any-language`, which ships as 0.0.10 with its own
  entry (task 10.5).

Answer 87: the flow registry is made safe with several
ascend-web-hunter containers (Decision 1). The flow record lives in Redis under `novnc_flow:{domain}:{profile}`,
written with `SET NX PX` and expiring after the lease, so a request on any container joins a live flow and two
containers can never open two windows for one key. The slot pool, the browsers, the windows and the monitor tasks
stay per container, because they belong to that container's display. The cap is per container. The listing reads
every container's flows from Redis. The lease sweep is local timed work that each container runs for its own flows
and takes no Redis lock, and an orphaned record of a dead container expires on its own. Every multi-instance
mechanism already planned is kept.

Answer 93: of the ten planned settings only `NOVNC_MAX_CONCURRENT_FLOWS` stays. The window
size, the cascade offset, the lease grace, the sweep interval, the cancel grace and the busy `Retry-After` are module
constants, `NOVNC_MAX_CONCURRENT_FLOWS` and `NOVNC_TIMEOUT_SECONDS` stay settings, and the display size has one
source, `NOVNC_DISPLAY_SIZE` set in the Dockerfile and read by supervisord and by the service (Decision 5 and the
configuration table). `novnc_flows_started_total` and `novnc_flow_joined_total` are dropped, and
`human_intervention_total` gains the label `joined` in their place. The lazy sweep at the top of `find` and
`reserve` is dropped and the timer sweep stays, which fits answer 87 because `find` reads Redis, where an expired
record is already gone. Task 3.5, the test that the registry methods are not coroutines, is removed: the registry
now awaits Redis, and the `SET NX` write is what makes a reservation safe. The listing and its MCP tool stay, and the
listing and the 409 `flows` use one flow shape and the 409 field names `active_flows` and `max_concurrent_flows`.
The window rectangle stays in the 428 body, the 409 entries and the listing, because the spec of task 11.3 checks
with it that every window lies inside the display. (Changed by answer 98 below: the window size, the cascade offset,
the lease grace, the sweep interval, the cancel grace and the busy `Retry-After` are settings again, with the same
values as defaults, and `NOVNC_DISPLAY_SIZE` has the default `1920x1080`.)

Answer 93: Not applied, left to the owner. Review item C13 also proposes that the cleanup of task 11.3 step 7
restarts ascend-web-hunter instead of waiting about 11 minutes for the leases to run out. A restart of a container
needs the owner's yes, so step 7 keeps the wait until the owner answers.

Answer 92: review item A5 (one shared browser or one shared Playwright driver for every
window) is not applied. One browser process per flow stays, because it is what keeps a crash of one window from
ending the others (Decision 4).

Answer 91.3: the concurrent intervention spec of task 11.3 stays. It is the one deterministic
spec of this capability, and it is the only test that opens several real headful Chromium windows on the real Xvfb
display of the image, which the unit tests replace with doubles. The human Part 2 of spec 11 and the spec 7 rows run
against real sites and stay.

Answer 85.1: no task of this change exports a key or a secret in a shell. `VNC_PASSWORD`,
which ADR-013 recommends, is set in the repository `.env` file like every other secret.

Answer 94.4: with several ascend-web-hunter containers, each publishes its own NoVNC port and has the setting `NOVNC_PUBLIC_URL`, and the 428 answer gives the NoVNC address of the container that owns the window, the `vnc_url` of the owner's flow record (new Decision 11, the configuration table, new tasks 1.5 and 4.5, task 10.1 extended, and a scenario of the join requirement). The host ports, the bind address, the compose shape of several containers and the future of `PUBLIC_VNC_URL` and the one Ngrok tunnel are left to the owner (Decision 11).

Answer 94.7: accepted that the ascend-web-hunter e2e sweep recreates ascend-web-hunter at its start and at its end (`add-ascend-python-common` tasks 9.10 and 9.11). A restart inside the spec of task 11.3 (review item C13) is not part of that answer, so step 7 keeps its wait.

Answer 95.1: `NOVNC_PUBLIC_URL` is one base address shared by every ascend-web-hunter container, and each container builds the `vnc_url` of its own flows as `<NOVNC_PUBLIC_URL>/novnc/<hostname>/vnc.html?autoconnect=true`, with the host name read from the container itself (`socket.gethostname()` or `HOSTNAME`). No container publishes a NoVNC port. With `NOVNC_PUBLIC_URL` unset (one container, no gateway), today's `PUBLIC_VNC_URL` and the one Ngrok tunnel stay. The gateway of `harden-cloud-deployment` routes `/novnc/{name}/*` to the container's NoVNC server, only for ascend-web-hunter container names, and the VNC password stays (its new task 2.7). The open values of answer 94.4 are closed: no NoVNC host port, so no bind address, and one compose service scaled by its replica count. Applied in Decision 11, the configuration table, tasks 1.5, 4.5 and 10.1 and the join requirement of `web-search-concurrent-human-intervention`. Two points found while applying it are recorded in Decision 11: the `vnc_url` also carries `&path=novnc/<hostname>/websockify`, because the noVNC 1.3.0 of the image opens its WebSocket from the root of the host, and the route targets port 7900, where the NoVNC server of the image listens, not the 6080 of the answer.

Answer 96: ascend-web-hunter is finished in build group 2, several containers included, because the owner deploys it on its own through the standalone bundle right after group 2. The router of Decision 11 is therefore the web-hunter edge proxy `ascend-web-hunter-edge` of the new change `scale-web-hunter-across-containers` (build group 2, position 11), not the platform gateway of build group 3, whose NoVNC site of `harden-cloud-deployment` task 2.7 now forwards to that proxy. `scale-web-hunter-across-containers` also removes the fixed `container_name`, `hostname` and host port 7021 that Decision 11 left to an undecided change, and points the one Ngrok tunnel at the proxy. Applied in Decision 11, the configuration table and tasks 1.5 and 10.1. Nothing this change builds moves.

Answer 98: every value of this change that has a default is a setting (owner rule 98 of 2026-10-08), which also
decides the module constants of answer 93 (CANON 31.13). Settings, each read by `config.py` with its default, passed by
both compose files as `${VAR:-default}` with the same value, put into both `.env.example` files and the bundle README by
the sync rule (task 1.6) and listed in `docs/configuration.md` with "Added by `open-several-novnc-windows-at-once`."
(task 10.1): `NOVNC_MAX_CONCURRENT_FLOWS` 4, `NOVNC_DISPLAY_SIZE` `1920x1080` (also kept in the Dockerfile for a
container started without compose, task 1.4), `NOVNC_WINDOW_WIDTH_PX` 1280, `NOVNC_WINDOW_HEIGHT_PX` 800,
`NOVNC_WINDOW_CASCADE_OFFSET_PX` 48, `NOVNC_FLOW_LEASE_GRACE_SECONDS` 30.0, `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS` 30.0,
`NOVNC_FLOW_CANCEL_GRACE_SECONDS` 10.0 and `NOVNC_BUSY_RETRY_AFTER_SECONDS` 30, plus `NOVNC_PUBLIC_URL` with no default
(empty, task 1.5). Each is a size, a duration or an interval an operator might change, for example a larger display or
a slower host. The display size no longer has an unset case, so the cascade always wraps. Kept as constants, because
they are not operational: the Redis key prefix `novnc_flow:`, the flow id length of 12 hex characters, the metric
names and labels, the `vnc_url` path shape `/novnc/<hostname>/vnc.html` and the noVNC container port 7900 of the
image. Values found in today's code that this change does not plan (the Ngrok API timeout of 5 seconds and
`_INITIAL_NAV_TIMEOUT_MS` in `novnc_strategy.py`) are not moved here. Tasks changed: 1.1 to 1.4, 2.1, 3.4, 6.1, 10.1
and 12.2, new task 1.6. No task of this change is ticked, so nothing is marked for rework. The proposal's lease
bullet, the requirement "A flow that stops without releasing is reclaimed, window included" of
`web-search-concurrent-human-intervention` and the requirement "Every flow's window is placed deterministically and
stays fully on screen" of `web-search-intervention-display` name these values as settings instead of fixed values. No
plan of this change uses LM Studio as a default in a test or a measurement, none uses the old `e2e` profile or overlay
mount, and none says that running several copies in production is planned elsewhere: several ascend-web-hunter
containers are finished in build group 2 by `scale-web-hunter-across-containers` (answer 96).
