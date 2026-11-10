# ADR-013: Concurrent human-intervention windows on one shared display

## Status

Accepted - 2026-10-19

## Context

ADR-003 gave the service one human-intervention flow at a time: one browser
window, one fixed CDP port (`--remote-debugging-port=9222`), and later one
global lock (`_NoVNCFlowLock`). A real test run on 2026-09-10 showed four
unrelated rows of the Part 1 matrix answering 409 because one human was still
working on an earlier window, while ADR-003's own risk section already said:
"No cap on concurrent tasks exists today." The lock answered that by setting
the cap to one. One is the wrong number: the display the service already runs
(Xvfb at 1920x1080 under supervisord with fluxbox as the window manager) can
show several independently raisable, closable windows over the one NoVNC
connection, and a second caller for the same site is waiting on the same
session record as the first, so serving it from the first flow's outcome is
correct, not a compromise.

## Decision

### D1 - A slot registry per container, with the flow records in Redis

`src/reader/novnc/flow_registry.py` holds `NoVNCFlowRegistry` (one
module-level instance per process) and `NoVNCFlow`, the record of one live
flow. Each container owns its display, so the slot pool (`NOVNC_MAX_CONCURRENT_FLOWS`
slots), the browsers and the monitor tasks live in the process. What every
container must agree on is the flow itself, so each live flow also has a
record in Redis under `novnc_flow:{registrable_domain}:{profile}`, written
with `SET NX PX` for the flow's lease and deleted on release by a
compare-and-delete script, so a flow never deletes a record a later flow
wrote. The key is the registrable domain plus the profile that
`CookieManager` already keys the session store on, so two live flows can
never write the same session record. A duplicate request joins the live
window (428 with `joined: true`) instead of opening a second one or being
refused; only a full container answers 409, with `active_flows`,
`max_concurrent_flows` and the per-flow entries. Failure stays inside one
flow: the monitor closes its own browser and releases its own slot, expiry
cancels the monitor (which removes the dead window), the sweep runs on a
timer per container without a Redis lock, and shutdown drains with a bound.

### D2 - One browser process per flow, and no fixed CDP port

Each flow calls `chromium.launch()` for itself, inside its own
`async with async_playwright()`. Nothing is shared. `--remote-debugging-port=9222`
becomes `--remote-debugging-port=0` (the OS assigns a free ephemeral port per
launch, so two launches can never contend) and `--remote-debugging-address=127.0.0.1`
binds that port to loopback instead of every interface, closing the
sibling-container exposure ADR-003 recorded as accepted. Playwright creates a
fresh temporary profile per launch; no explicit profile directory is passed.

### D3 - The display is shared by placement, not by partition

Each slot maps to a deterministic `1280x800` rectangle cascading by 48 px
per slot with a wrapping modulus, so however large the cap is set no window
is ever placed partly or wholly off screen (`src/reader/novnc/window_layout.py`
holds no size of its own; every figure is a setting). Cascade rather than
tile: a captcha has to stay solvable at any cap, and fluxbox lets the human
resolve overlap with a click. Windows are identified to the caller by the
`window` object (slot and rectangle) in the 428 body, the 409 `flows`
entries and the intervention listing.

### D4 - The `vnc_url` of a flow names the container that owns its window

`NOVNC_PUBLIC_URL` is one base address shared by every ascend-web-hunter
container (the web-hunter edge proxy). Each container builds the `vnc_url` of
the flows it owns from the base and its own host name and writes it into the
flow record, so every answer about a flow names the display it is on. With
`NOVNC_PUBLIC_URL` unset (one container, no gateway), today's
`PUBLIC_VNC_URL` resolution and the one Ngrok tunnel stay as they are. No
container publishes a NoVNC port of its own.

## Alternatives Considered

### Alternative 1: One shared browser process with a `BrowserContext` per flow

- **Pros**: Removes the port question entirely and costs less memory.
- **Cons**: One crashed browser process takes every window with it, and a
  `finally` that closes the browser would close every sibling's window.
- **Why not**: A flow that dies must not take the others down; a shared
  process fails the isolation requirement outright.

### Alternative 2: One shared Playwright driver with N `launch()` calls against it

- **Pros**: Saves roughly one node bridge process per flow.
- **Cons**: Reintroduces a shared-fate component every flow's lifetime is
  coupled to, which has to be owned and restarted by somebody.
- **Why not**: At a cap of 4 the saving is under 320 MiB against total
  isolation. Isolation wins.

### Alternative 3: Reusing `BrowserPool`

- **Pros**: No new browser management code.
- **Cons**: The pool launches headless and relaunches transparently on
  disconnect, which would silently destroy every open intervention window
  whenever the headless tier had a bad minute.
- **Why not**: The pool's relaunch contract is the opposite of what open
  windows need.

### Alternative 4: Injecting a fixed banner overlay into each page to label the window

- **Pros**: Labels the window unambiguously.
- **Cons**: Modifies a page whose whole purpose is an anti-bot challenge
  that inspects the DOM.
- **Why not**: The page is left alone; the window title already names the site.

### Alternative 5: One Xvfb, x11vnc and websockify per flow, with a port and a tunnel each

- **Pros**: Per-flow display isolation.
- **Cons**: Multiplies the ports, the tunnels and the VNC URLs the human
  has to juggle by the cap, for isolation the window manager already gives
  at the window level.
- **Why not**: The whole point is one display the human already has open.

## Consequences

### Positive

- Four sites can wait on one human at once (the 2026-09-10 run needed
  exactly that many), and a duplicate caller joins instead of colliding or
  being refused.
- A wedged flow is cancelled with its window removed within about one sweep
  interval plus the lease grace, instead of leaving a dead window behind.
- Shutdown no longer abandons live Chromium processes.

### Negative

- The default cap of 4 raises the worst-case memory by roughly three
  additional headful browsers; an operator who cannot afford that sets the
  cap to 1.
- At a raised cap the human clicks through a stack of overlapping windows;
  stated as accepted behaviour, not left to be discovered.
- Reclamation cannot force-kill a Chromium that ignores its close: after
  the cancel grace the slot is freed and an orphan is logged and counted,
  and the orphan window may remain on the display.

### Risks

- **A wider unauthenticated surface.** With one window, anyone holding the
  `vnc_url` could see one site; with four, they can see four, including any
  login a human is part way through. This is a real widening of ADR-003's
  accepted posture. It is recorded here rather than buried, and the
  recommendation is plain: set `VNC_PASSWORD` on any deployment where the
  tunnel is reachable by anyone but the operator.
- **A joined flow couples two callers.** Caller B's outcome depends on a
  window opened for caller A. This is deliberate (it keeps 409 meaning one
  thing) and safe precisely because both callers were already waiting on the
  same session record. A caller that needs its own window asks for a
  different profile.

### The new listing endpoint

`GET /api/v2/session/interventions` (REST) and `session_interventions`
(MCP) return the live flows of every container with their windows and
remaining lease. The listing is read-only and unauthenticated, exactly like
the `vnc_url` in the 428 body. It returns no cookies, no storage state and
no page content. It discloses only `vnc_url` values the 428 body already
returns unauthenticated on the same service, so the disclosure is not new;
it is recorded here alongside the rest of the posture.

## Related

- `src/reader/novnc/flow_registry.py` - `NoVNCFlow`, `NoVNCFlowRegistry`, `flow_shape`.
- `src/reader/novnc/window_layout.py` - `rect_for_slot`.
- `src/reader/strategies/novnc_strategy.py` - `NoVNCStrategy`, `_monitor_for_cookies`.
- `src/api/exceptions.py` - `HumanInterventionRequiredException`, `NoVNCFlowBusyException`.
- `src/api/exception_handlers.py` - 428 and 409 registry entries, `Retry-After` from settings.
- `src/api/rest/rest_endpoints.py` - `GET /api/v2/session/interventions`.
- `src/api/mcp/mcp_server.py` - `session_interventions`, `web_read`, `session_establish`.
- `src/observability/metrics.py` - `NOVNC_ACTIVE_FLOWS`, `NOVNC_FLOWS_RECLAIMED_TOTAL`, the `joined` label.
- [ADR-003](ADR-003-novnc-ngrok-captcha-intervention.md) - superseded in part (single-flow paragraph, fixed-CDP-port bullet); the 428/409 body shape amendment stands.
