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

All checks run before anything is written. Errors use the service's existing `HTTPException` detail style and carry a stable code at the start of the detail.

| Check | Status | Code |
|---|---|---|
| Body does not match the model, including a bad `url` | 422 | FastAPI validation error, unchanged |
| `url` fails `is_safe_external_url` | 400 | `UNSAFE_URL` |
| `profile` does not match `^[A-Za-z0-9_-]{1,64}$` | 400 | `INVALID_PROFILE` |
| No cookie whose `domain`, with a leading dot removed, equals the URL's registrable domain or ends with `.` plus it | 400 | `NO_COOKIES_FOR_DOMAIN` |

There is no limit on the body size or on the number of cookies (owner decision, 2026-10-01: no made-up limits). The checks are the ones that protect something real: the safe URL, the profile pattern and the domain match. The profile pattern is stricter than the free-form label the main spec allows, because an imported profile becomes part of a Redis key and is written by any caller. The other session routes keep their current behaviour.

### D3: Storing

The route calls `cookie_manager.save_storage_state(url, storage_state.model_dump(by_alias=True), user_agent, profile, produced_by=PRODUCED_BY_IMPORT)`. Cookies for other domains are dropped before the call, so an import cannot plant cookies for a second site. The read cache for the domain is cleared with `web_reader.clear_cache_for_domain(domain)`, the same call `session/clear` makes, so the next read uses the new session instead of a cached anonymous page.

The answer is:

```text
200 {"status": "imported", "domain": "saucedemo.com", "profile": "e2e", "auth_cookies": 1, "waf_cookies": 0, "dropped_cookies": 0}
```

### D4: Harness

`seed_authenticated_session.py` keeps its Playwright login against `saucedemo.com` with the public demo credentials. After `context.storage_state()` it sends the import request with `httpx` to `WEB_HUNTER_BASE_URL` (default `http://localhost:7021`) and exits non-zero when the answer is not `200`. It no longer imports anything from `src`.

## Risks and trade-offs

- Any caller that can reach port 7021 can plant a session. The same is already true of `session/establish`, and the service is local-only. A later auth change covers both.
- The stricter profile pattern means a profile created by NoVNC with characters outside the pattern cannot be overwritten by import. Accepted, since such a profile can still be cleared with `session/clear`.
