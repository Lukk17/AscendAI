# Challenge wall fixture corpus

Pages with known verdicts. The corpus test runs every fixture through
`assess` with its recorded status, headers and cookie names and asserts the
expected verdict, the expected type and the must and must-not signals. It
also runs every fixture through `ChallengeDetector.login_wall_verdict` with
its `source_url` as the requested address and its `final_url` (the
`source_url` when the entry has none) as the address the read ended at, and
asserts `expected.login_wall` (a scored wall of type `login` when the entry
has none). An entry of kind `login_wall` is a page a read was redirected to
for a login: the score alone keeps it content and only its `final_url` makes
it a login wall.

## Capture rules

- Capture, don't craft: every non-synthetic fixture is a response a real
  page served, fetched with `curl`, `curl_cffi` or Playwright on the date in
  its manifest entry. No fixture is typed from memory.
- No file exceeds 200 kilobytes. Inline script bodies are trimmed to their
  first 200 characters; attributes are never trimmed, because every marker in
  the catalogue lives in an attribute, a header or a short text node. Inline
  style bodies are trimmed to their first 200 characters too in captures from
  2026-11-07 on. Older real captures keep their style bodies, because trimming
  them would move the byte offsets the raw prefix of family A reads.
- No secrets: no cookie value, no `cf_clearance` or `datadome` token, no
  session content, no personal data. Token values that a real capture cannot
  avoid (the DataDome device cookie echoed in the Allegro block page) are
  replaced with `REDACTED`, recorded in the entry's notes. A test greps every
  fixture for the catalogue cookie names followed by `=` and a value.
- A fixture is `synthetic: true` only when no public page served that
  vendor's wall, it is built from the cited markers alone, and its vendor is
  listed under "Synthetic fixtures" below. When a spec 7 run records a real
  wall from a vendor that has a synthetic fixture, the run's raw response is
  captured into the corpus and the synthetic entry is replaced in the same
  commit: no two wall entries for one vendor where one is synthetic. A real
  counterexample may sit beside the synthetic wall, because it captures the
  opposite verdict and cannot mask it.
- Rendered captures (Playwright) record the initial response's status and
  headers and the context's cookie names, because a challenge that clears on
  its own changes the body and the cookies but not the headers of the
  response that started it.

## Known gaps

- No public page serving only a Friendly Captcha widget was found, so that
  vendor has no wall fixture. Measured 2026-11-03 with one GET per page in a
  throwaway container: `docs.friendlycaptcha.com` scores 60 raw and 40
  rendered, `developer.friendlycaptcha.com` 60, `app.friendlycaptcha.com`
  and `app.friendlycaptcha.eu` 80, the GitHub Pages shell 60, and
  `friendlycaptcha.com/demo` still redirects to the rich playground that is
  already the counterexample. Every one of them stays below the threshold.
- The DataDome `vendor_script` markers stay unfired: block pages never
  include the tag script. Re-verified 2026-10-26 against the `g2.com` and
  `github.com/signup` blocks, which carry only `captcha-delivery.com`.
  A readable DataDome-tagged page would pin them; none was found.
- `nowsecure-rendered.html` is kind `wall` by design Decision 2 row 12 (a
  thin Turnstile shell scores above the threshold): the deliberate cost of
  the 150-word guard, accepted by spec 7 row n as `{success, intervention}`.
- The Amazon button-variant pages serve no captcha input, so their entries
  assert no `captcha_input`; the character-entry variant carries it.
- No real 403 with a large real body is in the corpus. The page filed as
  that counterexample until 2026-11-07 (`rich-403.html`, captured from
  `https://old.reddit.com/login/`) was Reddit's "You've been blocked by
  network security" page and is now the wall
  `reddit-network-block-403.html`. Probed on 2026-11-07 for a genuine article
  served with 403, none found: `ft.com` and `theatlantic.com` answer with
  vendor block pages, `wsj.com` and `barrons.com` with DataDome walls,
  `sciencedirect.com` with a Cloudflare error page, and `quora.com`,
  `medium.com`, `indeed.com`, `imdb.com`, `trustpilot.com` and several
  journal sites with block pages or 200 answers. Until one is found, the e2e
  fake-site page `e2e/fake-site/pages/rich-403.html` holds the guard through
  `tests/reader/cloudflare/test_fake_site_verdicts.py`.

## Synthetic fixtures

The vendors whose only wall fixture is synthetic. The corpus test reads this
list and fails when it and the `synthetic: true` entries of `manifest.json`
disagree, so replacing a synthetic fixture with a real capture removes its
line here in the same commit. The list was first recorded in Open Question 4
of the archived change design
`openspec/changes/archive/2026-11-03-detect-challenge-walls-in-any-language/design.md`.

- `akamai`
- `imperva`
- `kasada`
- `perimeterx`
- `ddos_guard`
- `aws_waf`
- `friendly_captcha`
