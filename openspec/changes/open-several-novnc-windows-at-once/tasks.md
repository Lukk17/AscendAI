Every command runs from `apps/ascend-web-hunter/` through that module's own virtual environment
(`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Linux and macOS), never the system Python. The gate is
`--cov=src --cov-branch --cov-fail-under=100`, so every branch added below needs a test before the suite goes green.

Sections 1 to 9 are the implementation and can be done in order. Section 10 is documentation and section 11 is the
e2e suite, both of which need the implementation first. Section 12 is live verification and it gates calling the
change done.

## 1. Configuration

- [ ] 1.1 Add these settings to `src/config/config.py`, each with a `Field` carrying its default, its constraint and a
      description, with the defaults of the configuration table in `design.md` (owner rule 98 of 2026-10-08, every
      value with a default is a setting): `NOVNC_MAX_CONCURRENT_FLOWS` (default 4, minimum 1, described as a per
      container memory constraint), `NOVNC_DISPLAY_SIZE` (default `1920x1080`, the value the Dockerfile sets for the
      image, task 1.4), `NOVNC_WINDOW_WIDTH_PX` (default 1280, minimum 1), `NOVNC_WINDOW_HEIGHT_PX` (default 800,
      minimum 1), `NOVNC_WINDOW_CASCADE_OFFSET_PX` (default 48, minimum 1), `NOVNC_FLOW_LEASE_GRACE_SECONDS` (default
      30.0, above 0), `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS` (default 30.0, above 0), `NOVNC_FLOW_CANCEL_GRACE_SECONDS`
      (default 10.0, above 0) and `NOVNC_BUSY_RETRY_AFTER_SECONDS` (default 30, minimum 1). No value of the
      configuration table stays a module constant. Verify with cases in `tests/config/test_config.py` covering each
      default, a valid override and a rejected value below its minimum, and `NOVNC_DISPLAY_SIZE` set to a malformed
      value.
- [ ] 1.2 Add a model validator that rejects a `NOVNC_DISPLAY_SIZE` that does not read `<width>x<height>`, and a
      display smaller than `NOVNC_WINDOW_WIDTH_PX` by `NOVNC_WINDOW_HEIGHT_PX` on either axis. Verify with tests
      asserting construction fails and that the message names the display size and the window setting it is smaller
      than.
- [ ] 1.3 Replace `_NOVNC_LOCK_LEASE_GRACE_SECONDS` in `novnc_strategy.py` by the setting
      `NOVNC_FLOW_LEASE_GRACE_SECONDS`, which the registry reads, and `_NOVNC_BUSY_RETRY_AFTER_SECONDS` in
      `exception_handlers.py` by the setting `NOVNC_BUSY_RETRY_AFTER_SECONDS`, which the `novnc_busy` registry entry
      reads for its `Retry-After` header, both with today's value as the default (owner rule 98 of 2026-10-08). Verify
      by grepping `src/` for both old names with no match, and by tests asserting the handler's `Retry-After` header is
      30 by default and follows an override of the setting.
- [ ] 1.4 Keep `ENV NOVNC_DISPLAY_SIZE=1920x1080` in `apps/ascend-web-hunter/Dockerfile` as the image's own value for
      a container started without compose, and start Xvfb in `supervisord.conf` with
      `-screen 0 %(ENV_NOVNC_DISPLAY_SIZE)sx24`, so Xvfb and the service read the one variable that compose sets for
      both (task 1.6, owner answer 93 and owner rule 98 of 2026-10-08). Verify that the image builds, that a search of
      `supervisord.conf` finds no `1920` and no `1080`, that in `src/` only the default of `NOVNC_DISPLAY_SIZE` in
      `config.py` holds them, that a test in `tests/config/test_config.py` asserts the Dockerfile `ENV` value equals the
      `Settings` default, and that the startup banner prints the display size the service read.
- [ ] 1.5 Add `NOVNC_PUBLIC_URL` to `src/config/config.py` (design Decision 11, owner answers 94.4 and 95.1 of
      2026-10-08): optional, no default, one base address shared by every ascend-web-hunter container, and when set an
      absolute `http` or `https` URL with no path, refused at settings construction otherwise with the setting named.
      Pass it through in the `ascend-web-hunter` service of `compose.ascend-web-hunter.yaml` and of
      `deploy-standalone/compose.yaml` as `NOVNC_PUBLIC_URL=${NOVNC_PUBLIC_URL:-}`, publish no NoVNC port on either, and
      add `NOVNC_PUBLIC_URL=` with a one-line comment (the address of the web-hunter edge proxy that
      `scale-web-hunter-across-containers` adds later, shared by every container, empty for one container, owner answer
      96 of 2026-10-08) to the root `.env.example`, `deploy-standalone/.env.example` and the configuration
      table of `deploy-standalone/README.md` in the same commit (the sync rule). Verify with cases in
      `tests/config/test_config.py` (unset, a valid URL, a relative value refused, a value with a path refused) and
      `docker compose config` (read only) showing the variable empty on the service and no published port 7900.
- [ ] 1.6 Pass every setting of task 1.1 through the `ascend-web-hunter` service of `compose.ascend-web-hunter.yaml` and
      of `deploy-standalone/compose.yaml` as `- <NAME>=${<NAME>:-<default>}` with the default of task 1.1, for example
      `- NOVNC_MAX_CONCURRENT_FLOWS=${NOVNC_MAX_CONCURRENT_FLOWS:-4}` and
      `- NOVNC_DISPLAY_SIZE=${NOVNC_DISPLAY_SIZE:-1920x1080}` (owner rule 98 of 2026-10-08). Under the sync rule, in the
      same commit as task 1.1, add each one as a commented line with its default and a one-line comment, in the form
      of `# RATE_LIMIT_DEFAULT=1200/minute`, to the root `.env.example` and `deploy-standalone/.env.example`, and a row
      (Required `No`, the default named) to the configuration table of `deploy-standalone/README.md`. Verify with
      `docker compose config` (read only) from the repository root and in `deploy-standalone/` showing each variable
      with its default on the service, the same command with `NOVNC_MAX_CONCURRENT_FLOWS=2` set in the shell of that
      one command showing the override, and a search of both `.env.example` files and the bundle README finding each
      name once.

## 2. Window layout

- [ ] 2.1 Create `src/reader/novnc/__init__.py` and `src/reader/novnc/window_layout.py` with a `WindowRect` value
      object carrying the slot and the rectangle, and a pure `rect_for_slot(slot, display_size, window_size,
      cascade_offset)` implementing the wrapping cascade from `design.md` Decision 5, called with the settings
      `NOVNC_DISPLAY_SIZE`, `NOVNC_WINDOW_WIDTH_PX`, `NOVNC_WINDOW_HEIGHT_PX` and `NOVNC_WINDOW_CASCADE_OFFSET_PX` of
      task 1.1 and holding no size or offset constant of its own. Verify with
      `tests/reader/novnc/test_window_layout.py` asserting, for slot 0 through the cap and for one slot past it, that
      the rectangle is fully inside the display on both axes, that two different slots up to the cap give two
      different positions, that the size is constant, and that another display size, window size and offset passed in
      are honoured.
- [ ] 2.2 Add a test at a deliberately extreme cap (64) proving the modulus keeps every slot on screen. Verify the
      test fails if the modulus is removed, by asserting the exact boundary slot rather than a range.

## 3. The flow registry

- [ ] 3.1 Key the registry on the existing public static method `CookieManager.registrable_domain(url)` in
      `src/reader/cloudflare/cookie_manager.py`. Do not add a second implementation and do not add any
      `# noqa: SLF001`. Verify with a test in `tests/reader/novnc/test_flow_registry.py` asserting that the flow key
      for a host with a subdomain, a bare host, a host with a port and a malformed input equals
      `CookieManager.registrable_domain(url)` plus the profile, and by grepping `src/` for `SLF001` with no new match.
- [ ] 3.2 Create `src/reader/novnc/flow_registry.py` with `NoVNCFlow` and `NoVNCFlowRegistry` per `design.md`
      Decision 1, plus the module-level `novnc_flow_registry` instance: the local slot pool and tasks in the process,
      and the flow record in Redis under `novnc_flow:{registrable_domain}:{profile}`, written with `SET NX PX` for the
      lease and deleted on release by a compare and delete script. Verify with
      `tests/reader/novnc/test_flow_registry.py` against a fake Redis: reserve takes the lowest free slot and writes
      the record with the lease as its expiry, reserve past the cap raises `NoVNCFlowBusyException`, release frees the
      slot and deletes the record, release of an unknown identifier is a no-op, `find` returns a live flow for a
      matching key and `None` otherwise, `active()` and `local()` are ordered by start time, and a Redis error is
      logged once as a WARNING and leaves the flow in the process only.
- [ ] 3.3 Implement `sweep()` so an expired lease cancels that flow's task, drops its record and frees its slot,
      and so a flow whose lease has not expired is untouched. Verify with a test that shifts one flow's
      `started_at` past its lease, asserts only that flow's task was cancelled, and asserts a sibling's slot,
      record and task are unaffected.
- [ ] 3.4 Implement `shutdown()` so it cancels every local flow and waits at most `NOVNC_FLOW_CANCEL_GRACE_SECONDS`
      in total. Verify with a test using one monitor double that finishes on cancel and one that never does,
      asserting the call returns inside the grace, that both slots are free and both Redis records gone afterwards,
      and that a record written by a second registry on the same fake Redis is untouched.
- [ ] 3.6 Prove the registry is safe with several containers (owner answer 87 of 2026-10-08): two registry instances
      on one fake Redis stand for two containers. Verify with tests in `tests/reader/novnc/test_flow_registry.py`
      that a flow reserved on the first is found and joined from the second with the same `flow_id`, `vnc_url` and
      `window`, that two reserves of one key started together on both produce exactly one flow and one join, that
      each instance fills its own slots up to its own cap, that `active()` on either lists the flows of both, that a
      record past its expiry is not found, and that a release of an older flow does not delete a newer record written
      for the same key.

Task 3.5 removed by owner decision 93 of 2026-10-08.

## 4. The strategy

- [ ] 4.1 Rewrite `NoVNCStrategy.get_html` to compute the flow key from `registrable_domain(url)` and the effective
      profile, call `registry.find(key)` and, on a hit, raise `HumanInterventionRequiredException` carrying the
      existing flow's `vnc_url` and `flow_id` with `joined=True`, without launching anything. Verify with a test
      asserting a second call for the same domain and profile produces no second `chromium.launch`, no second
      monitor task, and the same `flow_id` and `vnc_url` as the first.
- [ ] 4.2 On a miss, reserve a slot, resolve the VNC URL, create the monitor task, attach it, and raise. When the
      reserve loses the `SET NX` write to another request, raise the 428 of the existing flow with `joined=True`
      instead. Verify with a test asserting a failed VNC resolution releases the slot and deletes the Redis record
      before the exception propagates and leaves the registry empty, and a test asserting a lost write launches no
      browser.
- [ ] 4.3 Assert the cap path end to end from the strategy: with the cap patched to 2, two distinct domains each get
      a window and the third raises `NoVNCFlowBusyException` carrying `active_flows=2` and `max_concurrent_flows=2`.
      Verify in the rewritten `tests/reader/strategies/test_novnc_concurrency.py`.
- [ ] 4.4 Delete `_NoVNCFlowLock`, `_novnc_flow_lock`, `_active_monitor_tasks` and `_CDP_REMOTE_DEBUGGING_PORT`, and
      delete `tests/reader/strategies/test_novnc_flow_lock.py`. Verify by grepping `src/` and `tests/` for each of
      the four names and getting no matches, and by the suite still passing the coverage gate.
- [ ] 4.5 Resolve the `vnc_url` of a new flow, when `NOVNC_PUBLIC_URL` is set, as
      `<NOVNC_PUBLIC_URL>/novnc/<hostname>/vnc.html?autoconnect=true&path=novnc/<hostname>/websockify`, with
      `<hostname>` this container's own host name read from the container itself (`socket.gethostname()`, the same
      value as `HOSTNAME`), and through today's `PUBLIC_VNC_URL` resolution and the one Ngrok tunnel when it is unset
      (design Decision 11, owner answers 94.4 and 95.1 of 2026-10-08). Verify with tests: a container with
      `NOVNC_PUBLIC_URL` set writes that address, with its own host name, into the flow record without calling the
      Ngrok API, a container without it keeps today's result, and two registry instances on one fake Redis with one
      shared `NOVNC_PUBLIC_URL` and two different host names (the setup of task 3.6, the host name read through a
      seam the test replaces) give, for a flow reserved on the first, the address with the first host name in the 428
      of a join on the second, in the 409 `flows` of the second and in the listing read on the second.

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

- [ ] 6.1 Start a periodic sweeper task in `create_app`'s lifespan every `NOVNC_FLOW_SWEEP_INTERVAL_SECONDS`, sweeping
      only this process's flows and taking no Redis lock, and cancel it in the `finally`. Verify with a test driving the
      lifespan with the setting overridden to a short interval, asserting the sweep ran at least twice and that the task is cancelled on
      exit.
- [ ] 6.2 Call `registry.shutdown()` in the lifespan `finally`, before `browser_pool.stop()`. Verify with a test
      asserting a live flow's monitor is cancelled and its browser closed when the lifespan exits, and that the
      ordering against `browser_pool.stop()` is the one specified.
- [ ] 6.3 Assert the sweeper never raises out of its own loop: make one sweep raise and assert the task is still
      running afterwards and the exception was logged. Verify the test fails if the guard is removed.

## 7. The contract

- [ ] 7.1 Add `flow_id`, `joined` and `window` to `HumanInterventionRequiredException`, to the extension members of
      the `human_intervention_required` entry of the service's `ErrorRegistry` (the REST problem body that
      `add-ascend-python-common` builds), and to the status object `mcp_server.web_read` returns. Verify with tests
      asserting the pre-existing members (`code`, `detail`, `intervention_type`, `vnc_url` on REST, `status`,
      `intervention_type`, `vnc_url`, `message` on MCP) are byte-identical to before this change for the same
      inputs, and that the three new keys are present with the values from the flow.
- [ ] 7.2 Add `active_flows`, `max_concurrent_flows` and `flows` to `NoVNCFlowBusyException`, to the extension
      members of the `novnc_busy` registry entry (REST problem body) and to the two MCP status objects, and populate
      them and `holder_url` and `holder_profile` from the local flows of the refusing container, oldest first. Each
      entry of `flows` is the flow shape of `design.md` Decision 9, the same one the listing returns. Verify with a
      test at a cap of 3 asserting `holder_url` names the oldest flow and `flows` lists all three in the flow shape
      with a positive `expires_in_seconds` each.
- [ ] 7.3 Add `GET /api/v2/session/interventions` to `rest_endpoints.py` and `session_interventions` to
      `mcp_server.py`, both returning the envelope in `design.md` Decision 9 from `active()`, so the flows of every
      container are listed. Verify with tests asserting an empty registry returns `active_flows: 0` with an empty
      list, that a populated one lists each flow once in the flow shape with its window and slot, that a flow written
      by a second registry on the same fake Redis is listed, that the response carries no cookie, storage-state or
      page content, and that both surfaces return the same payload for the same registry state.
- [ ] 7.4 Update the MCP tool docstrings for `web_read` and `session_establish` so an agent is told to surface the
      window's slot alongside the `vnc_url` when several windows may be open. Verify the docstrings still name
      `vnc_url` and `status` exactly as ADR-003 requires, with a test asserting both substrings are present.
- [ ] 7.5 Update the OpenAPI examples `_CAPTCHA_EXAMPLE` and `_LOGIN_EXAMPLE` in `rest_endpoints.py` to the problem
      body of `design.md` Decision 9, and add a busy example in the same shape. Verify by asserting each example validates against the shape the handler actually produces,
      rather than by eye.

## 8. Observability

- [ ] 8.1 Add `NOVNC_ACTIVE_FLOWS` (Gauge) and `NOVNC_FLOWS_RECLAIMED_TOTAL` to `src/observability/metrics.py`, and
      the label `joined` to the existing `HUMAN_INTERVENTION_TOTAL`, with the labels in `design.md`. No counter of
      flows started or joined is added beside it (owner answer 93 of 2026-10-08, review item C12). Verify with cases
      in `tests/observability/test_metrics.py` asserting each name, type and label set.
- [ ] 8.2 Wire them: every place that increments `HUMAN_INTERVENTION_TOTAL` (the REST handler and the two MCP sites)
      passes the exception's `joined`, reserve sets the gauge, join does not touch the gauge, the cap path increments
      the existing `NOVNC_FLOW_BUSY_TOTAL`, and each reclamation increments with its own reason. Verify with a test
      that runs one of each path and asserts the exact counter deltas, including `joined="false"` for a new flow,
      `joined="true"` for a join, and that join leaves the gauge alone.
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
      `.venv/Scripts/python.exe -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`
      (`.venv/bin/python -m pytest ...` on Linux and macOS). Verify it
      passes at 100 percent branch coverage with no `# pragma: no cover` and no `# noqa` added anywhere in this
      change.
- [ ] 9.4 Run `.venv/Scripts/python.exe -m ruff check .`, `.venv/Scripts/python.exe -m ruff format --check .` and
      `.venv/Scripts/python.exe -m mypy src tests` (`.venv/bin/python -m` on Linux and macOS), never a console script
      such as `ruff.exe` or `mypy.exe`. Verify all three are clean, with no
      suppression added.

## 10. Documentation and decisions

- [ ] 10.1 Add every setting of tasks 1.1 and 1.5 to the tables in `apps/ascend-web-hunter/AGENTS.md`, `README.md` and
      `docs/configuration.md`, the rows of `docs/configuration.md` in the same commit as the setting, each with its
      default and its description ending with "Added by `open-several-novnc-windows-at-once`." (owner rule 98 of
      2026-10-08, the per-service configuration reference), with `NOVNC_MAX_CONCURRENT_FLOWS` documented as a per container memory constraint and
      not only a display one, `NOVNC_DISPLAY_SIZE` documented as the size Xvfb and the service both read, whose
      default the Dockerfile also sets for the image, the window, lease, sweep, cancel and `Retry-After` settings with
      the derivations of the design configuration table, and
      `NOVNC_PUBLIC_URL` documented as one base address shared by every container, the address of the web-hunter edge
      proxy of `scale-web-hunter-across-containers` (owner answer 96 of 2026-10-08) with no path, from which each container builds `<NOVNC_PUBLIC_URL>/novnc/<hostname>/vnc.html` for its own
      flows, no NoVNC port published by any container, and unset for one container without that proxy, where
      `PUBLIC_VNC_URL` and the one Ngrok tunnel stay (design Decision 11, owner answers 94.4 and 95.1 of 2026-10-08).
      Verify each setting name of tasks 1.1 and 1.5 appears in all three files, that every row this change adds to
      `docs/configuration.md` ends with "Added by `open-several-novnc-windows-at-once`.", and that no stale reference to the single-flow
      behaviour remains, by grepping for "only one" and "one at a time" across the module's docs.
- [ ] 10.2 Write `docs/architecture/decisions/ADR-013-concurrent-human-intervention-windows.md` in the existing
      ADR format: the concurrency model, the per-flow browser and ephemeral CDP port, the cascade layout, the join
      rule, and the widened unauthenticated VNC surface with the recommendation to set `VNC_PASSWORD`. Include the
      rejected alternatives from `design.md` Decisions 4 and 5 with their reasons. Verify the file follows the
      structure of ADR-003 and ADR-008 and is added to the decisions `README.md` index. The ADR also states that the
      new listing endpoint is read-only and unauthenticated, exactly like `vnc_url` in the 428 body, that it returns
      no cookies, storage state or page content, and that it discloses only `vnc_url` values the 428 body already
      returns. ADR-009 to ADR-012 already exist, so this record is ADR-013.
- [ ] 10.3 Amend ADR-003 rather than superseding it: mark the single-flow paragraph and the
      `--remote-debugging-port=9222` security bullet as superseded by ADR-013, with the date, and leave the rest of
      the record intact, including the amendment `add-ascend-python-common` made, which marks the 428 and 409 body
      shape as superseded by the problem body. Verify ADR-003's status line and its other content are unchanged, and that the risk it
      recorded ("No cap on concurrent tasks exists today") now points at the setting that answers it.
- [ ] 10.4 Add one evidence line to F22 in `docs/DEFECT_REGISTER.md` recording that the collision it names cannot
      recur under the per-flow model, naming this change and the regression test in task 9.1. Verify F22's status
      is not changed and no other row is touched.
- [ ] 10.5 Bump `version` in `apps/ascend-web-hunter/pyproject.toml`, the version line in
      `apps/ascend-web-hunter/AGENTS.md` and the version in `apps/ascend-web-hunter/docs/architecture/arc42/02-constraints.md`
      from `0.0.8` (set by `add-python-runtime-upgrades`) to `0.0.9`, and add one `## [0.0.9]` entry at the top of
      `apps/ascend-web-hunter/CHANGELOG.md` describing the concurrent intervention windows (owner decision of
      2026-10-08, one named version per change, in build order). `detect-challenge-walls-in-any-language` writes its
      own `## [0.0.10]` entry. Verify `pyproject.toml`, `AGENTS.md` and the arc42 page read `0.0.9` and the CHANGELOG
      holds exactly one `## [0.0.9]` heading, the topmost version heading.

## 11. End-to-end coverage

Owner request of 2026-10-04: every behaviour this change adds has an end-to-end test. Deterministic checks go into a
new automated spec, the human step goes into the existing human spec 11, and spec 7 gets the 409 rule. Spec 7 is fully
automated since its human part moved to spec 11, so it has no Part 3. The shared fake site, the problem body check and
the scenario rule are design D10 to D14 of `add-web-search-scraping-e2e`, built by its tasks 7.1 to 7.3, 7.5 and 7.6 and by `add-ascend-python-common` (build group 2, position 1), which carries its tasks 7.4, 7.7 and 7.8 (the Bruno variables, the problem body check and the allow list) since the dependency fix of 2026-10-05, all before this section
starts.

- [ ] 11.1 In `apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md`, state that a
      `409 novnc_busy` on a best-effort row is a FAIL unless the run has genuinely saturated
      `NOVNC_MAX_CONCURRENT_FLOWS`, and add a prerequisite that the matrix runs with a cap of at least 4 so the window
      of spec 11 or of the new spec of task 11.3 cannot starve it. This is the one cap rule of spec 7:
      `detect-challenge-walls-in-any-language` task 11.5 later raises it to at least 5 in place and adds no second
      rule. Name rows n, o, p and t and the 2026-09-10 run as
      the reason the rule exists. Verify by re-reading the Contract section and confirming the accept-set and the new
      rule do not contradict each other.
- [ ] 11.2 Update the Concurrency sections of spec 7, spec 10, spec 11 and spec 12 and the "Parallelism and execution
      order" table of `apps/ascend-web-hunter/e2e/README.md`: a 428 no longer holds the single shared NoVNC browser, so
      every conflict that names that browser becomes a conflict over the window slots, which only the new spec of task
      11.3 fills on purpose. Verify each section still states what the test mutates and what it conflicts with, per the
      `e2e-runbooks` contract, and that no section still names one shared browser.
- [ ] 11.3 Write the new automated spec `apps/ascend-web-hunter/e2e/testing/<N>-concurrent-interventions-test.md`
      (`<N>` the next free number at implementation time) and its template under `testing/templates/`. No human. Its
      target is the synthetic captcha wall page `/turnstile-wall` of task 11.9 on the fake site under its allowed name `e2e-fake-site`
      (design D12 of `add-web-search-scraping-e2e`, owner answer 67.3 of 2026-10-04), read under the profiles `e2e-w1` to `e2e-w5`, so one site gives five distinct
      flows. Prerequisite: `GET /api/v2/session/interventions` reports `active_flows` 0 and `max_concurrent_flows` 4
      (the listing fields of design Decision 9). Run and
      Expected, each step checked before the next:
      1. Reads under `e2e-w1` to `e2e-w4` each answer HTTP 428 with the problem body check of design D13 of
         `add-web-search-scraping-e2e` (`code` `human_intervention_required`, `type`, `status`, `instance`, `traceId`,
         non-empty `vnc_url`), `joined` false, four distinct `flow_id` values, four distinct `window.slot` values, and a
         `window` position and size inside the display size `NOVNC_DISPLAY_SIZE` the startup banner prints.
      2. The REST listing reports `active_flows` 4, `max_concurrent_flows` 4 and each `flow_id` once with its target,
         profile, slot, window and a positive remaining lease, and its body holds no cookie name, cookie value or
         storage state. The MCP `session_interventions` tool returns the same four `flow_id` values.
      3. A read under `e2e-w5` answers HTTP 409 with the problem body check (`code` `novnc_busy`), a `Retry-After`
         header, `active_flows` 4, `max_concurrent_flows` 4, `flows` with four entries and `holder_url` naming the
         oldest flow.
      4. A second read under `e2e-w2` answers HTTP 428 with `joined` true and the `flow_id` of step 1 for `e2e-w2`, and
         the listing still reports `active_flows` 4.
      5. `/ready` answers the same status it answered before step 1, and a read of the fake site's plain article page
         answers HTTP 200 with `status` `success`.
      6. `/metrics` shows `novnc_active_flows` 4, `human_intervention_total{joined="true"}` one higher and
         `novnc_flow_busy_total` one higher than before step 1.
      7. Cleanup waits, polling the listing, until it reports `active_flows` 0 (at most the flow lease of design
         Decision 7 plus one sweep interval), then asserts no `session:<fake site domain>:e2e-w*` key and no
         `novnc_flow:<fake site domain>:e2e-w*` key exists in Redis, because nobody solved a wall. Review item C13 of
         the overengineering review proposes a restart of ascend-web-hunter in place of this wait. It waits for the
         owner's yes, so the wait stays until then.
      Concurrency: it fills every window slot, so it runs alone, with no other spec that can answer a 428 (7, 10, 11,
      12 and the wall spec of `detect-challenge-walls-in-any-language`). Verify every assertion is observable state
      (HTTP status, response body, `/metrics`, a Redis key), never a log substring.
- [ ] 11.4 Add the Bruno requests of task 11.3 in the folder `docs/api/request/AscendAI/web-hunter/testing/interventions/`:
      `interventions-list.yml`, `intervention-window-open.yml` (profile taken from an env variable),
      `intervention-window-5th-busy.yml`, `intervention-window-duplicate-join.yml` and `mcp-session-interventions.yml`,
      each with its assertions in the request file. Verify each runs with `bru run "<file>" --env ascend-local` against
      a live stack and asserts on the body fields the spec names.
- [ ] 11.5 Extend the human spec `apps/ascend-web-hunter/e2e/testing/11-captcha-solve-and-capture-test.md` and its
      template with a Part 2, "Two windows solved out of order": open the democaptcha form under the profiles
      `e2e-h1` and then `e2e-h2`, print both `vnc_url` values and slots, the human solves the `e2e-h2` window first and
      the `e2e-h1` window second, and after each solve the runner asserts that the listing frees exactly that flow's
      slot and that `session:democaptcha.com:e2e-h2` and then `session:democaptcha.com:e2e-h1` hold the `hmt_id`
      cookie, with the other key unchanged. Verify the template's rows match the spec's rows item for item.
- [ ] 11.6 Update `e2e/testing/templates/7-authenticated-realworld-scraping-tasks.template.md` with the new 409 rule, so
      a run record carries it. Verify the template's row set matches the spec's row set exactly, item for item.
- [ ] 11.7 Update `e2e/README.md`'s capability matrix and `e2e/testing/README.md`'s ordered list with the new spec and
      the spec 11 Part 2. Verify the matrix lists each once and that the spec count in the prose still matches.
- [ ] 11.8 Add the new spec of task 11.3 to the spec lists, counts and run order of scenarios 1 to 6 and of the
      ascend-web-hunter service suite in `docs/E2E_RUN_SCENARIOS.md`, as a spec that runs alone after spec 10, and
      name the spec 11 Part 2 in the closing human step of scenarios 3, 4 and 5. Verify every count in the document
      still adds up.
- [ ] 11.9 Add the page `/turnstile-wall` to the shared fake site `apps/ascend-web-hunter/e2e/fake-site/app.py` and list
      it in `apps/ascend-web-hunter/e2e/fixtures/README.md`: a thin page, far under `CHALLENGE_WALL_MAX_BYTES`, holding
      only a title, one short line asking the visitor to confirm they are human, and a `<div class="cf-turnstile">`
      element, with no script, so today's `ChallengeDetector.is_blocked` treats it as a wall (its `cf-turnstile` rule
      for a page under `CHALLENGE_WALL_MAX_BYTES`) and the read escalates to NoVNC. Run this task before task 11.3.
      Verify that the image builds, that the page answers 200 `text/html; charset=utf-8`, and that one read of it
      through `POST /api/v2/web/read` on the stack of this change answers HTTP 428 with `code`
      `human_intervention_required`, after which the cleanup of task 11.3 step 7 runs.

## 12. Live verification

- [ ] 12.1 Rebuild and restart the scrapper stack from the repository root against the main compose file, then
      confirm the container is running the new image. Verify with `docker compose ps ascend-web-hunter` and by
      reading the startup banner for the new settings.
- [ ] 12.2 Measure the memory cost of the default cap, which Open Question 1 in `design.md` leaves open. Open four
      concurrent flows, record container memory with `docker stats` at rest, at one flow and at four, and record the
      per-flow increment. Verify the recorded figure is written into `design.md`'s configuration table, and either
      confirm the default of 4 or lower it there, in `config.py`, in the two compose lines and the two `.env.example`
      lines of task 1.6, in the bundle README row and in the `docs/configuration.md` row, in the same edit.
- [ ] 12.3 Drive the sequence of task 11.3 by hand once before running it as a spec: four windows open, look at the NoVNC
      display and confirm four windows are visible with reachable title bars, clear them out of order, and confirm
      each clearance frees exactly one slot. Verify against
      `GET /api/v2/session/interventions` between each step rather than by impression.
- [ ] 12.4 Prove the lease and the sweeper live: open a flow, kill its Chromium from inside the container, and
      confirm the slot is freed and the window gone within one sweep interval plus the grace, without any further
      request being made. Verify with the interventions listing and with `docker exec ... ps`.
- [ ] 12.5 Ask the owner which run scenario of `docs/E2E_RUN_SCENARIOS.md` to use, then re-run e2e spec 7 in full with
      Part 1 fanned out, and confirm rows n, o, p and t return a terminal verdict rather than a 409. Then run the new
      spec of task 11.3 alone, and, when the chosen scenario has a human at the keyboard, spec 11 with its Part 2.
      Verify by the run records written under `e2e/testing/runs/`, and attach them to this change.
