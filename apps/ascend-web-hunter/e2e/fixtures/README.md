# e2e fixtures

ascend-web-hunter tools (`web_search`, `web_read` via MCP; `/api/v1/web/search`, `/api/v2/web/read` via REST) take
string arguments only - no file uploads.

- `session-clear-seed.json` - a synthetic minimal `storage_state` record used by test 8
  ([../testing/8-session-clear-test.md](../testing/8-session-clear-test.md)) to seed a session for `example.net`
  directly in Redis, without a login flow, FlareSolverr, or a human. `docker cp`'d into the `redis` container and
  loaded via `redis-cli -x SETEX ... < file`, since piping the JSON through a shell pipe corrupts it (PowerShell
  prepends a BOM, bash treats a bare quoted string as a command).
- `session-status-expired-seed.json` - the same kind of synthetic `storage_state` record, used by test 9
  ([../testing/9-session-status-test.md](../testing/9-session-status-test.md)) to seed a deliberately stale session
  for `example.org`, `saved_at` set far outside the auth TTL so the `expired` branch of `session/status` is
  reachable without waiting 14 days for one to lapse naturally. Test 9's `active`-branch call needs a `saved_at` of
  "now" instead, which can't be a committed fixture without going stale immediately, so that JSON is built inline
  in the spec's Run section rather than checked in here.

Reserved for future tests that might need canary content, e.g. a small static HTML page hosted under
`fixtures/static/` for an extraction-tier regression test against a known body.

## Fake site (`../fake-site/`)

The shared deterministic fake site of design D11 (`add-web-search-scraping-e2e`).
Starlette app `../fake-site/app.py`, image `../fake-site/Dockerfile`, fixture
bytes once in `../fake-site/files/`.

Loopback port: `7031`. No service in the root `AGENTS.md` uses it (9917, 7017,
7021, 7020, 9998, 7022, 5432, 6379, 6333/6334, 9070/9071, 5001, 9080, 9020, 8191).

Control paths (never written to the request log): `GET /__requests` answers the
log per path (`method`, `path`, `if_none_match`, `if_modified_since`,
`bytes_sent`), `POST /__reset` empties it and restores every page, `POST
/__state` switches a page between present and gone (`{"page", "present"}`) or
the product page between layouts (`{"page": "/product", "layout": 1|2}`).

Canary files (served under `/files/<name>` with the Content-Type below):

| File | Canary text | SHA-256 |
|---|---|---|
| `canary.pdf` (`application/pdf`) | The HELIX-FINCH memorandum approves 12 rooftop hives above the Meridian depot for spring. | `2bc862e020ebc64fff60bafefa8361b8338520452966184963061cb427851241` |
| `canary.png` (`image/png`) | Mirellion | `812413e7bdf1429ae43e0d4c3009ddd4c015d6aade57854c5be606a41aca95d4` |
| `canary.zip` (`application/zip`) | CINDER-SPARROW cache holds 23 brass tokens under the north pier. | `226b8b2d11993649dcf17d3401389e49c5ca35c5f04ba9a0a786d1c4549655e1` |
| `clean-doc.docx` (Office, no macro part) | The LUMEN-BADGER protocol rests dough for 47 minutes before the second fold. | `c1d045f1b76bc36de0fa88697506ea2bce1a46ab8620f6ef2ad33695ee8f438b` |
| `macro-doc.docm` (Office, holds `word/vbaProject.bin`) | The LUMEN-BADGER macro memo signs permits after 47 minutes of review. | `afb8135937e3fd4f6f4171c9e433ab249c11a80065359494383ae037616b60e3` |
| `circuit.kicad_sch` (`text/plain`) | KICAD-CANARY net CLASS_47 assigns 0.35 mm track width to the Mirell bus. | `60ee0a22df6091f0dfa1968e2b45b18e33bbe942ff8e44f3b578818d1a9b0f18` |
| `firmware.elf` (`application/octet-stream`, `\x7fELF` header) | ELF-CANARY build 7731 for board Mirell-revC | `d64f1c87379dedcb2ac9e533207e43b343c885c364ac076adb438b99358f0a05` |

Canary pages (all `text/html; charset=utf-8` unless noted): `/` index,
`/article` (QUARRY-THRUSH survey, 47 nesting pairs), `/product` (JSON-LD
Brassbound Meridian Astrolabe, 847.25 USD, layout 2 via `/__state`),
`/product-broken` (malformed JSON-LD), `/tables` (SKU-1147/2203/3318),
`/js-only` (NIGHT-HERON ledger, 11 lanterns, script-injected only),
`/captcha-wall` (long article plus `#captcha-widget`), `/prompt-injection`
(secret canary MOTH-SECRET-99, never a spec expectation),
`/redirect-1` to `/redirect-2` to `/article` (302 chain),
`/redirect-blocked` (302 to the blocked name), `/private-image` (img from the
blocked name), `/script-nav` (script sets `window.location` to the blocked
name), `/crawl/` sitemap tree down to `/crawl/a/b/c` plus `/crawl/outside` and
`/crawl/blocked-link`, `/crawl/disallowed` (see `/robots.txt`), `/wall-ko`
(Korean captcha), `/wall-tr` (Turkish login), `/wall-header` (403 plus
`cf-mitigated: challenge`), `/article-ja`, `/article-ar`, `/prose-captcha`
(word captcha in prose only), `/rich-403` (403 rich body), `/robots.txt`
(`text/plain`, disallows `/crawl/disallowed`), `/sitemap.xml`
(`application/xml`), `/oversized-declared` (large body with `Content-Length`),
`/oversized-undeclared` (chunked, no `Content-Length`), `/slow` (streams one
chunk per second, no `Content-Length`).
