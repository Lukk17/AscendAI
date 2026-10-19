# Challenge wall fixture corpus

Pages with known verdicts. The corpus test runs every fixture through
`assess` with its recorded status, headers and cookie names and asserts the
expected verdict, the expected type and the must and must-not signals.

## Capture rules

- Capture, don't craft: every non-synthetic fixture is a response a real
  page served, fetched with `curl`, `curl_cffi` or Playwright on the date in
  its manifest entry. No fixture is typed from memory.
- No file exceeds 200 kilobytes. Inline script bodies are trimmed to their
  first 200 characters; attributes are never trimmed, because every marker in
  the catalogue lives in an attribute, a header or a short text node.
- No secrets: no cookie value, no `cf_clearance` or `datadome` token, no
  session content, no personal data. Token values that a real capture cannot
  avoid (the DataDome device cookie echoed in the Allegro block page) are
  replaced with `REDACTED`, recorded in the entry's notes. A test greps every
  fixture for the catalogue cookie names followed by `=` and a value.
- A fixture is `synthetic: true` only when no public page served that
  vendor's wall, it is built from the cited markers alone, and it is listed
  in Open Question 4 of the change design. When a spec 7 run records a real
  wall from a vendor that has a synthetic fixture, the run's raw response is
  captured into the corpus and the synthetic entry is replaced in the same
  commit: no two entries for one vendor where one is synthetic.
- Rendered captures (Playwright) record the initial response's status and
  headers and the context's cookie names, because a challenge that clears on
  its own changes the body and the cookies but not the headers of the
  response that started it.

## Known gaps

- No public thin page serving only a MTCaptcha, Friendly Captcha or Arkose
  widget was found; those vendors have no wall fixture yet. Their script
  markers are fired by the vendor-content counterexamples.
- No public blog post pairing a real article with a reCAPTCHA comment form
  was found; the Turnstile and hCaptcha vendor pages pin the same property.
- No public login page pairing a password form with a captcha was found; the
  password-input classifier is pinned by unit tests instead.
- `nowsecure-rendered.html` is kind `wall` by design Decision 2 row 12 (a
  thin Turnstile shell scores above the threshold): the deliberate cost of
  the 150-word guard, accepted by spec 7 row n as `{success, intervention}`.
- The Amazon button-variant pages serve no captcha input, so their entries
  assert no `captcha_input`; the character-entry variant carries it.
