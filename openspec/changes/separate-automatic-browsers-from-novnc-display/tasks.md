Build order: not placed yet, see task 0.1. Load the skills of the proposal's Relevant Skills section first. Every Python command runs from `apps/ascend-web-hunter` through its own `.venv` as `python -m <tool>` (`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Linux and macOS), never the system Python. Docker build, up, run, stop and restart are the owner's to approve, one line each, before they run. Read-only commands (`docker compose config`, `ps`, `logs`, `inspect`, `exec ... printenv`) need no approval. Code changes are batched so the image is rebuilt once. Every throwaway container uses `--rm`, the superseded image and builder cache are pruned the same day, and `df` is reported before and after. Nothing is pushed and no workflow is run. Nothing is committed until the owner says to commit.

## 0. Preconditions

- [ ] 0.1 Ask the owner for the build group and position of this change, add it to `openspec/BUILD_ORDER.md`, and write the answer as the first line of this file. Verify: the row in `openspec/BUILD_ORDER.md` matches the line here.
- [ ] 0.2 Confirm whether `scale-web-hunter-across-containers` is applied, because it edits the same compose and `.env.example` blocks. Verify: the result is recorded in `design.md` Context.

## 1. Facts read before any edit

- [ ] 1.1 Read again every file and line named in `design.md` Context, and correct any line number or name that moved. Verify: `git grep -n -E "ENV DISPLAY|-display :99|Xvfb :99" -- apps/ascend-web-hunter` lists only the lines this change will edit.
- [ ] 1.2 Confirm the Camoufox and Playwright facts of `design.md` Context against the pinned versions in `apps/ascend-web-hunter/pyproject.toml`. Verify: each fact has its file and line in `design.md`.

## 2. Failing test first

- [ ] 2.1 Add `python-xlib`, at a frozen version read from its package index, to the `dev` extra of `apps/ascend-web-hunter/pyproject.toml`. Write `apps/ascend-web-hunter/tests/integration/test_automatic_browser_display.py` by design D9: two private Xvfb servers through `-displayfd` with a fluxbox on each, one headed NoVNC window on the human screen through the real `_run_window`, then a real read through each of `4-playwright_stealth`, `4a-patchright`, `4b-camoufox` and `5-crawlee_adaptive` with `DISPLAY` on the other screen. Stub the session store and the flow registry as `tests/integration/test_novnc_window_teardown.py` lines 196 to 199 do, but keep the launch headed. Serve the page from a local `ThreadingHTTPServer` with `ALLOWED_PRIVATE_HOSTS` patched as `tests/integration/test_crawlee_blocked_status.py` does. Assert that the top-level windows of the human screen and its focused window are the same before, during and after each read, that the automatic screen did gain a window during each read (so the test cannot pass with no browser opened), and that the NoVNC window is on the human screen. A control case runs one read with `DISPLAY` on the human screen and asserts a window appears there, which proves today's defect. Verify: with `NOVNC_DISPLAY` not yet wired, the NoVNC window assertion fails, and the control case passes.

## 3. Container

- [ ] 3.1 Edit `apps/ascend-web-hunter/supervisord.conf` by design D1 and D3. The first Xvfb, x11vnc and fluxbox read `%(ENV_NOVNC_DISPLAY)s`, a new `xvfb-automatic` program has the same arguments as the first with `%(ENV_AUTOMATIC_BROWSER_DISPLAY)s` and `%(ENV_AUTOMATIC_BROWSER_DISPLAY_SIZE)s` at priority 10, a new `fluxbox-automatic` program runs at priority 25, and the uvicorn program gets `environment=DISPLAY="%(ENV_AUTOMATIC_BROWSER_DISPLAY)s"`. Verify: tests of task 5.3 pass, and on a fresh container both fluxbox processes stay up (`docker compose logs` read-only, with `ps` in the container).
- [ ] 3.2 Check that no other program needs `DISPLAY` from the image. Verify: `git grep -n "DISPLAY" -- apps/ascend-web-hunter/supervisord.conf apps/ascend-web-hunter/docker-entrypoint.sh apps/ascend-web-hunter/Dockerfile` shows only intended lines.

## 4. Image, settings and code

- [ ] 4.1 In `apps/ascend-web-hunter/Dockerfile`, remove `ENV DISPLAY=:99`, and add `ENV NOVNC_DISPLAY=:99`, `ENV AUTOMATIC_BROWSER_DISPLAY=:98` and `ENV AUTOMATIC_BROWSER_DISPLAY_SIZE=1920x1080` beside `ENV NOVNC_DISPLAY_SIZE`. Verify: test of task 5.2.
- [ ] 4.2 In `apps/ascend-web-hunter/src/config/config.py`, add the three settings of design D4 and the refusals of design D5, reusing the size parsing. Verify: tests of task 5.1.
- [ ] 4.3 In `apps/ascend-web-hunter/src/reader/strategies/novnc_strategy.py`, pass `env` to the launch in `_run_window` by design D1, built by one pure function, with no `env` when `NOVNC_DISPLAY` is empty. Change no automatic tier file. Verify: tests of task 5.4, and the integration test of task 2.1 passes in full under task 6.1.
- [ ] 4.4 In `apps/ascend-web-hunter/src/config/startup_banner.py`, add the line of design D6 and leave the `NoVNC display` line as it is. Verify: test of task 5.5.

## 5. Unit tests

- [ ] 5.1 `tests/config/test_config.py`: each refusal of design D5 with the setting named in the error, both screen names empty accepted, a valid pair accepted, and the size format.
- [ ] 5.2 `tests/config/test_config.py`: the Dockerfile `ENV AUTOMATIC_BROWSER_DISPLAY_SIZE` equals the settings default, in the style of `test_dockerfile_novnc_display_size_matches_settings_default`, and the Dockerfile has no `ENV DISPLAY=` line.
- [ ] 5.3 `tests/runtime/test_supervisord.py`: exactly one x11vnc program, naming the human screen variable, two Xvfb programs with equal arguments other than the screen and the size, a fluxbox per screen, and `DISPLAY` of the uvicorn program set to the automatic screen variable.
- [ ] 5.4 Under `tests/reader/strategies/`: the NoVNC launch gets the human screen with every other variable of the process environment kept, gets no `env` when `NOVNC_DISPLAY` is empty, and leaves `os.environ` unchanged. The launches of the four automatic tiers pass no `env` and no display.
- [ ] 5.5 `tests/config/test_startup_banner.py`: the new line carries the name and the size, and the existing `NoVNC display` line still reads as the size only.
- [ ] 5.6 Run the full unit suite with the 100 percent branch coverage gate. Verify: this command exits 0.

```bash
.venv/bin/python -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100
```

- [ ] 5.7 Run `.venv/bin/python -m ruff check .`, `.venv/bin/python -m ruff format --check .` and `.venv/bin/python -m mypy src tests`, the same three the `ascend-web-hunter` job of `.github/workflows/ci.yaml` runs. Verify: each exits 0.

## 6. Integration tests

- [ ] 6.1 With the owner's approval, build the image once, then run `tests/integration/test_automatic_browser_display.py` in a throwaway container by design D9. Verify: the output shows it passed, not skipped. An automatic browser read opened no window on the human screen while a NoVNC window was open, for all four tiers.
- [ ] 6.2 Run the existing integration suite. Verify: this command exits 0, on a machine with Redis at `REDIS_URL` and with the browsers installed.

```bash
.venv/bin/python -m pytest tests/integration -q --no-cov
```

- [ ] 6.3 With the owner's approval, on the old image and on the image of task 6.1, measure the cost of design D8 in the running container: memory of each Xvfb and fluxbox with `ps`, the count of `dbus-daemon` processes, idle CPU with `docker stats`, each with no flow open and with four flows open. Verify: the numbers replace the unmeasured statement in design D8, with the command and the output recorded.

## 7. Compose, settings files and the sync rule

- [ ] 7.1 Add `NOVNC_DISPLAY=${NOVNC_DISPLAY:-:99}`, `AUTOMATIC_BROWSER_DISPLAY=${AUTOMATIC_BROWSER_DISPLAY:-:98}` and `AUTOMATIC_BROWSER_DISPLAY_SIZE=${AUTOMATIC_BROWSER_DISPLAY_SIZE:-1920x1080}` to the `ascend-web-hunter` environment of `compose.ascend-web-hunter.yaml` and of `apps/ascend-web-hunter/deploy-standalone/compose.yaml`. Verify: `docker compose config` on both files shows the three values.
- [ ] 7.2 Add the same three as commented lines, each with a comment in the style of the `NOVNC_DISPLAY_SIZE` line, to the root `.env.example` and to `apps/ascend-web-hunter/deploy-standalone/.env.example`. Verify: `diff` of the three-line blocks shows no difference.
- [ ] 7.3 Add one row per setting to the configuration table of `apps/ascend-web-hunter/deploy-standalone/README.md`, and change the `NOVNC_DISPLAY_SIZE` row from the shared display to the screen the human sees. If task 6.3 changes the memory sums, update its limits section. Same commit as tasks 7.1 and 7.2.

## 8. Documents

- [ ] 8.1 `apps/ascend-web-hunter/docs/configuration.md`: one row per setting, each ending "Added by `separate-automatic-browsers-from-novnc-display`.", and correct the `NOVNC_DISPLAY_SIZE` and `PLAYWRIGHT_HEADLESS` text.
- [ ] 8.2 `apps/ascend-web-hunter/AGENTS.md` environment list, `apps/ascend-web-hunter/README.md` table, and `apps/ascend-web-hunter/docs/architecture/arc42/07-deployment-view.md` with both screens.
- [ ] 8.3 Amend `apps/ascend-web-hunter/docs/architecture/decisions/ADR-013-concurrent-human-intervention-windows.md` with design D1, D2 and D3.
- [ ] 8.4 `apps/ascend-web-hunter/CHANGELOG.md` entry with the version of design D10 and the migration note of design D4 about a custom `NOVNC_DISPLAY_SIZE`.

## 9. End-to-end regression and the live check

- [ ] 9.1 Before any end-to-end run, ask the owner which scenario or service suite from `docs/E2E_RUN_SCENARIOS.md` to use, as the root `AGENTS.md` requires. Specs 7 and 22 need live sites, and spec 22 needs a human at the keyboard.
- [ ] 9.2 Run these specs under `apps/ascend-web-hunter/e2e/testing/` through the `e2e-runner` subagent and record each verdict: `7-authenticated-realworld-scraping-test.md`, `18-tier-ladder-and-guard-test.md`, `19-challenge-verdicts-test.md`, `20-concurrent-interventions-test.md`, `22-human-login-reuse-test.md`. Verify: each verdict is pass, with spec 7's best-effort rows recorded and compared to the last run.
- [ ] 9.3 Live check with the owner's approval, during step 2 of spec 20 with four windows open: run reads through each automatic tier against the fake site. List `DISPLAY` of every browser process from `/proc/<pid>/environ` with a read-only `docker compose exec`. Verify: the browser processes on the human screen are the four NoVNC ones and every other browser process is on the automatic screen. The command and output are recorded, and the owner confirms over NoVNC that no other window appeared.

## 10. Final review

- [ ] 10.1 Review every changed file against `design.md` and the repository rules. Report what passed and what did not. Verify: `git status --short` lists only the files this change names.
- [ ] 10.2 Clean up: no `Exited` test container and no orphan network remain, the superseded image and builder cache are pruned, and `df` before and after is reported.
