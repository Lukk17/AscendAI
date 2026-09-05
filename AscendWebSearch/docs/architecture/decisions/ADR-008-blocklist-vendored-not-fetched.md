# ADR-008: Blocklist vendored into the image, refreshed only on operator request

## Status

Accepted — 2026-09-04

## Context

`BlocklistLoader.load_rules()` downloaded the Fanboy Annoyance adblock list from `BLOCKLIST_URL` on every call,
with no on-disk cache check, and this ran at startup inside the FastAPI lifespan and again, independently, every
time `WebReader()` was constructed — once for the REST module singleton, once for the MCP module singleton. A
failed download raised and the lifespan re-raised `RuntimeError`, so a slow or unreachable third-party host
prevented the service from starting. This was not hypothetical: it was already breaking the unit test suite
before this change, which is why `tests/conftest.py` carried two separate stubs to keep the download off the
network during collection.

Earlier the same day (commit `0947f99`), the blocklist had been moved the opposite direction: from a file
committed at `src/assets/fanboy-annoyance.txt` to a runtime download into a cache directory, on the reasoning that
committing a ~55,000-line third-party text file into the package was unnecessary when it could be fetched fresh.
That reasoning held only as long as the fetch itself was reliable, and it was not.

## Decision

### D1 — The blocklist is vendored into the repository and the image, not fetched at startup

`src/assets/fanboy-annoyance.txt` is committed to the repository, sourced from
`https://secure.fanboy.co.nz/fanboy-annoyance.txt` (Fanboy's Annoyance List, CC BY 3.0, fetched 2026-09-04). The
Dockerfile's existing `COPY src/ src/` bakes it into the image; no separate `COPY` step was needed, the same way
`src/assets/user_agents.json` already ships this way. `settings.BLOCKLIST_PATH` (default
`src/assets/fanboy-annoyance.txt`) is the single path the service reads from and writes to — there is no separate
cache directory.

### D2 — `load_rules()` never downloads; a missing or corrupt file is a packaging defect

`BlocklistLoader.load_rules()` only reads `settings.BLOCKLIST_PATH` from disk. A missing file, or one that fails
to parse, raises (`FileNotFoundError` / `RuntimeError`) instead of falling back to an empty ruleset or attempting
a network fetch. Since the file ships inside the image, its absence means the image was built without it — a
build-time defect the service should refuse to hide by starting with every URL unfiltered.

`src/validator/url_validator.py` calls `load_rules()` exactly once, eagerly, at module import time, to build a
single process-wide `url_validator = URLValidator(...)` singleton. Both `WebReader` instances (REST and MCP) now
share this one object instead of each building — and each independently loading — their own. `main.py`'s lifespan
no longer loads anything; it only asserts `blocklist_loader.state is not None` as a fail-fast sanity check, since
by the time the lifespan runs the singleton has already been built.

### D3 — Refresh is an explicit, synchronous operator action, never automatic

`POST /api/v1/blocklist/refresh` (`src/api/rest/blocklist_endpoints.py`) downloads `BLOCKLIST_URL`, parses the
result, and only then swaps in the new list: it writes the new content to `settings.BLOCKLIST_PATH` via
`os.replace()` (atomic same-directory rename) and reassigns `url_validator.rules` to the newly parsed
`AdblockRules` object (a single attribute assignment, atomic under the GIL, so a request served concurrently with
a refresh sees either the fully-old or fully-new rule set, never a partial one). A download failure
(`httpx.HTTPError`) or an empty parsed ruleset (`BlocklistValidationError`) raises before either swap happens, so
the file on disk and the rules serving live traffic are untouched. Refresh is synchronous: the caller waits and
gets a definitive answer (`rule_count`, `loaded_at`) rather than firing an update it can't confirm.

Concurrent refresh calls serialise on an `asyncio.Lock`, and a call inside `BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS`
(default 60s) of the last attempt is rejected with 429 rather than reaching the network again — protection against
naive retry loops, not authentication, since the rest of the service has none. `GET /api/v1/blocklist/status`
reports the current rule count and age without triggering anything. Neither endpoint is on the MCP surface:
refreshing a shared blocklist is an operator action, not a decision an calling agent should make mid-conversation.

## Alternatives Considered

### Alternative 1: Keep downloading at startup, add an on-disk cache check
- **Pros**: Smaller diff; the service self-updates without any operator action.
- **Cons**: Still couples "can this process start" to "is a third-party host reachable right now," just less
  often. Still needs a fallback story for the very first boot before any cache exists.
- **Why not**: The whole point of the change is that an outside host's availability stops being able to prevent
  the service from starting, for any request path, including the first one.

### Alternative 2: Ship a small hand-authored seed list, download the full list lazily
- **Pros**: Tiny diff to the repository; avoids committing a large third-party file.
- **Cons**: The seed list is not the real list — it is either too small to be useful or a maintenance burden to
  keep meaningfully current, and it invites confusion about which rules are actually active until the first
  refresh runs.
- **Why not**: Vendoring the real, current list costs one file and one commit; a fake subset costs ongoing
  guesswork about its own adequacy for no benefit once refresh exists.

### Alternative 3: Async/background refresh instead of synchronous
- **Pros**: The HTTP call returns immediately regardless of upstream latency.
- **Cons**: The caller has to poll `/status` separately to learn whether the refresh it triggered actually
  succeeded, which is strictly more round trips for an action that already completes in well under a second in
  practice (a single HTTP GET plus parsing ~55,000 lines).
- **Why not**: An operator calling this endpoint wants to know, in the same response, whether it worked.

## Consequences

### Positive
- No request path — service startup, `WebReader()` construction, or a real HTTP request — depends on
  `BLOCKLIST_URL` being reachable. An outside failure can no longer degrade or block the running service.
- The blocklist is loaded exactly once per process instead of once per `WebReader()` construction, closing the
  duplicate-load item previously tracked in `docs/architecture/arc42/11-risks-and-technical-debt.md`.
- The refresh response is a definitive success/failure signal an operator or a deploy script can branch on.

### Negative
- `src/assets/fanboy-annoyance.txt` is a ~2 MB, ~56,000-line vendored file, which shows up as one large diff
  whenever it's next refreshed via a manual re-download and commit (refreshing via the endpoint at runtime does
  not touch the repository, only the running container's copy).
- A refresh done through the endpoint is only as durable as the container's writable layer: unless
  `BLOCKLIST_PATH` is bind-mounted to a persistent volume, a container restart reverts to whatever was last
  committed to the image, not the last runtime refresh.

### Risks
- **The vendored file goes stale between deployments.** There is no scheduled refresh; an operator has to call
  `POST /api/v1/blocklist/refresh` (or rebuild the image with an updated file) to pick up upstream changes. This
  is intentional per D3, but it means staleness is silent unless something checks `GET /api/v1/blocklist/status`.

## Related

- `src/config/blocklist_loader.py` — `BlocklistLoader`, `BlocklistState`, `BlocklistValidationError`,
  `BlocklistRefreshThrottledError`.
- `src/validator/url_validator.py` — process-wide `url_validator` singleton.
- `src/api/rest/blocklist_endpoints.py` — `GET /api/v1/blocklist/status`, `POST /api/v1/blocklist/refresh`.
- `src/config/config.py` — `BLOCKLIST_PATH`, `BLOCKLIST_URL`, `BLOCKLIST_REFRESH_MIN_INTERVAL_SECONDS`.
- `src/assets/fanboy-annoyance.txt` — the vendored file itself.
- `docs/architecture/arc42/11-risks-and-technical-debt.md` — the duplicate-load item this closes.
