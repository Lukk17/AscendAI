# Challenge detection

How the service tells a challenge wall from real content, in any language.

## The verdict

`assess(status_code, html, headers, cookie_names)` in
`src/reader/cloudflare/challenge_signals.py` returns one frozen
`ChallengeVerdict`: a score, the threshold, every fired signal, the vendor,
`wall`, `has_content` and the `intervention_type` (`captcha`, or `login`
when the dominant form carries a password input). Every tier and the NoVNC
monitor share the one function, so no two callers can disagree about the
same page. `is_blocked`, `has_real_content` and `is_content_accepted` keep
their names and read the verdict. A signal fires at most once per verdict.

## The families

| Family | Signals | What it reads |
| :--- | :--- | :--- |
| A vendor | `definitive_header` 200, `interstitial_structure` 80, `vendor_script` 60, `vendor_presence` 30 | Response headers, cookie names, vendor script hosts and challenge-page markers. Language-independent. |
| B HTTP | `status_empty_body` 200, `status_small_body` 50, `status_large_body` 20 | Status 403, 429 or 503 crossed with empty, small and large bodies. |
| C structure | `captcha_input` 50, `captcha_element` 40, `form_dominance` 40, `script_only_body` 40 | Element names and attribute values over the parsed prefix, never text. |
| D shape | `thin_text` 20, `few_links` 20, `no_article` 20, `rich_content` -60, `many_links` -20 | One trafilatura extraction plus link and element counts. The two negative guards keep real articles out of walls. |
| E phrases | `phrase_title` 60, `phrase_body` 30 | Catalogue phrases, matched after normalisation. A supplement only. |

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
`status_empty_body` may reach the threshold alone, `rich_content` and
`many_links` must not be positive, no other weight may be negative, and
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
  login page with a captcha (expected wall, type login), articles in `en`,
  `pl`, `de`, `ja` and `ar`, a 404, a 403 with a large real body, and a
  script-only shell.
- No file exceeds 200 kilobytes. Inline script bodies are trimmed to 200
  characters; attributes are never trimmed.
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
