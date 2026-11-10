## Context

Every statement here was read from the code on 2026-11-08. Task 1.1 reads the same lines again, because other changes edit the same files.

How it works today, under `apps/ascend-web-hunter`:

- `supervisord.conf` starts one screen: `Xvfb :99 -screen 0 %(ENV_NOVNC_DISPLAY_SIZE)sx24 -ac +extension GLX +render -noreset` (line 9), then `x11vnc -display :99` (line 14), `fluxbox -display :99` (line 19), websockify on port 7900, and uvicorn last.
- `Dockerfile` line 76 sets `ENV DISPLAY=:99`. `x11vnc` and fluxbox name their display on the command line, so that `ENV` line matters only to the uvicorn process and the browsers it starts. Line 77 sets `NOVNC_DISPLAY_SIZE=1920x1080`. The runtime image installs `xvfb`, `x11vnc`, `novnc`, `websockify`, `fluxbox`, `dbus-x11` and `supervisor`, and sets `DBUS_SESSION_BUS_ADDRESS=autolaunch:`.
- Nothing in `src/` sets `DISPLAY`. Every browser takes it from the process environment.
- `config.py` holds `NOVNC_DISPLAY_SIZE` (line 121, validated at line 696) and `PLAYWRIGHT_HEADLESS` (default `False`, "keeps the stealth posture").
- `docs/configuration.md` says `false` is the stealth-friendly posture and `true` is only for a host with no display server. `docs/architecture/arc42/09-architecture-decisions.md` records that headless Chromium is detectable by advanced web application firewalls.

Which code opens which browser:

| Tier or path | Launch site | Headed setting | Screen today |
| :--- | :--- | :--- | :--- |
| `1-beautifulsoup`, `2-trafilatura` | no browser, `curl_cffi_fetcher.py` | none | none |
| `4-playwright_stealth` | one shared Chromium, `src/runtime/browser_pool.py` line 75, started at service start (`src/main.py` line 85) | `PLAYWRIGHT_HEADLESS` | `:99` by inheritance |
| `4a-patchright` | one Chromium per read, `patchright_strategy.py` line 79 | `PLAYWRIGHT_HEADLESS` | `:99` by inheritance |
| `4b-camoufox` | one Firefox build per read, `camoufox_strategy.py` lines 23, 46 and 57 | `PLAYWRIGHT_HEADLESS` | `:99` by inheritance |
| `5-crawlee_adaptive` | Crawlee, `crawlee_strategy.py` line 112 | `PLAYWRIGHT_HEADLESS` | `:99` by inheritance |
| `6-novnc` and `POST /api/v2/web/session/establish` (`src/session/session_manager.py` line 91) | one Chromium per flow, `_run_window` in `novnc_strategy.py` line 585 | `headless=False`, fixed | `:99` by inheritance |

Screenshots go through the `screenshot_page` of the three strategies that have one. Crawl jobs read through `WebReader` (`src/crawl/worker.py` line 148), so they take the same ladder. No automatic launch passes a window position, so the window manager places those windows. NoVNC windows get `--window-position` and `--window-size` from `src/reader/novnc/window_layout.py`.

Library facts read from the installed packages:

- Camoufox 0.5.8 measures the screen from the Python process. `camoufox/display.py` line 55 calls `screeninfo.get_monitors()`, and `camoufox/utils.py` lines 1105 and 1151 clamp the claimed screen to that size. It does not read a `DISPLAY` passed only to the browser launch.
- Playwright 1.60 replaces the whole environment when `env` is given. `driver/package/lib/coreBundle.js` line 42578 reads `options.env ? envArrayToObject(options.env) : process.env`. `env=None` keeps `process.env`.
- `fingerprint.py` sets a 1920x1080 viewport, which equals the default screen.

What is not read from code: that fluxbox gives the input focus to a new window. That is the fluxbox default as far as I know, and the owner reported the symptom. Task 2.1 reproduces the windows on the human screen with a failing test before anything is fixed.

## Goals / Non-Goals

Goals:

- Only NoVNC windows appear on the screen the human sees.
- Every automatic browser keeps its headed posture and its screen shape.
- A browser launch added later is safe by default.

Non-Goals:

- No per-flow screen. ADR-013 already rejected one Xvfb, x11vnc and websockify per flow.
- No change to window placement, the NoVNC address, flow records, or any HTTP or MCP field.
- No readiness probe for either screen. A dead Xvfb is restarted by supervisord exactly as today.
- No change to `PLAYWRIGHT_HEADLESS`.

## Decisions

### D1: The automatic screen is the process default, and only the NoVNC launch names the human screen

`supervisord.conf` gives the uvicorn program `environment=DISPLAY="%(ENV_AUTOMATIC_BROWSER_DISPLAY)s"`, and the Dockerfile drops `ENV DISPLAY=:99`. The NoVNC launch passes `env` with `DISPLAY` set to `settings.NOVNC_DISPLAY` on a full copy of `os.environ`, built by one small pure function, because Playwright replaces the whole environment. With `NOVNC_DISPLAY` empty it passes no `env` at all.

Why this way round:

- The four automatic tier files need no change.
- Camoufox measures the screen from the process environment, so a per-launch `env` on the automatic tiers would give it the wrong screen size.
- The failure mode is safe. A launch that says nothing goes to the invisible screen.

Rejected: setting `DISPLAY` per launch on the automatic tiers (four launch sites plus Crawlee options, wrong for Camoufox, and the unsafe default stays). Rejected: changing `os.environ["DISPLAY"]` around the NoVNC launch (process-wide, so a concurrent automatic launch would race onto the human screen).

### D2: What must stay headed and what moves

| Browser | Headed | Screen after this change | Reason |
| :--- | :--- | :--- | :--- |
| `4-playwright_stealth` | yes, by `PLAYWRIGHT_HEADLESS` | automatic | Headless Chromium is detectable. No human needs to see it. |
| `4a-patchright` | yes, by `PLAYWRIGHT_HEADLESS` | automatic | Same. |
| `4b-camoufox` | yes, by `PLAYWRIGHT_HEADLESS` | automatic | Same, and it needs a real screen to measure. |
| `5-crawlee_adaptive` | yes, by `PLAYWRIGHT_HEADLESS` | automatic | Same. |
| `6-novnc` | yes, fixed | human | A human has to see and use it. It is the only browser that stays on the human screen. |

Headed does not mean visible to a person. It means the browser runs in its normal mode and draws to an X server. The second screen keeps that and removes the viewer.

### D3: The second screen copies the first, including its window manager

A new supervisord program runs Xvfb with the same arguments as the first (`-screen 0 <size>x24 -ac +extension GLX +render -noreset`). A second fluxbox runs on it. With this, the only thing that changes for an automatic browser is the number in `DISPLAY`. Depth, GLX, the render extension and window management stay as they are, so no fingerprint comparison is needed to trust the move.

A screen with no window manager would save one small process, but it changes how windows are mapped and sized, which nobody has measured. It is not worth the risk for that saving.

Rejected alternatives:

- Headless mode for automatic tiers: detectable, and against `PLAYWRIGHT_HEADLESS`.
- Camoufox `headless="virtual"`: covers one tier only, starts one Xvfb per launch, and its own comment (`camoufox/utils.py` line 1150) says that 1x1 screen is not a real screen.
- A second `-screen` in one Xvfb (`:99.1`): one X server has one input focus, so focus could still be taken.
- A fluxbox rule, another workspace, or an off-screen position: the windows still share the server, and focus or visibility can still leak.

### D4: Settings

Every value with a default is a setting, as in `scale-web-hunter-across-containers` D13.

| Variable | `config.py` default | Image and compose default | Read by |
| :--- | :--- | :--- | :--- |
| `NOVNC_DISPLAY` | empty | `:99` | supervisord (Xvfb, x11vnc, fluxbox) and the NoVNC launch |
| `AUTOMATIC_BROWSER_DISPLAY` | empty | `:98` | supervisord (Xvfb, fluxbox, uvicorn `DISPLAY`) and the startup check |
| `AUTOMATIC_BROWSER_DISPLAY_SIZE` | `1920x1080` | `1920x1080` | supervisord (Xvfb) and the startup banner |

The two screen names default to empty in `config.py` so a native run keeps using the display of its own process, and the NoVNC window still opens on a developer's desktop. The Dockerfile sets all three with `ENV`, as it does `NOVNC_DISPLAY_SIZE`, because supervisord needs them even in a container started without compose. Both compose files pass `${VAR:-default}`.

`AUTOMATIC_BROWSER_DISPLAY_SIZE` is separate from `NOVNC_DISPLAY_SIZE` because an operator who enlarges the human screen to fit more windows should not change what automatic browsers look like. An operator who has already changed `NOVNC_DISPLAY_SIZE` must set the new setting too if automatic browsers should keep that size. The change log says so.

### D5: Startup refusal

`config.py` refuses, in the style of `_validate_novnc_display_size`:

- a screen name that does not match a colon and digits, because the value goes onto a supervisord command line
- the two names being equal, because the isolation would then be silently off
- exactly one name set, because the isolation could not be guaranteed
- a size that is not `<width>x<height>`

`parse_display_size` and the size format check are reused, not copied.

### D6: Banner

`startup_banner.py` line 142 prints `NoVNC display` with the size only, and spec 20 parses that line with a pattern for `<width>x<height>`, so it does not change. A new line `Automatic browser display` carries the name and size.

### D7: Security

- x11vnc stays attached only to the human screen, so the viewer loses sight of automatic browsers, which can hold pages opened with stored login sessions. Today a person on the viewer can see those.
- A login typed by a human can no longer land in an automatic browser because of a focus change.
- No port is added. The second screen is reachable only by processes inside the container, through its socket in `/tmp/.X11-unix`, the same as the first. It keeps `-ac`, like the first.
- Unit tests pin that only one `x11vnc` program exists and that it names the human screen.

### D8: Memory and process cost

Two more long-running processes per container: one Xvfb and one fluxbox. There is no second x11vnc or websockify.

The only figure known without measuring is the framebuffer: 1920 x 1080 x 4 bytes is 7.9 MiB for one screen. Xvfb and fluxbox baseline memory was not measured for this proposal, because Xvfb is not installed on the machine where it was written and no container was started. Rendering memory for automatic browsers moves from the first server to the second, so it is not an added cost. Task 6.3 measures the real cost before anything is written into a document.

`DBUS_SESSION_BUS_ADDRESS=autolaunch:` may start one more session bus per X display. That is from memory, not from code, so the same measurement counts `dbus-daemon` processes.

The limits are 4G in `compose.ascend-web-hunter.yaml` and 2560M in the standalone bundle, each with `/dev/shm` charged to it (2 GB and 1 GB). If the measured cost changes the sums in `deploy-standalone/README.md`, that section is updated in the same commit. CPU cost at idle is expected to be close to zero, and task 6.3 records it.

### D9: How the isolation is tested

The integration test starts two private Xvfb servers with `-displayfd`, so display numbers never collide, with a fluxbox on each, because without a window manager the focus check would prove nothing. It opens a real NoVNC window on one and runs real automatic reads with `DISPLAY` set to the other. It lists the top-level windows of the human screen through the X protocol before, during and after each read and compares them.

Listing needs a tool. The image has no `xwininfo`, and adding one to a production image for a test is wrong, so `python-xlib` is added to the development extra only, at a frozen version read at implementation time. The existing tests in `tests/integration/test_novnc_window_teardown.py` force `headless=True`, which cannot prove this, so the new test stays headed.

This machine has no Xvfb, and installing one changes system packages, so the test runs in a throwaway `docker run --rm` from the built image, with the supervisord entrypoint overridden. A machine with no Xvfb or fluxbox reports a skip that names the missing program, and a skip never counts as a pass for the task.

### D10: Records and version

The decision goes in an amendment of ADR-013, which recorded one shared display. The change takes the next free ascend-web-hunter version at implementation time, in the files `scale-web-hunter-across-containers` D12 lists.

## Risks / Trade-offs

- Two fluxbox processes share `/home/webhunter/.fluxbox`. If they race on first start, one may read a half-written file. Task 3.1 checks both start cleanly on a fresh container.
- Uvicorn may start before the second Xvfb is ready, and the shared browser launches at service start. The same race exists today with `:99`. The second Xvfb starts at the same supervisord priority as the first, and `BrowserPool` relaunches on disconnect.
- An operator with a custom `NOVNC_DISPLAY_SIZE` sees automatic browsers return to the default size until the new setting is set. Listed in the change log.
- A tight standalone memory limit gets a little tighter. Measured in task 6.3.

## Migration Plan

1. Build the new image and recreate the container. Nothing is stored on a screen, so nothing moves.
2. To go back, redeploy the previous image. The three settings are ignored by it.

## Open Questions

1. This change is not yet listed in `openspec/BUILD_ORDER.md`, and this proposal may not edit that file. The owner said next version but did not name a build group or position. Task 0.1 waits for that answer.
