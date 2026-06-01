# Troubleshooting

Common failure modes and the commands that diagnose them. For architectural rationale see the ADRs under
[architecture/decisions/](architecture/decisions/).

---

### Reinstalling Python dependencies

Run each command from inside an activated venv. The sequence: list installed packages, uninstall them,
remove the list, reinstall. `pip` commands are identical in both shells; only the file-deletion step
differs between bash (`rm`) and PowerShell (`Remove-Item`).

Step 1: snapshot installed packages.

```bash
pip freeze > uninstall.txt
```

Step 2: uninstall them all.

```bash
pip uninstall -y -r uninstall.txt
```

Step 3: remove the snapshot file.

Bash:

```bash
rm uninstall.txt
```

PowerShell:

```powershell
Remove-Item uninstall.txt
```

Step 4: reinstall.

```bash
pip install -e .[dev]
```

---

### Playwright browsers missing

The `playwright` Python package is installed but the Chromium binary it drives is not. Local Python only;
the Docker image bundles them.

```bash
playwright install --with-deps chromium
```

If the install fails on Linux without root, run with `sudo` or use the Docker image instead.

---

### `/ready` reports `redis: error` while `/health` returns 200

`/health` is liveness only and does not touch dependencies. `/ready` runs an actual `PING` against
`REDIS_URL`. Check the URL matches what's reachable from inside the container, and that Redis is bound to an
interface the container can see.

`docker exec` is identical in both shells.

Bash:

```bash
docker exec ascend-web-search redis-cli -u "$REDIS_URL" PING
```

PowerShell:

```powershell
docker exec ascend-web-search redis-cli -u "$env:REDIS_URL" PING
```

If Redis is intentionally optional, the service still works (cookies fall back to an in-process dict), but
sessions will not survive a restart and will not be shared across replicas.

---

### CAPTCHA flow never completes

The NoVNC monitor task captures cookies for `NOVNC_TIMEOUT_SECONDS` (default 600 seconds). If the user takes
longer to solve, the task exits without saving the session.

- Verify the user actually navigated away from the challenge page; the monitor exits early once `page.url`
  changes off the challenge URL.
- Confirm Redis is reachable, otherwise the cookie capture silently lands in the per-process memory store
  and is lost on the next restart.
- Inspect `human_intervention_total` and `redis_ops_total{op="set"}` in `/metrics` to see whether the
  428 actually fired and whether the cookie was persisted.

---

### `STRATEGY_DURATION_SECONDS` buckets all show 0 above 60 s

Histogram buckets in [src/observability/metrics.py](../src/observability/metrics.py) cover up to 600 s. If a
strategy takes longer it lands in the `+Inf` bucket. Either widen the buckets and rebuild metrics state, or
investigate why a tier is breaching its own per-call timeout.

---

### Container says "browser is None or disconnected, relaunching"

The singleton Chromium process was lost (OOM, crash, or stopped externally) and the pool brought up a fresh
one. One log line is fine. Repeated relaunches in a short window mean Chromium is dying mid-request; check
container memory limits and `dmesg` for OOM kills.

---

### Want full request tracing

Every response carries an `X-Request-ID` header. Echo it back in client requests to correlate across calls,
or read the auto-generated UUID from the response header. Every log line in the process includes the request
ID via the `CorrelationFilter` in [src/config/logging_config.py](../src/config/logging_config.py).
