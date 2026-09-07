# ADR-005: Strategy budget, singleton Chromium, and recursion guard

## Status

Accepted — 2026-05-31

## Context

The original `WebReader` chain had three independent timeouts but no overall budget, so a worst-case escalation
through all six tiers could run for ~13 minutes before returning. The first three tiers default to
`EXTRACT_TIMEOUT=30s` each; `FlareSolverr` doubles that; `Playwright` and `Crawlee` add another 30 s apiece;
`NoVNC` is human-gated at 600 s. A misbehaving target site dragged the calling chat assistant past any usable
latency budget.

`PlaywrightStrategy.get_html` opened `async_playwright()` inside the request, launched a fresh Chromium browser
per call, then tore it down. Cold Chromium launch on Linux is 600-1500 ms before navigation; on every tier-4
escalation the request paid that cost.

`WebReader._execute_strategy` caught `ChallengeDetectedException` from a strategy and re-dispatched to
NoVNC via `_execute_strategy("6-novnc", ...)`. If the NoVNC strategy itself ever raised the same exception
(directly or via a future internal refactor that propagates one from its inner Playwright calls), the same
handler would re-enter and recurse without bound, blowing the Python stack mid-request.

## Decision

Three coupled changes in `src/reader/web_reader.py` and `src/runtime/browser_pool.py`.

### 1. Total read budget

`Settings.READ_TOTAL_BUDGET` (default 90 s) caps the wall-clock time across the strategy chain tiers 1-5.
Before invoking each tier the loop checks `time.perf_counter() - started > READ_TOTAL_BUDGET`; if exceeded,
the remaining tiers are skipped and the failure response is returned. NoVNC (tier 6) is exempt because it
returns 428 immediately and the actual human work happens out-of-band.

90 seconds covers a realistic full escalation (typical tier 1-2 at 1-3 s, tier 3 at 10-15 s, tier 4 at
10-20 s, tier 5 at 10-20 s) with headroom for slow networks. Past 90 s the caller's UX is already broken;
better to return a clean failure than continue spending wall-clock for a tier that may also miss.

The exhaustion is observable via `read_budget_exhausted_total` (Prometheus counter).

### 2. Singleton Chromium browser

`src/runtime/browser_pool.py` runs one `async_playwright().start()` + `chromium.launch()` for the lifetime of
the FastAPI process. `PlaywrightStrategy` creates a fresh `BrowserContext` per request (~50 ms) and closes
only the context on completion; the browser process is reused. If the browser disconnects (Chromium crash,
OOM), `get_browser` relaunches transparently behind an `asyncio.Lock`.

The browser is started inside the FastAPI lifespan (`src/main.py`) and stopped on shutdown. `Crawlee` and
NoVNC still launch their own browser instances because their lifecycles do not fit the singleton model
(Crawlee owns the browser internally, NoVNC needs a separate per-task browser with VNC visibility).

### 3. Recursion guard

`_execute_strategy` and `_execute_html_strategy` take an `escalating: bool = False` parameter. When the
`ChallengeDetectedException` handler re-dispatches to NoVNC, it passes `escalating=True`. If the second call
catches `ChallengeDetectedException` again, the handler logs and returns `None`/`""` instead of re-recursing.
The recursion is bounded to depth 2 by construction.

## Alternatives Considered

### Alternative 1: Per-tier timeouts only, no total budget
- **Pros**: No new setting; per-tier timeouts already exist.
- **Cons**: Worst-case still scales with the number of tiers. Adding a new tier shifts the worst case again
  without anyone noticing.
- **Why not**: The user-facing budget should be on the user-facing operation, not on the implementation
  detail of how many tiers exist.

### Alternative 2: Browser pool with multiple Chromium instances and a semaphore
- **Pros**: Higher concurrent tier-4 throughput when many requests hit the slow path at once.
- **Cons**: Memory cost per browser is ~300 MB. Justifying multiple instances requires evidence of contention
  that doesn't exist at current request volume.
- **Why not**: Premature optimisation. Single browser + per-request context is the standard Playwright
  server pattern; revisit if metrics show contention.

### Alternative 3: Track depth as an integer, allow arbitrary recursion up to N
- **Pros**: Generalises to deeper chains if future strategies want to escalate from inside NoVNC.
- **Cons**: There is no real use case for depth > 2 here. NoVNC is the terminal strategy.
- **Why not**: Boolean is enough and the failure mode is clearer.

## Consequences

### Positive
- Worst-case `read()` latency capped at 90 s plus the last in-flight tier's per-strategy timeout, regardless
  of how many tiers escalate.
- Tier-4 latency drops by 600-1500 ms per request (browser launch eliminated).
- Recursive crash mode is structurally impossible.

### Negative
- The browser pool is a long-lived process. If Chromium leaks memory over many requests, restart cycles need
  to drain it; today the only signal is `is_connected()` checked on the next `get_browser` call.
- Crawlee's separate browser lifecycle means tier 5 still pays a per-request launch cost. Not addressed
  here; revisit when crawlee 1.x adds external-browser injection.

### Risks
- **READ_TOTAL_BUDGET too tight**: 90 s assumes typical network. On extremely slow upstreams the budget may
  exhaust before tier 4 returns. Configurable via env var so deployments with different network profiles can
  tune.
- **Browser process death between requests**: `get_browser` checks `is_connected()` cheaply, but a hung
  browser process that returns `True` from `is_connected()` while being unresponsive would not trigger
  relaunch. No mitigation today; future work.

## Related

- `src/reader/web_reader.py:_budget_exceeded`, `_execute_strategy`, `_execute_html_strategy`.
- `src/runtime/browser_pool.py:BrowserPool`.
- `src/observability/metrics.py:READ_BUDGET_EXHAUSTED_TOTAL`, `STRATEGY_ATTEMPTS_TOTAL`, `STRATEGY_DURATION_SECONDS`.
- `src/config/config.py:READ_TOTAL_BUDGET`, `PLAYWRIGHT_HEADLESS`.
- [ADR-001](ADR-001-multi-tier-extraction-strategy.md) — the strategy chain this budget applies to.
- [ADR-003](ADR-003-novnc-ngrok-captcha-intervention.md) — NoVNC, the terminal strategy.
