# Challenge detection

How the service tells a challenge wall from real content, in any language.

## The verdict

`assess(status_code, html, headers, cookie_names)` in
`src/reader/cloudflare/challenge_signals.py` returns one frozen
`ChallengeVerdict`: a score, the threshold, every fired signal, the vendor,
`wall`, `has_content` and the `intervention_type` (`captcha`, or `login`
when the dominant form carries a password input). Every tier and the NoVNC
monitor share the one function, so no two callers can disagree about the
same page. The read path and the NoVNC monitor accept a page through the
verdict's `accepted` field. `is_blocked` and `has_real_content` keep their
names and read the verdict. A signal fires at most once per verdict.

`ChallengeDetector.login_wall_verdict` decides once for every read tier, the
static tiers and the browser tiers alike, whether a page is a login wall. A
scored wall of type `login` is one. A read that ended on a login path is one
too: every tier passes the address it asked for and the address the read
ended at (after redirects, and in a browser after any later navigation), and
when a path segment of the final address, without its file extension, is one
of the `login_path_segments` in `challenge_dictionary.json` (`login`,
`log-in`, `signin`, `sign-in`, `logon`) while no segment of the requested
address is, and a second login sign holds, the page is a login wall at any
size and whatever its title, score or rich content. The second sign is a
query parameter of the final address named in `login_return_parameters`
(`next`, `dest`, `return_to`, `returnTo`, `redirect`, `redirect_uri`,
`continue`, `from`, compared without case), or a password input on the page
(`has_password_input` in `src/reader/cloudflare/challenge_detector.py`, which
reads every input tag in one linear pass over the markup, and which the NoVNC
monitor reads too through this rule). So an anonymous read of
`https://old.reddit.com/r/programming/` that the site redirects to
`https://old.reddit.com/login/?reason=lor2&dest=...`, a 200 page titled
"Welcome to Reddit" that scores 60, is a login wall. GitHub
(`/login?return_to=...`) and Instagram (`/accounts/login/?next=...`),
measured on 2026-11-07, land the same way. A redirect to
`/en/login/reset-password` or `/docs/login/sso-setup` with neither sign, an
article that only links to its login page, and a read that asked for the
login page itself are judged by the other rules.

A verdict made by this landing rule carries `login_landing` true. The read
ladder in `src/reader/web_reader.py` then stops climbing, because every
anonymous tier lands on the same login page: with the human tier allowed it
goes straight to `6-novnc`, which answers 428 with the type `login`, and
without it (a crawl) the read ends with `status` `error` and `reason`
`login_required`. The NoVNC monitor counts a landing page, and an address
that matches a login redirect pattern, as a login page until the window has
seen a login wall. After that such an address is a login page only when its
origin and path equal a login address the window already saw as a wall, so a
window that stays on `https://old.reddit.com/login/` stays a login page,
whatever its query, while a finished login whose site ends on a callback such
as `/login/callback?next=...` or `/signin/callback` can resolve. The monitor
also finds a visible password input with Playwright's locator
`input[type=password]:visible`, which reaches into open shadow roots, so a
login form drawn by a web component, as on Reddit, keeps the page a login
page. A hidden password input does not count, so a finished login whose page
keeps a hidden password field can resolve. A cookie the site sets by itself
while the login page still shows is therefore never a new login.

A page whose `<title>` matches one of the
`login_title_patterns` in `challenge_dictionary.json` is one too, unless the
verdict carries the `rich_content` signal (at least
`CHALLENGE_RICH_CONTENT_WORDS` extracted words, 150 by default). So a "Sign
in" page with a short form is a login wall, and an article titled "Login -
Wikipedia" is content. The title rule does not apply to a page larger than
`CHALLENGE_SHAPE_MAX_BYTES`, because the shape family, and with it
`rich_content`, never runs on such a page: a 600 KB article titled "Log in
to read more" is content. A scored wall of type `login` stays a login wall
at any size. A login wall is raised with the type `login`, and the
read escalates toward the NoVNC window. Any other page is judged by the
score alone.

`challenge_verdicts_total{verdict,tier}`,
`challenge_signals_fired_total{signal,vendor}` and the `challenge_score`
histogram record one verdict per read for each read tier. The NoVNC monitor
rechecks its page every `NOVNC_COOKIE_SYNC_POLL_SECONDS` while it waits for a
human and logs each check, but records only the last one in all three
metrics, once per window when the window ends, with the verdict under the tier
`novnc-monitor`. A window that never checked a page records nothing.

## The families

| Family | Signals | What it reads |
| :--- | :--- | :--- |
| A vendor | `definitive_header` 200, `interstitial_structure` 80, `vendor_script` 60, `vendor_presence` 30 | Response headers, cookie names, vendor script hosts and challenge-page markers. Language-independent. |
| B HTTP | `status_empty_body` 200, `status_small_body` 50, `status_large_body` 20 | Status 403, 429 or 503 crossed with empty, small and large bodies. |
| C structure | `captcha_input` 50, `captcha_element` 40, `form_dominance` 40, `script_only_body` 40 | Element names and attribute values over the parsed prefix, never text. |
| D shape | `thin_text` 20, `few_links` 20, `no_article` 20, `rich_content` -70, `many_links` -20, `served_page` -30 | One trafilatura extraction plus link and element counts. The first two negative guards keep real articles out of walls. `served_page` fires on a page answered 200 whose only challenge evidence is `vendor_script` or `vendor_presence`, the page a cleared challenge lands on. |
| E phrases | `phrase_title` 60, `phrase_body` 30 | Catalogue phrases, matched after normalisation. A supplement only. |

The parsed prefix that families C and E read is the first
`CHALLENGE_DETECTION_MAX_BYTES` (50000 by default) of the page after two
cuts made inside the first `CHALLENGE_SHAPE_MAX_BYTES`: every inline
`<style>` body is emptied, and every attribute value that starts with
`data:` is cut to `data:`. Neither carries visible text, and without the
cuts a large inline stylesheet or an inline image pushes the page's text out
of the prefix. Reddit's 403 block page is the measured example: its sentence
"You've been blocked by network security" sits at byte 189316, behind
inline styles and an 87552-byte inline image. Family A still reads the raw
prefix, because vendor markers live in script tags and attributes.

The threshold is 100. No non-definitive signal reaches it alone, so a wall
verdict always rests on at least two independent pieces of evidence. The two
definitive signals (`definitive_header`, `status_empty_body`) weigh twice
the threshold so no combination of guards can cancel them.

## Tuning settings

| Setting | Default |
| :--- | :--- |
| `CHALLENGE_SCORE_THRESHOLD` | `100` |
| `CHALLENGE_RICH_CONTENT_WORDS` | `150` |
| `CHALLENGE_FORM_DOMINANCE_RATIO` | `0.6` |
| `CHALLENGE_MIN_WORDS_PER_KB` | `2.0` |
| `CHALLENGE_THIN_LINK_COUNT` | `5` |
| `CHALLENGE_RICH_LINK_COUNT` | `20` |
| `CHALLENGE_SHAPE_MAX_BYTES` | `500000` |

## Weight settings and the validator

One `CHALLENGE_WEIGHT_<SIGNAL>` setting per signal, with the table weights
above as defaults. The settings validator keeps the scoring rules true for
any values: `CHALLENGE_WALL_MAX_BYTES` must not exceed
`CHALLENGE_SHAPE_MAX_BYTES`, no weight other than `definitive_header` and
`status_empty_body` may reach the threshold alone, `rich_content`,
`many_links` and `served_page` must not be positive, no other weight may be
negative, and
`CHALLENGE_THIN_LINK_COUNT` must not exceed `CHALLENGE_RICH_LINK_COUNT`.

Warning: changing a weight or the threshold without re-running the corpus
test (`tests/reader/cloudflare/test_challenge_corpus.py`, task 9.1) is
guessing. The corpus margin table shows how close every fixture sits to the
line.

## Capture rules

`tests/fixtures/challenge_walls/` holds the fixture pages and
`manifest.json` describes them. The rules, enforced by tests:

- Every vendor in the catalogue has at least one wall fixture, and every
  `vendor_script`, `interstitial_structure` and `definitive_header` marker
  is fired by at least one fixture.
- Cloudflare and Amazon have one fixture per captured language, and every
  catalogue translation is fired by at least one of them.
- Counterexamples pin the guard: a blog post with a comment-form captcha, a
  Turnstile widget beside real text, a vendor page beside real content, a
  login page with a captcha (expected wall, type login), a subreddit read
  redirected to its login page (kind `login_wall`, a login wall only through
  its `final_url`), articles in `en`,
  `pl`, `de`, `ja` and `ar`, a 404, and a script-only shell. A 403 with a
  large real body has no real capture: the one filed until 2026-11-07,
  `rich-403.html`, was Reddit's network security block page and is now the
  wall `reddit-network-block-403.html`. The e2e fake-site page
  `e2e/fake-site/pages/rich-403.html` holds that guard through
  `tests/reader/cloudflare/test_fake_site_verdicts.py` until a public
  article served with 403 is found (see "Known gaps" in
  `tests/fixtures/challenge_walls/README.md`).
- No file exceeds 200 kilobytes. Inline script bodies are trimmed to 200
  characters; attributes are never trimmed. Inline style bodies are trimmed
  to 200 characters too in captures from 2026-11-07 on. Older real captures
  keep their style bodies, because trimming them would move the byte offsets
  the raw prefix of family A reads.
- No fixture carries a cookie value, a token, session content or personal
  data.
- A fixture is `synthetic: true` only when no public page served that
  vendor's wall; it is replaced with a real capture in the same commit when
  a spec 7 run records one.

## Phrase by language, captured 2026-10-19

`en` is the canonical English every phrase carries. `x` marks a captured
translation; an empty cell is a language with no captured translation for
that phrase, left visible rather than guessed at. Printed by
`tests/reader/cloudflare/test_challenge_dictionary.py`.

| phrase | bg | hr | cs | da | nl | en | et | fi | fr | de | el | hu | it | lv | lt | pl | pt | ro | sk | sl | es | sv | uk | ru | tr | ja | ko | zh-Hans | zh-Hant | ar |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| cf_just_a_moment |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| cf_checking_connection |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| cf_attention_required |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| cf_verify_human |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| generic_prove_humanity |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| generic_verify_you_are_human |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| generic_not_a_robot |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  | x |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| generic_enable_js_adblock |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| datadome_captcha |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| imperva_pardon_interruption |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| amazon_type_characters |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| amazon_enter_characters |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| amazon_continue_shopping |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| akamai_access_denied |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| perimeterx_automation_tools |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| ddosguard_title |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
| generic_blocked_by_network_security |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |  |
