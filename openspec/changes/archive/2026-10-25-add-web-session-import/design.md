## Context

ascend-web-hunter stores one session record per registrable domain and profile in Redis under `session:{domain}:{profile}` (`CookieManager` in `apps/ascend-web-hunter/src/reader/cloudflare/cookie_manager.py`). `save_storage_state(url, storage_state, user_agent, profile, produced_by)` splits a Playwright storage state into an `auth` part and a `waf` part and saves both. Today only two paths write it: the NoVNC capture after a human login, and the e2e harness, which calls the method in-process. The REST API already has `session/establish`, `session/status` and `session/clear` on `rest_router_v2` (prefix `/api/v2/web`), each with a small Pydantic model holding `url: HttpUrl` and `profile: str | None`.

## Goals and non-goals

Goals:

- One supported way to put a captured login into the store from outside the process.
- The stored record is identical in shape to the ones the existing paths write, so nothing downstream changes.
- The e2e harness loses every import of service code.

Non-goals:

- No authentication or per-caller isolation on the endpoint. Profiles stay free-form labels for a single local user, as the main spec says.
- No export endpoint. Reading a stored session back out is not part of this change.
- No MCP tool.

## Decisions

### D1: Request shape

```text
POST /api/v2/web/session/import
{
  "url": "https://www.saucedemo.com/inventory.html",
  "profile": "e2e",
  "storage_state": {"cookies": [...], "origins": [...]},
  "user_agent": "Mozilla/5.0 ..."
}
```

`url` is `HttpUrl`. `profile` is optional and falls back to `settings.SESSION_DEFAULT_PROFILE` like the other session routes. `storage_state` is a Pydantic model with `cookies: list[Cookie]` and `origins: list[Origin]`, where `Cookie` holds the Playwright cookie fields (`name`, `value`, `domain`, `path`, `expires`, `httpOnly`, `secure`, `sameSite`) and `Origin` holds `origin` and `localStorage` (a list of `name` and `value`). Unknown top-level fields are refused (`extra="forbid"`). `user_agent` is optional. When it is missing the service stores the user agent its own browser tier sends, so a replay by that tier is consistent.

### D2: Validation and error codes

All checks run before anything is written. Every refusal is an RFC 7807 problem body built by the problem builder of the `ascend-python-common` library (its D5): media type `application/problem+json`, `type` `https://ascend.ai/errors/` followed by the code with every `_` replaced by `-`, `title`, `status`, `detail`, `instance`, the extension field `code` and the extension field `traceId`. Every code is a lower case snake case entry in the service's `ErrorRegistry` in `src/api/exception_handlers.py`, and this change adds no error helper of its own.

| Check | Status | Code |
|---|---|---|
| Body does not match the model, including a bad `url` and an unknown field | 400 | `validation` with the `errors` field, the library's answer for every web-hunter endpoint |
| The host of `url` has no registrable domain: an IP address literal, or a name with no public suffix such as `localhost` (`CookieManager.registrable_domain` finds no domain and suffix), checked with no address lookup | 400 | `unsafe_uri`, raised as the library's `UnsafeUriError`, the code ascend-web-hunter registers for it, built by the library |
| `profile` does not match `^[A-Za-z0-9_-]{1,64}$` | 400 | `invalid_profile` |
| No cookie whose `domain`, with a leading dot removed, equals the URL's registrable domain or ends with `.` plus it | 400 | `no_cookies_for_domain` |

There is no limit on the body size or on the number of cookies (owner decision, 2026-10-01: no made-up limits). The checks are the ones that protect something real: a host with a registrable domain, the profile pattern and the domain match.

The import makes no request to the URL, so it does not run the library guard `check_fetch_uri` and its address lookup (owner decision 93 of 2026-10-08, review item C18). The safety of the guard stays where a request is made: every read, download or session check that later replays the imported session fetches through `check_fetch_uri` (`add-ascend-python-common` D21, owner answer 63.2), which refuses a private, loopback, link-local or reserved address at that moment. A session stored for a name that resolves to a private address is therefore never sent there. `session/establish`, `session/status` and `session/clear` keep `check_fetch_uri` unchanged. The profile pattern is stricter than the free-form label the main spec allows, because an imported profile becomes part of a Redis key and is written by any caller. The other session routes keep their current behaviour.

### D3: Storing

The route calls `cookie_manager.save_storage_state(url, storage_state.model_dump(by_alias=True), user_agent, profile, produced_by=PRODUCED_BY_IMPORT)`. Cookies for other domains are dropped before the call, so an import cannot plant cookies for a second site. The read cache for the domain is then cleared on every ascend-web-hunter instance (D6), so the next read on any instance uses the new session instead of a cached anonymous page.

The answer is:

```text
200 {"status": "imported", "domain": "saucedemo.com", "profile": "e2e", "auth_cookies": 1, "waf_cookies": 0, "dropped_cookies": 0}
```

### D4: Harness

`seed_authenticated_session.py` keeps its Playwright login against `saucedemo.com` with the public demo credentials. After `context.storage_state()` it sends the import request with `httpx` to `WEB_HUNTER_BASE_URL` (default `http://localhost:7021`) and exits non-zero when the answer is not `200`. It no longer imports anything from `src`.

### D5: Version 0.0.14

The change ships as ascend-web-hunter 0.0.14 with one CHANGELOG entry (owner decision of 2026-10-08, one named
version per change, in build order). 0.0.13 is the version of `remove-flaresolverr-tier`, which lands directly before
this change (build group 2, position 7), and `enhance-web-search-crawl-at-scale` takes 0.0.15 after it. The bump moves
`pyproject.toml`, the `AGENTS.md` version line and `docs/architecture/arc42/02-constraints.md` together.

### D6: Read cache cleared on every instance

Several ascend-web-hunter containers run at once (owner decision 87 of 2026-10-08). The session store is already shared in Redis, but the read cache of `WebReader` is a map inside each process with a bounded lifetime, so a purge in one process alone would let another container answer a cached anonymous page. `enhance-web-search-extraction-and-tiers` (build group 2, position 6, before this change) already makes the purge that a session clear runs reach every container: its design D7 and task 5.5 build the Redis channel `read_cache_purge`, the subscriber task in the lifespan, the local purge that still runs when Redis fails, and the full cache drop after a reconnect. The import route calls that same purge for the domain, exactly as `session/clear` does, so the job has one mechanism (owner decision 89 of 2026-10-08). This change adds no channel, no method name and no subscriber of its own.

## Risks and trade-offs

- Any caller that can reach port 7021 can plant a session. The same is already true of `session/establish`, and the service is local-only. A later auth change covers both.
- The stricter profile pattern means a profile created by NoVNC with characters outside the pattern cannot be overwritten by import. Accepted, since such a profile can still be cleared with `session/clear`.

## Owner decisions of 2026-10-08

- Item 11 of the review of 2026-10-07, approved by the owner on 2026-10-08: the change had no version bump and no
  CHANGELOG task. It now bumps ascend-web-hunter by one patch step with one CHANGELOG entry (D5, task 4.1).
- Owner decision of 2026-10-08, "one named version per change, in build order": this change ships as
  ascend-web-hunter 0.0.14, one patch step after 0.0.13 of `remove-flaresolverr-tier` (D5).
- Item 19 of the same review: task 2.5 runs mypy over `src tests`, the same gate as `add-ascend-python-common` D14.

Answer 87 (rule R1): several ascend-web-hunter instances run at once. The session store stays in Redis, which every instance shares. The read cache is a map inside each process, so the import calls the purge across instances that `enhance-web-search-extraction-and-tiers` task 5.5 builds for `session/clear`, one mechanism for one job (answer 89, D6, task 2.6). Nothing else of this change keeps state inside one process.

Answer 85.1: no task of this change exports a key or a secret in a shell. The harness and the Bruno requests need no secret, and the saucedemo.com demo login is public.

Answer 90: this change adds no test-only setting or seam to the service. The unit tests mock `cookie_manager` and `web_reader` on the test side (task 2.1).

Answer 91.3: the 1000 cookie step of the session import e2e spec and its fixture `session-import-1000-cookies.json` are removed, and the unit test of task 2.1 that imports 1000 cookies stays. The refusal steps of that spec (`unsafe_uri`, `invalid_profile`, `no_cookies_for_domain` and `validation`) are removed too, because the unit tests of task 2.1 prove each refusal and that nothing is stored. The spec keeps the steps no lower test proves: an import stored in the real Redis with provenance `import`, the status answer `active` for it, and the clear (task 3.6). Its Bruno folder loses the requests of the removed steps (task 3.7).

Answer 93 (review item C18): the import no longer runs `check_fetch_uri` and its address lookup on a URL it never fetches. It refuses, with no lookup, a host with no registrable domain with 400 `unsafe_uri` (D2), and every request that later uses the imported session still passes `check_fetch_uri`, so the protection the owner asked for in answer 63.2 stays where a request is made. `add-ascend-python-common` gets the matching note through `inbox93`.

Answer 98: every value with a default that this change plans was checked against the configuration rule. The change adds no operational value, so it adds no setting, no compose line, no `.env.example` line and no row in `apps/ascend-web-hunter/docs/configuration.md`, and the proposal's Impact line "no new setting or environment variable" stays true. The profile it falls back to is the existing setting `SESSION_DEFAULT_PROFILE`, unchanged. Values kept as constants, with the reason: the profile pattern `^[A-Za-z0-9_-]{1,64}$`, because it is the format of an identifier that becomes part of the Redis key `session:{domain}:{profile}` (a key format, like the tenant format `[a-z0-9-]{1,64}` of the other web-hunter changes), the provenance value `PRODUCED_BY_IMPORT = "import"` (an enum value), the route path and the error codes `invalid_profile` and `no_cookies_for_domain` (API path and error codes), and the harness default `WEB_HUNTER_BASE_URL` of `http://localhost:7021` (a test-only value of `seed_authenticated_session.py`, which owner answer 90 keeps out of the service settings). No test or measurement of this change uses LM Studio, and no text of it names the old `e2e` Spring profile or the overlay mount.
