# Proposal

## Why

In ascend-web-hunter every headed browser draws on one virtual X screen, display `:99`. The image sets `ENV DISPLAY=:99` (`apps/ascend-web-hunter/Dockerfile` line 76), `x11vnc` shows that same screen to the human (`supervisord.conf` line 14), and fluxbox manages it (line 19). The automatic browser tiers launch headed by default and inherit that `DISPLAY`, so while a human solves a captcha or types a login in a NoVNC window, an automatic read can open a browser window on the same screen, cover the human's window, and take focus. Keys the human types can then land in the wrong browser. The owner decided on 2026-11-08 to save this for the next version ("50. leave it for next version - save as openspec").

## What Changes

- The container runs a second virtual X screen, by default `:98`, with its own fluxbox. No `x11vnc`, no websockify and no port is attached to it, so nobody can view it.
- The automatic browser tiers (`4-playwright_stealth` with its shared browser process, `4a-patchright`, `4b-camoufox`, `5-crawlee_adaptive`) and the screenshots and crawl jobs that use them draw on that second screen. They stay headed, with the same `PLAYWRIGHT_HEADLESS` default, so what a site can detect does not change.
- The NoVNC windows (`6-novnc`, the one launch in `_run_window` of `novnc_strategy.py`, also used by `POST /api/v2/web/session/establish`) stay on `:99`, and they become the only windows on the screen the human sees.
- The service process gets the second screen as its own `DISPLAY`, and only the NoVNC launch names the human screen. A browser launch added later therefore lands on the invisible screen unless someone deliberately names the human one.
- Three new settings: `NOVNC_DISPLAY`, `AUTOMATIC_BROWSER_DISPLAY`, `AUTOMATIC_BROWSER_DISPLAY_SIZE`. By the repository sync rule they go into the root `.env.example`, `apps/ascend-web-hunter/deploy-standalone/.env.example` and the configuration table of `apps/ascend-web-hunter/deploy-standalone/README.md`, and into both compose files.
- The service refuses to start when the two screens are the same, when only one is set, or when a value is malformed.
- The startup banner gains one line for the automatic screen. The existing `NoVNC display` line keeps its format, because spec 20 parses it.
- Cost: two more long-running processes per container (one Xvfb, one fluxbox), measured in `tasks.md` before any figure is written down.

No HTTP or MCP field changes. No breaking change for a caller. An operator who changed `NOVNC_DISPLAY_SIZE` from its default sees automatic browsers go back to the default size until `AUTOMATIC_BROWSER_DISPLAY_SIZE` is set too (see design D4).

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `web-search-intervention-display`: the screen the human sees carries only intervention windows, no viewer can reach the automatic screen, and the two screens are separate settings that cannot name the same screen.
- `web-search-antibot-evasion`: the automatic browser tiers keep their headed posture and their screen shape when they move to their own screen.

## Impact

- Container: `apps/ascend-web-hunter/Dockerfile`, `apps/ascend-web-hunter/supervisord.conf`.
- Code: `apps/ascend-web-hunter/src/config/config.py`, `src/config/startup_banner.py`, `src/reader/strategies/novnc_strategy.py`. The four automatic tier files do not change (design D1).
- Tests: `tests/config/`, `tests/runtime/test_supervisord.py`, `tests/reader/strategies/`, one new test under `tests/integration/`, and one new development dependency to list X windows (design D9).
- Compose and settings: `compose.ascend-web-hunter.yaml`, `apps/ascend-web-hunter/deploy-standalone/compose.yaml`, root `.env.example`, `apps/ascend-web-hunter/deploy-standalone/.env.example`.
- Documents: `apps/ascend-web-hunter/deploy-standalone/README.md`, `apps/ascend-web-hunter/docs/configuration.md`, `apps/ascend-web-hunter/AGENTS.md`, `apps/ascend-web-hunter/README.md`, `apps/ascend-web-hunter/docs/architecture/arc42/07-deployment-view.md`, an amendment of `apps/ascend-web-hunter/docs/architecture/decisions/ADR-013-concurrent-human-intervention-windows.md`, `apps/ascend-web-hunter/CHANGELOG.md`.
- Memory: both compose limits stay as they are unless the measurement of task 6.3 says otherwise. The standalone limit of 2560M is the tight one.
- Overlaps with `scale-web-hunter-across-containers` in the same compose and `.env.example` blocks. Each copy simply holds its own two screens.

## Relevant Skills

- `/python-patterns` for the settings, the validators and the NoVNC launch
- `/docker-patterns` for the Dockerfile, supervisord and the compose settings
- `/security-review` for what the remote viewer can reach and for the operator-supplied display values
- `/tdd-workflow` for the failing test that comes first
- `/e2e-runbooks` for the regression of specs 7, 18, 19, 20 and 22
- `/architecture-decision-records` for the amendment of ADR-013
- `/markdown-writer` for the deploy-standalone README and `apps/ascend-web-hunter/AGENTS.md`
