Every command runs from `apps/ascend-web-hunter/` through that module's own virtual environment
(`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Linux and macOS), never the system Python. The gate is
`--cov=src --cov-branch --cov-fail-under=100`, so every branch added below needs a test before the suite goes green.

Sections 1 to 9 are the implementation and can be done in order. Section 10 is documentation and section 11 is the
e2e suite, both of which need the implementation first. Section 12 is live verification and it gates calling the
change done.

## 1. Configuration

- [ ] 1.1 Add `NOVNC_MAX_CONCURRENT_FLOWS`, `NOVNC_WINDOW_WIDTH_PX`, `NOVNC_WINDOW_HEIGHT_PX`,
      `NOVNC_WINDOW_CASCADE_OFFSET_PX`, `NOVNC_DISPLAY_WIDTH_PX`, `NOVNC_DISPLAY_HEIGHT_PX`,
      `NOVNC_FLOW_LEASE_GRACE_SECONDS`, `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS`, `NOVNC_FLOW_CANCEL_GRACE_SECONDS` and
      `NOVNC_BUSY_RETRY_AFTER_SECONDS` to `src/config/config.py`, each with a `Field` carrying its default, its
      constraint and a description. Defaults are the table in `design.md`. Verify with a case per setting in
      `tests/config/test_config.py` covering the default, a valid override and a rejected out-of-range value.
- [ ] 1.2 Add a model validator rejecting a window larger than the display on either axis, and a constraint
      rejecting a cap below 1. Verify with tests asserting construction fails and that the message names both the
      window field and the display field it exceeded.
- [ ] 1.3 Delete `_NOVNC_LOCK_LEASE_GRACE_SECONDS` from `novnc_strategy.py` and `_NOVNC_BUSY_RETRY_AFTER_SECONDS`
      from `exception_handlers.py`, replacing both with the settings. Verify by grepping `src/` for both names and
      getting no matches, and by a test asserting the handler's `Retry-After` header follows the setting when it is
      patched.

## 2. Window layout

- [ ] 2.1 Create `src/reader/novnc/__init__.py` and `src/reader/novnc/window_layout.py` with a `WindowRect` value
      object and a pure `rect_for_slot(slot)` implementing the wrapping cascade from `design.md` Decision 5. Verify
      with `tests/reader/novnc/test_window_layout.py` asserting, for slot 0 through the cap and for one slot past
      it, that the rectangle is fully inside the display on both axes, that two different slots up to the cap give
      two different positions, and that the size is constant.
- [ ] 2.2 Add a test at a deliberately extreme cap (64) proving the modulus keeps every slot on screen. Verify the
      test fails if the modulus is removed, by asserting the exact boundary slot rather than a range.

## 3. The flow registry

- [ ] 3.1 Promote `CookieManager._get_domain` to a module-level `registrable_domain(url)` in `cookie_manager.py`,
      with the static method delegating to it, and replace the two `# noqa: SLF001` call sites for it in
      `session_manager.py` and `rest_endpoints.py` with the public function. Verify the existing cookie manager
      tests pass unchanged and add a test asserting the function and the method return the same value for a host
      with a subdomain, a bare host, a host with a port and a malformed input.
- [ ] 3.2 Create `src/reader/novnc/flow_registry.py` with `NoVNCFlow` and `NoVNCFlowRegistry` per `design.md`
      Decision 1, plus the module-level `novnc_flow_registry` instance. Verify with
      `tests/reader/novnc/test_flow_registry.py`: reserve takes the lowest free slot, reserve past the cap raises
      `NoVNCFlowBusyException`, release frees the slot for reuse, release of an unknown identifier is a no-op,
      `find` returns a live flow for a matching key and `None` otherwise, and `active()` is ordered by start time.
- [ ] 3.3 Implement `sweep()` so an expired lease cancels that flow's task, drops its record and frees its slot,
      and so a flow whose lease has not expired is untouched. Verify with a test that shifts one flow's
      `started_at` past its lease, asserts only that flow's task was cancelled, and asserts a sibling's slot,
      record and task are unaffected.
- [ ] 3.4 Implement `shutdown()` so it cancels every live flow and waits at most `NOVNC_FLOW_CANCEL_GRACE_SECONDS`
      in total. Verify with a test using one monitor double that finishes on cancel and one that never does,
      asserting the call returns inside the grace and that both slots are free afterwards.
- [ ] 3.5 Assert the atomicity argument rather than trusting it: add a test that inspects every public mutating
      method of the registry and fails if any is a coroutine function. Verify the test fails when one is made
      `async`.

## 4. The strategy

- [ ] 4.1 Rewrite `NoVNCStrategy.get_html` to compute the flow key from `registrable_domain(url)` and the effective
      profile, call `registry.find(key)` and, on a hit, raise `HumanInterventionRequiredException` carrying the
      existing flow's `vnc_url` and `flow_id` with `joined=True`, without launching anything. Verify with a test
      asserting a second call for the same domain and profile produces no second `chromium.launch`, no second
      monitor task, and the same `flow_id` and `vnc_url` as the first.
- [ ] 4.2 On a miss, reserve a slot, resolve the VNC URL, create the monitor task, attach it, and raise. Verify with
      a test asserting a failed VNC resolution releases the slot before the exception propagates and leaves the
      registry empty.
- [ ] 4.3 Assert the cap path end to end from the strategy: with the cap patched to 2, two distinct domains each get
      a window and the third raises `NoVNCFlowBusyException` carrying `active_flows=2` and `max_concurrent_flows=2`.
      Verify in the rewritten `tests/reader/strategies/test_novnc_concurrency.py`.
- [ ] 4.4 Delete `_NoVNCFlowLock`, `_novnc_flow_lock`, `_active_monitor_tasks` and `_CDP_REMOTE_DEBUGGING_PORT`, and
      delete `tests/reader/strategies/test_novnc_flow_lock.py`. Verify by grepping `src/` and `tests/` for each of
      the four names and getting no matches, and by the suite still passing the coverage gate.

## 5. The monitor

- [ ] 5.1 Change `_monitor_for_cookies` to take a `NoVNCFlow` and to launch with
      `--remote-debugging-port=0`, `--remote-debugging-address=127.0.0.1` and the flow's own window position and
      size. Verify with a test capturing the launch arguments of two concurrent flows and asserting neither carries
      `9222`, both carry port `0`, and their `--window-position` values differ.
- [ ] 5.2 Make the `finally` close only this flow's browser and release only this flow's slot, each wrapped so a
      failure in one cannot skip the other. Verify with a test where `browser.close()` raises, asserting the slot is
      still released and the outcome metric is still recorded.
- [ ] 5.3 Catch `asyncio.CancelledError` explicitly: record the outcome `cancelled`, close the browser, release the
      slot, re-raise. Verify with a test cancelling a running monitor and asserting the browser was closed, the slot
      freed, the `cancelled` outcome recorded, and the `CancelledError` observed by the awaiting caller.
- [ ] 5.4 Prove failure isolation: with two flows in flight, make one raise inside its poll loop and assert the
      other's task is still running, its browser is still open, its slot is still held, and its session record is
      untouched. Verify in `tests/reader/strategies/test_novnc_concurrency.py`.
- [ ] 5.5 Prove a capture survives a later failure of its own flow: save a state, then make the monitor raise, and
      assert the record written before the failure is still present and unmodified. Verify no code path in the
      monitor calls `clear_session` by asserting it against a mocked cookie manager across all four outcomes.

## 6. Lifecycle

- [ ] 6.1 Start a periodic sweeper task in `create_app`'s lifespan at `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS`, and
      cancel it in the `finally`. Verify with a test driving the lifespan with a patched short interval, asserting
      the sweep ran at least twice and that the task is cancelled on exit.
- [ ] 6.2 Call `registry.shutdown()` in the lifespan `finally`, before `browser_pool.stop()`. Verify with a test
      asserting a live flow's monitor is cancelled and its browser closed when the lifespan exits, and that the
      ordering against `browser_pool.stop()` is the one specified.
- [ ] 6.3 Assert the sweeper never raises out of its own loop: make one sweep raise and assert the task is still
      running afterwards and the exception was logged. Verify the test fails if the guard is removed.

## 7. The contract

- [ ] 7.1 Add `flow_id`, `joined` and `window` to `HumanInterventionRequiredException` and to both places the 428
      body is built: `human_intervention_exception_handler` and `mcp_server.web_read`. Verify with tests asserting
      the four pre-existing keys are byte-identical to today for the same inputs, and that the three new keys are
      present with the values from the flow.
- [ ] 7.2 Add `active_flows`, `max_concurrent_flows` and `flows` to `NoVNCFlowBusyException` and to both places the
      409 body is built, and populate `holder_url` and `holder_profile` from the oldest live flow. Verify with a
      test at a cap of 3 asserting `holder_url` names the oldest flow and `flows` lists all three with a positive
      `expires_in_seconds` each.
- [ ] 7.3 Add `GET /api/v2/session/interventions` to `rest_endpoints.py` and `session_interventions` to
      `mcp_server.py`, both returning the envelope in `design.md` Decision 9. Verify with tests asserting an empty
      registry returns `active: 0` with an empty list, that a populated one lists each flow once with its slot and
      window, that the response carries no cookie, storage-state or page content, and that both surfaces return the
      same payload for the same registry state.
- [ ] 7.4 Update the MCP tool docstrings for `web_read` and `session_establish` so an agent is told to surface the
      window's slot alongside the `vnc_url` when several windows may be open. Verify the docstrings still name
      `vnc_url` and `status` exactly as ADR-003 requires, with a test asserting both substrings are present.
- [ ] 7.5 Update the OpenAPI examples `_CAPTCHA_EXAMPLE` and `_LOGIN_EXAMPLE` in `rest_endpoints.py`, and add a
      busy example. Verify by asserting each example validates against the shape the handler actually produces,
      rather than by eye.

## 8. Observability

- [ ] 8.1 Add `NOVNC_ACTIVE_FLOWS` (Gauge), `NOVNC_FLOWS_STARTED_TOTAL`, `NOVNC_FLOW_JOINED_TOTAL` and
      `NOVNC_FLOWS_RECLAIMED_TOTAL` to `src/observability/metrics.py`, with the labels in `design.md`. Verify with
      cases in `tests/observability/test_metrics.py` asserting each name, type and label set.
- [ ] 8.2 Wire them: reserve increments started and sets the gauge, join increments joined and does not touch the
      gauge, the cap path increments the existing `NOVNC_FLOW_BUSY_TOTAL`, and each reclamation increments with its
      own reason. Verify with a test that runs one of each path and asserts the exact counter deltas, including
      that join leaves the gauge alone.
- [ ] 8.3 Add `cancelled` as an outcome on the `6-novnc-monitor` label of `STRATEGY_ATTEMPTS_TOTAL`. Verify with a
      test asserting all four outcomes are reachable and that each maps to the path it names.
- [ ] 8.4 Put `flow_id` and `slot` on every registry, strategy and monitor log line, and the request identifier on
      the reserve line. Verify with a caplog test asserting each of those lines carries the identifier, and that no
      line carries a cookie value or a storage-state fragment.

## 9. Proof that F22 stays closed

- [ ] 9.1 Add `tests/reader/strategies/test_novnc_f22_regression.py` driving two concurrent flows for two different
      domains through the real `get_html` path with a Playwright double. Assert two distinct `chromium.launch`
      calls, that no two launches share a `--remote-debugging-port` value, that no launch carries `9222`, and that
      the two `--window-position` values differ. Verify the test fails if the fixed port is reintroduced.
- [ ] 9.2 In the same file, assert the capture half of F22: both flows resolve, and two session records exist under
      two distinct `session:{domain}:{profile}` keys with the right content in each. Verify the test fails if both
      monitors are pointed at one key.
- [ ] 9.3 Run the full gate and record the figure:
      `.venv/Scripts/pytest.exe --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`. Verify it
      passes at 100 percent branch coverage with no `# pragma: no cover` and no `# noqa` added anywhere in this
      change.
- [ ] 9.4 Run `.venv/Scripts/ruff.exe check .` and `.venv/Scripts/mypy.exe src`. Verify both are clean, with no
      suppression added.

## 10. Documentation and decisions

- [ ] 10.1 Add the ten settings to the tables in `apps/ascend-web-hunter/AGENTS.md`, `README.md` and
      `docs/configuration.md`, with `NOVNC_MAX_CONCURRENT_FLOWS` documented as a memory constraint and not only a
      display one. Verify each of the ten names appears in all three files and that no stale reference to the
      single-flow behaviour remains, by grepping for "only one" and "one at a time" across the module's docs.
- [ ] 10.2 Write `docs/architecture/decisions/ADR-009-concurrent-human-intervention-windows.md` in the existing
      ADR format: the concurrency model, the per-flow browser and ephemeral CDP port, the cascade layout, the join
      rule, and the widened unauthenticated VNC surface with the recommendation to set `VNC_PASSWORD`. Include the
      rejected alternatives from `design.md` Decisions 4 and 5 with their reasons. Verify the file follows the
      structure of ADR-003 and ADR-008 and is added to the decisions `README.md` index.
- [ ] 10.3 Amend ADR-003 rather than superseding it: mark the single-flow paragraph and the
      `--remote-debugging-port=9222` security bullet as superseded by ADR-009, with the date, and leave the rest of
      the record intact. Verify ADR-003's status line and its other content are unchanged, and that the risk it
      recorded ("No cap on concurrent tasks exists today") now points at the setting that answers it.
- [ ] 10.4 Add one evidence line to F22 in `docs/DEFECT_REGISTER.md` recording that the collision it names cannot
      recur under the per-flow model, naming this change and the regression test in task 9.1. Verify F22's status
      is not changed and no other row is touched.

## 11. End-to-end spec 7

- [ ] 11.1 In `apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md`, state that a
      `409 novnc_busy` on a best-effort row is a FAIL unless the run has genuinely saturated
      `NOVNC_MAX_CONCURRENT_FLOWS`, and add a prerequisite that the matrix runs with a cap of at least 4 so Part 3's
      window cannot starve it. Name rows n, o, p and t and the 2026-09-10 run as the reason the rule exists. Verify
      by re-reading the Contract section and confirming the accept-set and the new rule do not contradict each other.
- [ ] 11.2 Update the same file's Concurrency section: Part 3's human solve no longer blocks Part 1, so the note that
      it must run first stands only for the human-forwarding reason, not for a shared-browser reason. Verify the
      section still states what the test mutates and what it conflicts with, per the `e2e-runbooks` contract.
- [ ] 11.3 Add a gated Part 4, "Several intervention windows at once". Open four intervention flows against four
      distinct domains, assert four HTTP 428 responses with four distinct `flow_id` values and four distinct
      `window.slot` values, assert `GET /api/v2/session/interventions` reports `active: 4`, assert a fifth request
      returns 409 with `active_flows: 4`, assert a duplicate of one of the four returns 428 with `joined: true` and
      the same `flow_id`, then have the human solve exactly one window and leave the other three to time out.
      Assert the solved window's capture lands under its own session key and that the three timeouts leave it
      untouched. Verify every assertion is observable state (HTTP status, response body, a Redis key), never a log
      substring.
- [ ] 11.4 Add the matching Bruno requests under `docs/api/request/AscendAI/web-hunter/testing/`:
      `interventions-list.yml`, `intervention-window-5th-busy.yml` and `intervention-window-duplicate-join.yml`.
      Verify each runs with `bru run "<file>" --env ascend-local` against a live stack and asserts on the body
      fields the spec names.
- [ ] 11.5 Update `e2e/testing/templates/7-authenticated-realworld-scraping-tasks.template.md` with the Part 4 rows
      and the new 409 rule, so a run record carries them. Verify the template's row set matches the spec's row set
      exactly, item for item.
- [ ] 11.6 Update `e2e/README.md`'s capability matrix with the concurrent-intervention capability and its spec
      number. Verify the matrix lists it once and that the spec count in the prose still matches.

## 12. Live verification

- [ ] 12.1 Rebuild and restart the scrapper stack from the repository root against the main compose file, then
      confirm the container is running the new image. Verify with `docker compose ps ascend-web-hunter` and by
      reading the startup banner for the new settings.
- [ ] 12.2 Measure the memory cost of the default cap, which Open Question 1 in `design.md` leaves open. Open four
      concurrent flows, record container memory with `docker stats` at rest, at one flow and at four, and record the
      per-flow increment. Verify the recorded figure is written into `design.md`'s configuration table, and either
      confirm the default of 4 or lower it there and in `config.py` in the same edit.
- [ ] 12.3 Drive the Part 4 sequence by hand once before running it as a spec: four windows open, look at the NoVNC
      display and confirm four windows are visible with reachable title bars, clear them out of order, and confirm
      each clearance frees exactly one slot. Verify against
      `GET /api/v2/session/interventions` between each step rather than by impression.
- [ ] 12.4 Prove the lease and the sweeper live: open a flow, kill its Chromium from inside the container, and
      confirm the slot is freed and the window gone within one sweep interval plus the grace, without any further
      request being made. Verify with the interventions listing and with `docker exec ... ps`.
- [ ] 12.5 Re-run e2e spec 7 in full, with Part 3 on the main session and Part 1 fanned out, and confirm rows n, o,
      p and t return a terminal verdict rather than a 409. Verify by the run record written under
      `e2e/testing/runs/`, and attach it to this change.
