## Why

The archived change
[2026-09-18-enhance-web-search-scraping](../archive/2026-09-18-enhance-web-search-scraping/design.md) names three
pieces of its own design that it specified and did not build. They are listed there under "Follow-ups left open at
landing", and each one is a capability the specs already promise and the code does not deliver.

1. **The validated address is not the address connected to.** `is_safe_external_url`
   ([url_validator.py](../../../apps/ascend-web-hunter/src/validator/url_validator.py)) resolves the hostname,
   checks every returned address, and then throws the resolution away. The fetch that follows resolves the same
   name a second time, so whoever controls the authoritative DNS for a name can answer the validation query with a
   public address and the connect query with `169.254.169.254`. Re-validating each redirect hop, which the landing
   did build, narrows that window to the gap between one check and one connect. It does not close it, because the
   connect still re-resolves. The design called this out as the unbuilt half of D6.
2. **`SessionManager.validate()` is dead weight on the read path.** It exists, it is correct, and it has no caller.
   A read against a domain whose stored login lapsed weeks ago proceeds as if the session were live: the expired
   cookies are dropped by the store, the tiers fetch anonymously, and the caller gets a logged-out page or a 428,
   with no signal that the cause was an expired session it could re-establish in one call. The `session_expired`
   outcome the design describes cannot occur, because nothing asks.
3. **Two orchestrator controls are unreachable from both API surfaces.** `output_format=structured` threads through
   `WebReader.read`, `read_with_links` and the cache key, and neither the REST read nor the MCP `web_read` tool
   accepts it, so the structured extractor built in the same change is reachable only from inside the process. A
   caller-supplied starting tier does not exist at all: `heavy_mode` is the one coarse knob and it means "start at
   Playwright", so there is no way to ask for FlareSolverr first, no way to force the cheap tiers for a page known
   to be static, and no way for the e2e suite to exercise one tier deliberately.

## What Changes

- **Connect-time address pinning (piece 1).** `pin_safe_host(url)` resolves a host once, validates every address it
  returns against the same private, loopback, link-local, multicast and reserved rules the existing guard uses, and
  returns those addresses as a pin. The in-process `curl_cffi` tier hands the pin to libcurl through
  `CURLOPT_RESOLVE`, so the connection goes to an address that was validated by the same lookup that authorised it.
  A second answer to a second lookup never reaches a socket. This applies to the initial URL and to every redirect
  hop, replacing the second, unpinned resolution the hop check performs today. The tiers that fetch outside this
  process (FlareSolverr, Crawlee) and the tiers that fetch through the shared browser (Playwright, NoVNC) keep
  pre-dispatch validation and stay residual risk, recorded in a new ADR rather than implied.
- **The read path consults the stored session (piece 2).** When a stored record for the target domain and profile
  carries auth cookies, meaning a login was captured at some point, the read calls `SessionManager.validate()`
  before the tier chain runs. A valid session slides its auth TTL, exactly as the specification for validate
  already says, so an actively used login stops expiring under its user. An invalid one returns a `session_expired`
  read outcome naming the domain, the profile, and the operation that re-establishes it, instead of a silent
  anonymous read. A domain with no stored session, or a record that only ever held WAF clearance, is untouched and
  still reads anonymously.
- **Both read controls reach both API surfaces (piece 3).** `POST /api/v2/web/read` and the MCP `web_read` tool
  gain `output_format` (`text` or `structured`, default `text`) and `tier` (one of the six strategy names, default
  unset). `tier` starts the escalation chain at the named tier and keeps the remaining tiers in their existing
  order, so escalation still works from wherever it starts. Both fields join the read cache key. `output_format`
  combined with `include_links` is rejected at the boundary rather than silently ignored, because the links path
  produces the annotated flat shape and cannot produce the structured one. The pre-emptive login-redirect check
  still outranks an explicit `tier`, because the rule that a known login-redirect URL goes straight to the
  human-intervention tier is a safety requirement, not a routing preference.

Out of scope: pinning inside the browser tiers, which would need a browser launched per request because Chromium
takes its resolver rules on the command line and the pool launches one browser for the process. A network-probe
session validate, which needs a per-site logged-in marker and stays the open item D4 already names. Structured
output on the `include_links` path.

## Capabilities

### New Capabilities

<!-- None: all three pieces belong to capabilities that already exist under openspec/specs/. -->

### Modified Capabilities

- `web-search-fetch-correctness`: gains a requirement that the address the guard validated is the address the
  in-process fetch connects to, with the out-of-process and browser tiers named as residual risk.
- `web-search-authenticated-sessions`: validation is now invoked by the read path, and an expired stored session
  produces a `session_expired` outcome. The read operation exposes `output_format` and `tier`, which the current
  text explicitly says it does not.
- `web-search-extraction-quality`: structured output is reachable from REST and MCP, which the current text
  explicitly says it is not.

## Impact

- **Code:** `src/validator/url_validator.py` (pin), `src/reader/strategies/curl_cffi_fetcher.py` (pinned connect),
  `src/reader/cloudflare/cookie_manager.py` (the `has_auth_cookies` gate accessor, plus `_get_domain` promoted to
  the public `registrable_domain` the outcome message needs), `src/session/session_manager.py` (the two call sites
  of that rename, which drop the two `noqa: SLF001` suppressions they carried), `src/reader/web_reader.py`
  (session gate, tier override, cache key), `src/api/rest/rest_endpoints.py` and `src/api/mcp/mcp_server.py` (two
  new read fields and one rejected combination).
- **API:** two optional fields on one read operation across both surfaces, one new 400 for an unsupported
  combination, and one new read outcome (`status: session_expired`) returned with HTTP 200 alongside the existing
  `human_intervention_required` and `novnc_busy` outcomes. No existing field changes meaning and no default
  changes, so a caller that sends neither field sees the behaviour it sees today.
- **Config:** no new settings. Every threshold involved already exists.
- **Dependencies:** none. `CURLOPT_RESOLVE` is exposed by the pinned `curl_cffi==0.15.0` already in the manifest.
- **Docs/ADRs:** ADR-011 for the tier override, which reverses the position ADR-001 took in its rejected
  Alternative 3, and ADR-012 for connect-time pinning and the tiers it cannot cover. Plus the arc42 crosscutting
  SSRF section, the context and glossary entries for the read operation, `docs/api-examples.md` and
  `docs/running.md`.
- **Tests:** the module's 100 percent branch-coverage gate holds. The pinning tests demonstrate a rebinding attempt
  between validation and connect being refused, not merely that the happy path still works.

## Relevant Skills

Load these before implementing:

- `/python-patterns` for typing, pytest discipline and the async conventions this module follows.
- `/tdd-workflow` for the red-green loop and the coverage gate.
- `/security-review` for the SSRF work in piece 1, which is the reason piece 1 exists.
- `/api-design` for the two new read fields, the rejected combination and the new outcome.
- `/coding-standards` for the cross-cutting floor.
- `/ai-regression-testing` for asserting the response contract on both surfaces rather than one field at a time.
