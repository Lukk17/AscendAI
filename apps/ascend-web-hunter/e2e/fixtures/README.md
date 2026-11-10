# e2e fixtures

ascend-web-hunter tools (`web_search`, `web_read` via MCP; `/api/v1/web/search`, `/api/v2/web/read` via REST) take
string arguments only - no file uploads.

- `session-clear-seed.json` - a synthetic minimal `storage_state` record used by test 8
  ([../testing/8-session-clear-test.md](../testing/8-session-clear-test.md)) to seed a session for `example.net`
  directly in Redis, without a login flow, a browser tier, or a human. `docker cp`'d into the `redis` container and
  loaded via `redis-cli -x SETEX ... < file`, since piping the JSON through a shell pipe corrupts it (PowerShell
  prepends a BOM, bash treats a bare quoted string as a command).
- `session-status-expired-seed.json` - the same kind of synthetic `storage_state` record, used by test 9
  ([../testing/9-session-status-test.md](../testing/9-session-status-test.md)) to seed a deliberately stale session
  for `example.org`, `saved_at` set far outside the auth TTL so the `expired` branch of `session/status` is
  reachable without waiting 14 days for one to lapse naturally. Test 9's `active`-branch call needs a `saved_at` of
  "now" instead, which can't be a committed fixture without going stale immediately, so that JSON is built inline
  in the spec's Run section rather than checked in here.
- `session-import-mixed.json` - the full `POST /api/v2/web/session/import` request body used by test 17
  ([../testing/17-session-import-test.md](../testing/17-session-import-test.md)): a Playwright `storage_state`
  with two `example.net` cookies carrying canary values and one `example.org` cookie, so the import keeps two,
  drops one, and stores provenance `import`. Bruno does not read this file: the request file
  `docs/api/request/AscendAI/web-hunter/testing/session-import/import-mixed.yml` carries the same body inline, so
  change both together.

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
| `canary.mp3` (`audio/mpeg`, 1.2 s, one invented word spoken once) | Kaksma | `4aab0d72746265c100b3c13472fe30cef61780eaba3b26743c4ca3219f84e49f` |
| `oversized.pdf` (`application/pdf`, declared `Content-Length` 52428801, no body bytes sent) | The QUASAR-WREN memorandum files 52428801 blank pages under seal. | `5f2adbaa0ffd1f749efa1716f48b716763538a535fd8ec230cd4f3fd5b3f73a2` |

`canary.mp3` speaks its word once, generated with
`espeak -v en -s 130 -w canary.wav "kexmar"` plus `lame canary.wav
canary.mp3`. The declared word is Kaksma: ascend-audio-scribe
(`POST /api/v1/transcribe/local`, `stream=false`) transcribes the clip as
"KAKSMA", verified twice on 2026-10-19.

Canary pages (all `text/html; charset=utf-8` unless noted): `/` index,
`/article` (QUARRY-THRUSH survey, 47 nesting pairs), `/product` (layout 1, the
default: the name Brassbound Meridian Astrolabe alone in `h1.product-name`, the
price 847.25 alone in `span.price` with `USD` in its own `span.currency`, plus
JSON-LD and a description sentence that names the product, so one CSS selector per
field replays each value and spec 15 can store and replay a recipe. Layout 2 via
`/__state` changes the markup: the name in an `h2`, the price inside the sentence
`Priced at 847.25 USD.` of `p.stock-price`, so layout 1's selectors match nothing
and no selector can replay the price. Both layouts carry the SKU canary
`MRD-4471-QUILL`, in `span.sku` on layout 1 and in `p.stock-sku` on layout 2, a
value no cached answer of another schema holds, so spec 15's `sku` read proves it
read the live page),
`/product-broken` (malformed JSON-LD), `/tables` (SKU-1147/2203/3318),
`/js-only` (NIGHT-HERON ledger, 11 lanterns, script-injected only),
`/captcha-wall` (Mirell field-notes blog of 190+ extracted words with a
reCAPTCHA `g-recaptcha` widget under its comment form, keeps the
QUARRY-THRUSH canary), `/prompt-injection` (real page values Brassbound Meridian Astrolabe, 847.25 USD
beside the injection text; secret canary MOTH-SECRET-99 in the text, never a
spec expectation),
`/redirect-1` to `/redirect-2` to `/article` (302 chain),
`/redirect-blocked` (302 to the blocked name), `/private-image` (img from the
blocked name), `/script-nav` (script sets `window.location` to the blocked
name), `/crawl/` link tree down to `/crawl/a/b/c` plus `/crawl/outside` and
`/crawl/blocked-link`, `/crawl/disallowed` (see `/robots.txt`),
`/crawl/a-sitemap-only` (no page links to it, only `/sitemap.xml` lists it, canary
`The KESTREL-BUOY register lists 19 marker buoys moored off the Mirell south point.`), `/wall-ko`
(Korean captcha: captcha image, `captcha_answer` text input, the Korean phrase
`로봇이 아님을 확인하십시오. 계속하려면 상자를 선택하십시오.`, no vendor marker),
`/wall-tr` (Turkish login: the sentence `Giriş yapmak için kutuyu işaretleyin.`
with a password input and a `captcha` input), `/wall-header` (403 plus
`cf-mitigated: challenge`, body `Full article text behind the wall.`),
`/wall-vendor-thin` (thin page whose only vendor marker is the catalogued
DataDome script `js.datadome.co/tags.js`, body `Loading, please wait.`),
`/wall-oversized` (recaptcha vendor script inside the first
`CHALLENGE_DETECTION_MAX_BYTES` with a body longer than that, canary
`Type the letters shown in the image above to continue.`),
`/turnstile-wall` (thin page with a `cf-turnstile` div and no script, canary
`Please confirm you are human to continue.`),
`/article-ja` (Japanese survey article of a dozen paragraphs with a six-link
archive nav, keeps `QUARRY-THRUSHの調査で47組の営巣を確認した。`),
`/article-ar` (Arabic survey article of seven paragraphs with a six-link
archive nav, keeps `سجل مسح QUARRY-THRUSH 47 زوجا معششا.`),
`/prose-captcha` (QUARRY-THRUSH canary plus `The essay uses the word captcha
only as prose.`), `/rich-403` (403, members article of ten paragraphs with a
22-link archive nav, keeps `Long rich member article text.`),
`/robots.txt` (`text/plain`, disallows `/crawl/disallowed`, names the sitemap by its full
address built from the request's `Host`, so `http://e2e-fake-site:7031/sitemap.xml` inside the
network), `/sitemap.xml` (`application/xml`, lists `/crawl/`, `/crawl/a`, `/crawl/outside` and
`/crawl/a-sitemap-only` by their full addresses, never a page deeper than depth 1 by links, because
a sitemap address enters the crawl at depth 1), `/oversized-declared` (large body with `Content-Length`),
`/oversized-undeclared` (chunked, no `Content-Length`), `/slow` (streams one
chunk per second, no `Content-Length`), `/pdf-link-blocked` (its own canary
sentence plus a `.pdf` link to `http://e2e-fake-site-blocked:7031/files/canary.pdf`).

The challenge pages above live as one file each under `../fake-site/pages/`
(served unchanged by `../fake-site/app.py` with the status and headers named
here) and are judged by the unit test
`tests/reader/cloudflare/test_fake_site_verdicts.py`, which runs `assess` over
every file: wall verdicts for `/wall-ko` (`captcha`), `/wall-tr` (`login`),
`/wall-vendor-thin`, `/wall-header`, `/wall-oversized` and `/turnstile-wall`,
content verdicts for `/captcha-wall`, `/article-ja`, `/article-ar`,
`/prose-captcha` and `/rich-403`.
