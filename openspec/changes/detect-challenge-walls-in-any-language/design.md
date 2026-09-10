## Context

Detection lives in `apps/ascend-web-hunter/src/reader/cloudflare/challenge_detector.py` and is called from eight
places: `curl_cffi_fetcher.py` (tiers 1 and 2), `playwright_strategy.py` (tier 4, four calls, two of them inside a
poll loop that waits `CHALLENGE_CLEAR_WAIT_SECONDS` for a Cloudflare challenge to clear on its own),
`flaresolverr_strategy.py` (tier 3), `crawlee_strategy.py` (tier 5), `novnc_strategy.py` (the monitor's
`_poll_captcha`, which decides when a human has cleared a page), and `web_reader.py` (the second line of defence in
`_execute_strategy` and `_execute_html_strategy`, which only has the HTML because `get_html` returns a string).

The decision is `is_content_accepted(status, html)`, defined as not `is_blocked` and `has_real_content`.
`is_blocked` is a substring search over a 50 000 byte prefix for the entries of `challenge_dictionary.json`, a
`Ray ID:` regex, and three weak substrings gated on page size. `has_real_content` runs trafilatura on pages under
50 000 bytes and accepts ten words. Every call site except the curl tier passes a hard-coded status of 200, and no
call site passes a header, so the one language-independent signal every fetch already has in hand, the response
headers, is thrown away before the detector sees it.

The dictionary is hand-typed. It has four script signatures, eleven phrases in two languages, one structural marker
whose path may not be the path Amazon serves, and five English login title patterns. The tests patch the dictionary
with synthetic entries and synthetic pages, so nothing in the suite pins the behaviour against a page a vendor
actually served.

The requirement this change answers is that a wall is recognised in any language. That fixes the order of evidence.
First, what a wall cannot translate: the vendor's script, cookie and header names, the HTTP status, the shape of the
page. Then, and only as a supplement, what it says.

## Goals

- A wall from any vendor in the catalogue, and a site's own captcha from no vendor at all, is a wall in any language.
- A page carrying a real article beside a captcha widget is content, not a wall.
- One decision function, with one score and one threshold, shared by every tier and by the monitor, so no two callers
  can disagree about the same page.
- Every marker in the catalogue has a source, and every marker has a fixture that fires it.
- An operator can see which signal decided a page and how close the score came to the line.

## Non-Goals

- Solving anything. The verdict feeds the escalation that exists.
- Per-domain or per-vendor tuning.
- Language coverage for the login title patterns beyond the password-input classifier.
- Any change to the 428 body, the 409 body, the session store, or the tier order.

## Decisions

### Decision 1: A scored verdict replaces four booleans

`ChallengeDetector.assess(status_code, html, headers=None, cookie_names=())` returns a frozen `ChallengeVerdict`:

```python
@dataclass(frozen=True)
class FiredSignal:
    id: str          # for example "vendor_script", "captcha_input", "rich_content"
    family: str      # "vendor", "http", "structure", "shape", "phrase"
    weight: int      # may be negative for a guard
    vendor: str | None
    evidence: str    # the marker that matched, never a page excerpt

@dataclass(frozen=True)
class ChallengeVerdict:
    score: int
    threshold: int
    signals: tuple[FiredSignal, ...]
    vendor: str | None
    wall: bool             # score >= threshold, or a definitive signal fired
    has_content: bool      # the VALIDATION_MIN_WORDS floor, unchanged from today
    intervention_type: str # "login" when the dominant form has a password input, else "captcha"

    @property
    def accepted(self) -> bool:
        return not self.wall and self.has_content
```

`is_blocked`, `has_real_content` and `is_content_accepted` keep their names and signatures, gain optional `headers`
and `cookie_names`, and read the verdict. `is_login_required` and `is_login_redirect_url` are untouched. That is what
lets the eight call sites keep compiling on day one while each is moved, one task at a time, to pass what it has.

A signal fires at most once per verdict, however many markers matched it. Two reCAPTCHA scripts on one page are one
`vendor_script`. Every fired signal is kept on the verdict so the log line, the metric and the test can name it.

Rejected: a boolean per new signal added beside the existing ones. Eight call sites already combine three booleans
with `and` and `not`, and each new signal would have to be threaded through all eight with a decision about how it
combines. A score is one number with one comparison, and the combination rule lives in one place.

Rejected: a machine-learned classifier. It would need the corpus this change builds before it could be trained, it
could not say which marker decided a page, and a vendor changing its markup would degrade it silently. The
catalogue plus a score can be read, tested and corrected by hand.

### Decision 2: Five signal families, with the language-independent ones first

The weights are module constants in `challenge_signals.py`, not settings. They are relative to each other and to
`CHALLENGE_SCORE_THRESHOLD`, and changing one without re-running the corpus is guessing. The corpus test in task 9.1
is the place a weight changes.

Family A, vendor signatures. All language-independent.

| Signal | Weight | Fires when |
| :-- | :-- | :-- |
| `definitive_header` | 200 | A response header the vendor documents as present only while serving a challenge: `cf-mitigated: challenge` (Cloudflare), `x-amzn-waf-action: challenge` or `captcha` (AWS WAF). |
| `interstitial_structure` | 80 | A marker that appears only on the vendor's own challenge or block page, never on a page that merely hosts its widget. One per vendor, listed in Decision 3. |
| `vendor_script` | 60 | A vendor's challenge or widget script host and path in the prefix. |
| `vendor_presence` | 30 | A vendor's server string, response header or cookie name. Says the vendor is in the path, not that it blocked. |

Family B, HTTP evidence.

| Signal | Weight | Fires when |
| :-- | :-- | :-- |
| `status_empty_body` | 200 | 403, 429 or 503 with an empty body. Today's behaviour, kept verbatim. |
| `status_small_body` | 50 | 403, 429 or 503 with a body under `CHALLENGE_WALL_MAX_BYTES`. |
| `status_large_body` | 20 | 403, 429 or 503 with a larger body. |

Family C, page structure. Computed with lxml on the first `CHALLENGE_DETECTION_MAX_BYTES` of the page. Every test
is on an attribute value or an element name, never on text.

| Signal | Weight | Fires when |
| :-- | :-- | :-- |
| `captcha_input` | 50 | An `input` or `textarea` whose `name`, `id` or `autocomplete` contains `captcha`. Covers `captchacharacters`, `g-recaptcha-response`, `h-captcha-response`, `frc-captcha-solution` and `mtcaptcha-verifiedtoken` without naming them. |
| `captcha_element` | 40 | An element whose `class` or `id` contains `captcha` or starts with `geetest_`, or an `img`, `canvas` or `iframe` whose `src` or `id` contains `captcha`. |
| `form_dominance` | 40 | At least one form exists and the visible text inside forms is at least `CHALLENGE_FORM_DOMINANCE_RATIO` of all visible text in the prefix. |
| `script_only_body` | 40 | A `meta http-equiv="refresh"` in the head, or a body whose visible text is under `VALIDATION_MIN_WORDS` while the page carries at least one `script` and a `noscript`. |

The `intervention_type` classifier lives here and carries no weight: when the verdict is a wall and the form that
dominates the page has an `input type="password"`, the type is `login`, otherwise `captcha`.

Family D, content shape. Uses one trafilatura extraction, the same one `has_real_content` already runs, on pages up to
`CHALLENGE_SHAPE_MAX_BYTES`. Above that the family contributes nothing and the word floor passes automatically, which
is today's rule at a higher bound.

| Signal | Weight | Fires when |
| :-- | :-- | :-- |
| `thin_text` | 20 | Extracted words per kilobyte of HTML is under `CHALLENGE_MIN_WORDS_PER_KB`. |
| `few_links` | 20 | Fewer than `CHALLENGE_THIN_LINK_COUNT` anchors with an `href` in the prefix. |
| `no_article` | 20 | No `article` or `main` element, and extracted words under `CHALLENGE_RICH_CONTENT_WORDS`. |
| `rich_content` | -60 | Extracted words at or above `CHALLENGE_RICH_CONTENT_WORDS`. This is the guard. |
| `many_links` | -20 | At least `CHALLENGE_RICH_LINK_COUNT` anchors with an `href`. |

Family E, phrases. The supplement. Matched after normalisation (NFKC, casefold, punctuation stripped, whitespace
collapsed) so `Just a moment...` and `Just a moment…` are one phrase.

| Signal | Weight | Fires when |
| :-- | :-- | :-- |
| `phrase_title` | 60 | A catalogue phrase is the whole normalised `title`, or the title starts with it. |
| `phrase_body` | 30 | A catalogue phrase appears in the normalised visible text of the prefix. |

The threshold is 100. No non-definitive signal reaches it alone, so a wall verdict always rests on at least two
independent pieces of evidence, and the only single-signal verdicts are the two the vendor documents as meaning
exactly that. A definitive signal weighs twice the threshold so that no combination of guards can cancel it, which
matters because Cloudflare serves the challenge body with the header and the body may be anything.

Worked examples, each computed by the rule above and each pinned by a fixture in section 8 of `tasks.md`:

| Page | Signals | Score | Verdict |
| :-- | :-- | :-- | :-- |
| Cloudflare managed challenge, curl tier, any language | `definitive_header` 200, `status_small_body` 50 | 250 | wall |
| Cloudflare challenge, browser tier after the clear wait, no headers | `interstitial_structure` 80, `thin_text` 20, `few_links` 20, `no_article` 20 | 140 | wall, with no phrase needed |
| GeeTest wall, forty words of explanation in Korean | `vendor_script` 60, `captcha_element` 40, `form_dominance` 40, `thin_text` 20, `few_links` 20, `no_article` 20 | 200 | wall |
| A site's own image captcha in Japanese, no vendor | `captcha_input` 50, `captcha_element` 40, `form_dominance` 40, `thin_text` 20, `few_links` 20, `no_article` 20 | 190 | wall |
| Akamai 403 Access Denied | `status_small_body` 50, `vendor_presence` 30, `interstitial_structure` 80, shape 60 | 220 | wall, 140 without the reference number |
| Kasada 429 with a script-only body | `status_small_body` 50, `vendor_presence` 30, `script_only_body` 40, shape 60 | 180 | wall |
| Amazon captcha page, German, no phrase captured yet | `interstitial_structure` 80, `captcha_input` 50, `captcha_element` 40, `form_dominance` 40, `thin_text` 20, `no_article` 20 | 250 | wall |
| Blog post, 800 words, 40 links, reCAPTCHA under the comment form, rendered | `vendor_script` 60, `captcha_element` 40, `captcha_input` 50, `rich_content` -60, `many_links` -20 | 70 | content |
| Wikipedia article in Arabic | `rich_content` -60, `many_links` -20 | -80 | content |
| Login page with a captcha, Turkish | `captcha_input` 50, `captcha_element` 40, `form_dominance` 40, shape 60 | 190 | wall, type `login` |
| 404 page in German, thirty words | shape 60 | 60 | content, as today |
| A page under 150 words hosting a Turnstile widget beside its text | `vendor_script` 60, `captcha_element` 40, shape 60 | 160 | wall |

The last row is the deliberate cost. A page with under `CHALLENGE_RICH_CONTENT_WORDS` of text whose main feature is a
captcha widget is treated as a wall, and a human opens it once. Spec 7's row n, `nowsecure.nl`, is that page, and its
accept set is already `{success, intervention}`. The guard is set at 150 words rather than lower because every wall
in the catalogue explains itself in well under 150 words and every article the service is asked to read is well over
it. Open Question 1 records that this number is a judgement until the corpus reports the margins.

Rejected: a threshold at 60 with a single vendor script sufficient. That is today's false positive on the blog post.

Rejected: requiring a phrase for any verdict. That is today's false negative in every language but two.

Rejected: weights as settings. Eleven more environment variables whose only safe values are the ones in the table.

### Decision 3: The catalogue carries a source per marker, and unverified markers stay out

Every marker below was checked on 2026-09-10 against the source beside it. Markers that could not be verified against
a vendor page or a maintained detector are listed at the end and are not in the catalogue. Confidence is stated where
the only source is secondary.

| Vendor | Signal | Markers | Source |
| :-- | :-- | :-- | :-- |
| Cloudflare | `definitive_header` | `cf-mitigated: challenge` | https://developers.cloudflare.com/cloudflare-challenges/challenge-types/challenge-pages/detect-response/ |
| Cloudflare | `interstitial_structure` | Element ids and classes `cf-challenge-running`, `cf-please-wait`, `challenge-spinner`, `trk_jschal_js`, `turnstile-wrapper`, `attack-box`, `ray_id`, and the `Ray ID:` text the current detector already matches | https://raw.githubusercontent.com/FlareSolverr/FlareSolverr/master/src/flaresolverr_service.py |
| Cloudflare | `vendor_script` | `challenges.cloudflare.com/turnstile/v0/api.js` | https://developers.cloudflare.com/turnstile/get-started/client-side-rendering/ |
| Cloudflare | `captcha_element` | Class `cf-turnstile` with `data-sitekey` | same page |
| Cloudflare | `vendor_presence` | Header `cf-ray`, header `server: cloudflare`, cookies `cf_clearance`, `__cf_bm` | https://developers.cloudflare.com/fundamentals/reference/policies-compliances/cloudflare-cookies/ and https://raw.githubusercontent.com/EnableSecurity/wafw00f/master/wafw00f/plugins/cloudflare.py |
| DataDome | `interstitial_structure` | `captcha-delivery.com` in the prefix, the host the challenge page loads from. Also observed locally in the Allegro fixture in `tests/reader/cloudflare/test_challenge_detector.py` as `geo.captcha-delivery.com` | https://docs.datadome.co/docs/javascript-tag |
| DataDome | `vendor_script` | `js.datadome.co/tags.js`, `js.datadome.co/` with a version path | same page |
| DataDome | `vendor_presence` | Cookie `datadome`, header `x-dd-b` | https://docs.datadome.co/reference/validate-request and https://docs.datadome.co/docs/manual-integration-1 |
| GeeTest | `vendor_script` | `static.geetest.com/v4/gt4.js`, hosts `gcaptcha4.geetest.com`, `static.geetest.com`, `gcaptcha4.geevisit.com`, `gcaptcha4.gsensebot.com`, `static.geevisit.com` | https://docs.geetest.com/BehaviorVerification/deploy/client/web |
| GeeTest | `captcha_element` | Id or class prefix `geetest_` | same page |
| Akamai Bot Manager | `vendor_presence` | Header `server: AkamaiGHost`, cookies `_abck`, `bm_sz`, `ak_bmsc` | https://raw.githubusercontent.com/EnableSecurity/wafw00f/master/wafw00f/plugins/kona.py for the server string. Cookies from https://scrapfly.io/blog/posts/akamai-bot-manager-understanding-abck-cookies-and-sensor-data and https://blog.crawlex.net/blog/akamai-bot-manager-abck-cookie/, secondary, medium confidence, Akamai's own docs are behind a login |
| Akamai Bot Manager | `interstitial_structure` | `Reference #18.` followed by hex segments, on a 403 | https://www.aethyn.io/blog/what-is-akamai-reference-18-access-denied, secondary, low to medium confidence, admitted only because the fixture pins it and the signal is one of several on that page |
| Imperva Incapsula | `interstitial_structure` | Path `/_Incapsula_Resource`, text `incapsula incident id`, text `powered by incapsula` | https://raw.githubusercontent.com/EnableSecurity/wafw00f/master/wafw00f/plugins/incapsula.py |
| Imperva Incapsula | `vendor_presence` | Cookies matching `incap_ses_` and `visid_incap_`, headers `x-iinfo` and `x-cdn: Incapsula` | same file for the cookies. The two headers from https://www.aethyn.io/solutions/imperva-incapsula-which-engine-blocked-you, secondary, medium confidence |
| Kasada | `vendor_presence` | Response headers `x-kpsdk-ct`, `x-kpsdk-cd` | https://blog.crawlex.net/blog/kasada-kpsdk-token-vm/ and https://www.roolink.io/products/kasada, secondary, Kasada publishes no spec |
| MTCaptcha | `vendor_script` | `service.mtcaptcha.com/mtcv1/client/mtcaptcha.min.js`, `service2.mtcaptcha.com` | https://docs.mtcaptcha.com/dev-guide-quickstart |
| MTCaptcha | `captcha_input` | Hidden input `mtcaptcha-verifiedtoken` | https://docs.mtcaptcha.com/dev-guide-validate-token |
| Friendly Captcha | `vendor_script` | `widget.module.min.js` together with class `frc-captcha` on the same page | https://developer.friendlycaptcha.com/docs/v1/sdk/ |
| Friendly Captcha | `captcha_input` | Hidden input `frc-captcha-solution` | same page |
| Arkose Labs | `vendor_script` | `arkoselabs.com/v2/` with `/api.js`, default host `client-api.arkoselabs.com` | https://arkoselabs.atlassian.net/wiki/pages/viewpage.action?pageId=819905 |
| hCaptcha | `vendor_script` | `js.hcaptcha.com/1/api.js` | https://docs.hcaptcha.com/ |
| hCaptcha | `captcha_element`, `captcha_input` | Class `h-captcha`, field `h-captcha-response` | https://docs.hcaptcha.com/configuration |
| Google reCAPTCHA | `vendor_script` | `www.google.com/recaptcha/api.js`, `www.google.com/recaptcha/enterprise.js`, `recaptcha.net/recaptcha/` | https://developers.google.com/recaptcha/docs/display and https://docs.cloud.google.com/recaptcha/docs/instrument-web-pages |
| Google reCAPTCHA | `captcha_element`, `captcha_input` | Class `g-recaptcha`, field `g-recaptcha-response` | same pages |
| PerimeterX and HUMAN | `interstitial_structure` | Element id `px-captcha`, path `perimeterx.net/whywasiblocked` or `perimeterx.com/whywasiblocked` | https://docs.humansecurity.com/applications/about-enforcers and https://raw.githubusercontent.com/EnableSecurity/wafw00f/master/wafw00f/plugins/perimeterx.py |
| PerimeterX and HUMAN | `vendor_script` | `client.perimeterx.net`, `client.perimeterx.com` | wafw00f plugin above |
| PerimeterX and HUMAN | `vendor_presence` | Cookies `_px3`, `_px2` | https://docs.humansecurity.com/applications/about-enforcers |
| DDoS-Guard | `vendor_presence` | Header `server: ddos-guard`, cookies matching `__ddg1`, `__ddg2`, `__ddgid`, `__ddgmark` | https://raw.githubusercontent.com/EnableSecurity/wafw00f/master/wafw00f/plugins/ddosguard.py |
| Amazon | `interstitial_structure` | Form action `/errors/validateCaptcha`, image host `opfcaptcha-prod.s3.amazonaws.com`, input `captchacharacters` | https://github.com/a-maliarov/amazoncaptcha/issues/40, secondary. Amazon publishes nothing. Task 3.5 measures the live form action before the catalogue commits, and the current dictionary's `/errors_page/validateCaptcha` is carried until then |
| AWS WAF | `definitive_header` | `x-amzn-waf-action: challenge`, `x-amzn-waf-action: captcha` | https://docs.aws.amazon.com/waf/latest/developerguide/waf-captcha-and-challenge-actions.html |
| AWS WAF | `vendor_presence` | Cookie `aws-waf-token` | same page |

Left out because no vendor page or maintained detector confirmed them on 2026-09-10: Cloudflare `__cf_chl_`,
`cf_chl_opt` and `/cdn-cgi/challenge-platform/`, Kasada `KP_UIDz` and its UUID path pattern, Arkose `fc-token` and
`data-pkey`, DataDome `x-datadome` as a browser-facing header, Friendly Captcha's jsDelivr path, PerimeterX
`captcha.px-cdn.net` and the `Press & Hold` label, `X-Recaptcha-Wafdata` from Cloud Armor, and
`autocomplete="one-time-code"`, which two searches tied only to one-time passwords and to no captcha vendor. A marker
enters the catalogue with a source and a fixture or not at all.

One consequence of the sources: Cloudflare's supported-languages reference says the challenge page's displayed
language follows the browser's `navigator.language`, read client-side, not the request's `Accept-Language`. That was a
fetched summary rather than a quoted sentence, so confidence is medium, and task 5.2 confirms it by capture. If it
holds, the curl tier only ever sees the page's default text, and the browser tiers see it in the fingerprint's
locale, so the phrase supplement must be captured through a browser per language and the default text captured
through curl.

### Decision 4: Phrases are generated from a maintained source, and none is typed from memory

`challenge_dictionary.source.json` is the maintained file. `challenge_dictionary.json` is generated from it by
`scripts/generate_challenge_dictionary.py` and committed, and `tests/reader/cloudflare/test_challenge_dictionary.py`
runs the generator in `--check` mode and fails when the committed output differs. A hand edit to the generated file
therefore fails the suite.

The source file has three sections. `vendors` holds the marker table from Decision 3, each marker with its `signal`,
its `source` URL and its `verified_on` date. `phrases` holds the table below, each translation with a `provenance`
object recording the URL it was captured from, the tier or the browser locale it was captured through, and the date.
`login_title_patterns` is carried over verbatim and untouched.

The phrase set. Ids are stable, the English text is the canonical form, and a phrase enters a language only when
captured.

| Id | Canonical English | Where it matches | Origin |
| :-- | :-- | :-- | :-- |
| `cf_just_a_moment` | Just a moment... | title | current dictionary, FlareSolverr `CHALLENGE_TITLES` |
| `cf_checking_connection` | Checking if the site connection is secure | body | current dictionary |
| `cf_attention_required` | Attention Required! | title | current dictionary |
| `cf_verify_human` | Verify you are human | body | Cloudflare managed challenge heading, English text confirmed at capture in task 5.2 |
| `generic_prove_humanity` | Prove your humanity | body | current dictionary |
| `generic_verify_you_are_human` | Please verify you are a human | body | current dictionary |
| `generic_not_a_robot` | Sorry, we just need to make sure you're not a robot | body | current dictionary, with the Polish translation the dictionary already carries |
| `generic_enable_js_adblock` | Please enable JS and disable any ad blocker | body | current dictionary, the Allegro block page |
| `datadome_captcha` | DataDome CAPTCHA | title, body | current dictionary |
| `imperva_pardon_interruption` | Pardon Our Interruption | title, body | current dictionary |
| `amazon_type_characters` | Type the characters you see in this image | body | measured interstitial markers in the spec 7 Bruno rows v, w, x, y |
| `amazon_enter_characters` | Enter the characters you see below | body | same rows |
| `amazon_continue_shopping` | Click the button below to continue shopping | body | same rows, with the Polish and Swedish translations they carry |
| `akamai_access_denied` | Access Denied | title | wafw00f `kona.py`, and `ERROR_KEYWORDS` today |
| `perimeterx_automation_tools` | denied because we believe you are using automation tools | body | wafw00f `perimeterx.py` |
| `ddosguard_title` | DDoS-Guard | title | FlareSolverr `CHALLENGE_TITLES` |

Sixteen phrases. The current dictionary's eleven are all present, so nothing that matched yesterday stops matching.

The language set is thirty BCP 47 codes: the twenty-four official languages of the European Union less Irish and
Maltese, which are `bg`, `hr`, `cs`, `da`, `nl`, `en`, `et`, `fi`, `fr`, `de`, `el`, `hu`, `it`, `lv`, `lt`, `pl`,
`pt`, `ro`, `sk`, `sl`, `es`, `sv`, plus `uk`, `ru`, `tr`, `ja`, `ko`, `zh-Hans`, `zh-Hant` and `ar`.

Capture, not typing, is how a translation enters the file. For the Cloudflare phrases, task 5.2 opens a Cloudflare
challenge in a Playwright context with `locale` set to each code and records the rendered title and heading. For the
Amazon phrases, task 5.3 fetches each marketplace's captcha page and records its text, which extends the four locales
spec 7 already measured. For the generic and vendor phrases that exist today, the English is kept with provenance
`legacy-dictionary`, and a translation is added only when a wall carrying it is captured into the corpus. A language
with no captured translation for a phrase simply has no entry, and `scripts/generate_challenge_dictionary.py
--coverage` prints the phrase by language table so the gap is visible rather than guessed at.

Normalisation is applied at generation and at match time by the same function, so the generated file holds the
normalised forms and the matcher never has to agree with a second implementation.

Rejected: translating the phrases with a machine translation service and committing the output. It produces a
plausible sentence that is not the sentence the vendor renders, and a phrase that almost matches is a phrase that
never matches.

Rejected: matching on a per-language word for captcha alone. The word `captcha` is the same in most scripts and the
structure family already catches it in attribute values, where it is not translated.

### Decision 5: Every tier passes what it has, and the reader keeps its second look

Each call site is changed once:

- `curl_cffi_fetcher.py` passes `response.status_code`, `response.text`, `dict(response.headers)` and the names from
  every `set-cookie` header. Redirect hops keep their loop, and the assessment runs on the final response as today.
- `playwright_strategy.py` passes `initial_response.status`, `await initial_response.all_headers()` and the cookie
  names from `context.cookies()`, on the initial navigation. The two in-loop calls and the post-render call pass the
  rendered `page.content()` with the same headers, because a challenge that clears on its own changes the body and
  the cookies but not the headers of the response that started it. The `CHALLENGE_CLEAR_WAIT_SECONDS` loop keeps its
  shape and waits while `verdict.wall` is true.
- `flaresolverr_strategy.py` passes 200, the solution's `headers` map when present, and the names from
  `solution.cookies`.
- `crawlee_strategy.py` passes the status and headers of the final response through the result container it already
  fills.
- `novnc_strategy.py`'s `_poll_captcha` passes the rendered content and the cookie names from the storage state it
  already holds. `page_blocked` and `cleared` become two reads of one verdict.
- `web_reader.py` keeps its two calls with HTML only. `get_html` returns a string, and widening that contract to a
  response object touches six strategies and the Protocol for a second look that already fires on structure, shape
  and phrases without headers.

`ChallengeDetectedException` gains `verdict: ChallengeVerdict`, and its message names the vendor and the score. The
tiers that raise it stop deciding the intervention type themselves and take `verdict.intervention_type`, which is
what makes the password-input classifier reach the 428 without a second code path.

### Decision 6: The parser fails soft, the score does not

Family C uses `lxml.html.fromstring` on the prefix with the recovering parser lxml already ships. When it raises,
the family contributes nothing, a `parse_failed` pseudo-signal with weight 0 is recorded on the verdict so it is
counted, and the other four families still run. A page that defeats the parser is not thereby content: the word
floor, the headers, the status and the phrases still apply. This is stated as a requirement so that a future
"simplification" does not turn a parse error into an accept.

### Decision 7: The corpus is the contract, and a marker without a fixture is not admitted

`tests/fixtures/challenge_walls/` holds the pages and `manifest.json` describes them. The manifest entry for a
fixture carries `path`, `vendor`, `language`, `kind` (`wall` or `counterexample`), `status`, `headers` (an allowlist
of the names Decision 3 uses, values kept only for `server`, `cf-mitigated`, `x-amzn-waf-action`, `x-cdn` and
`x-iinfo`), `cookie_names`, `source_url`, `captured_on`, `captured_with` (`curl_cffi`, or `playwright` with the
locale), `synthetic`, `expected` (`wall`, `intervention_type`, `vendor`, `signals_must_fire`,
`signals_must_not_fire`) and `notes`.

Corpus rules, each enforced by a test:

- Every vendor in the catalogue has at least one `wall` fixture. Every `vendor_script`, `interstitial_structure` and
  `definitive_header` marker is fired by at least one fixture.
- Cloudflare and Amazon, the two vendors that localise their wall, have one fixture per captured language, and each
  phrase translation in the source file is fired by at least one of them.
- The counterexample set contains at least: a blog post with a reCAPTCHA comment form, a page hosting a Turnstile
  widget beside its own text, a vendor's own page that hosts its widget beside real content, a login page with a
  captcha (expected wall, type `login`), an article in each of `en`, `pl`, `de`, `ja` and `ar`, a 404 page, a 403
  with a large real body, and a script-only application shell (expected `has_content` false, `wall` false).
- No file exceeds 200 kilobytes. Inline script bodies are trimmed to their first 200 characters, attributes are
  never trimmed, because every marker in Decision 3 lives in an attribute, a header or a short text node.
- No cookie value, no `cf_clearance` or `datadome` token, no session content, no personal data. A test greps every
  fixture for the cookie names in the catalogue followed by `=` and a value.
- A fixture is `synthetic: true` only when no public page served that vendor's wall during capture, it is built from
  the cited markers alone, and it is listed in Open Question 4 with a task to replace it.

The corpus test runs every fixture through `assess` with its recorded status, headers and cookie names, asserts the
expected verdict, the expected type and the must and must-not signals, and prints a table of fixture, score, margin
to the threshold and fired signals. A fixture within twenty points of the threshold on either side is printed under a
heading of its own so a weight change that moves it is visible in the run output.

### Decision 8: One extraction per verdict, and the reader's own extraction is left alone

`has_real_content` already runs trafilatura on pages under `CHALLENGE_WALL_MAX_BYTES`, and `_execute_strategy` runs
`extract_text_with_fallback` again on accepted pages. The verdict runs trafilatura once, uses it for the word floor
and for family D, and the reader's extraction is untouched. Making the reader reuse the verdict's extraction would
save one call on accepted pages and would couple the detector's bare `trafilatura.extract` to the reader's
readability fallback, which are different functions with different outputs. Task 9.4 measures the added cost on the
largest fixture and on the largest real page in spec 7's matrix.

## Configuration

| Setting | Default | Derivation |
| :-- | :-- | :-- |
| `CHALLENGE_SCORE_THRESHOLD` | `100` | Above every non-definitive weight, so a wall needs two independent signals. Below the sum of any two strong ones, so a vendor script beside a captcha input is a wall on a thin page. |
| `CHALLENGE_RICH_CONTENT_WORDS` | `150` | Every wall in the catalogue explains itself in under 150 extracted words. Every article the service is asked to read is well over it. The guard sits between. |
| `CHALLENGE_FORM_DOMINANCE_RATIO` | `0.6` | A captcha page's visible text is its form and a footer. Three fifths inside the form separates that from a page with a search box and a newsletter form. |
| `CHALLENGE_MIN_WORDS_PER_KB` | `2.0` | A wall carries a few dozen words in five to two hundred kilobytes of script. An article carries several per kilobyte. |
| `CHALLENGE_THIN_LINK_COUNT` | `5` | A wall links to the vendor and a help page. A content page links to its site. |
| `CHALLENGE_RICH_LINK_COUNT` | `20` | Navigation plus in-article links on any content site. |
| `CHALLENGE_SHAPE_MAX_BYTES` | `500_000` | Bounds the extraction. A wall above this size is not a case worth paying for, and pages above it already pass the word floor automatically today at 50 000. |
| `CHALLENGE_DETECTION_MAX_BYTES` | `50_000` | Kept. The prefix the vendor, structure and phrase families read. |
| `CHALLENGE_WALL_MAX_BYTES` | `50_000` | Kept. The size under which a 403, 429 or 503 body is small, and under which the word floor is computed. |
| `VALIDATION_MIN_WORDS` | `10` | Kept. The word floor, unchanged. |

Two validators run at settings construction: the threshold must be positive, and `CHALLENGE_SHAPE_MAX_BYTES` must be
at least `CHALLENGE_WALL_MAX_BYTES`, so the word floor is never computed on a page the shape family refused.

## Observability

| Signal | Type | Labels | Meaning |
| :-- | :-- | :-- | :-- |
| `challenge_signals_fired_total` | Counter | `signal`, `vendor` | One increment per signal per verdict. `vendor` is a catalogue name, `none` for vendor-free signals. Cardinality is bounded by the catalogue. |
| `challenge_verdicts_total` | Counter | `verdict`, `tier` | `wall`, `content` or `no_content`, per tier name plus `novnc-monitor` and `reader`. |
| `challenge_score` | Histogram | none | Buckets `0, 20, 40, 60, 80, 100, 120, 160, 200, 300`, one at each weight sum that matters, so the near misses on both sides of 100 are visible. |
| `strategy_attempts_total` | Counter | `strategy`, `outcome`, `domain` | Kept. `challenge_detected` keeps its meaning. |

One log line per verdict at INFO when the score is at or above half the threshold or the verdict is a wall, at DEBUG
otherwise: `Challenge verdict: wall=%s score=%d threshold=%d vendor=%s type=%s signals=%s tier=%s url=%s`. The
`signals` field lists ids and weights, never evidence beyond the marker that matched. No page text, no cookie value
and no header value other than the four allowlisted in Decision 7 appears in any line.

`ChallengeDetectedException` carries the verdict, so the tier's existing "block detected" warning gains the vendor
and the score in the same line rather than a second line.

## Migration from the current dictionary

1. `challenge_dictionary.json` keeps its filename and its four top-level keys become sections of the generated file,
   with `login_title_patterns` copied verbatim. The four `waf_script_signatures` become `vendor_script` markers under
   their vendors. The eleven `waf_strict_phrases` become the phrase entries marked `legacy-dictionary` in Decision 4.
   The one `waf_structural_markers` entry becomes an Amazon `interstitial_structure` marker, beside the
   `/errors/validateCaptcha` form the sources name, until task 3.5 measures which is real and drops the other.
2. The three size-gated substrings, `cf-turnstile`, `cf_clearance` and `datadome`, become a `captcha_element`, a
   `vendor_presence` and a `vendor_presence` marker with no size gate. The `Ray ID:` regex becomes a Cloudflare
   `interstitial_structure` marker.
3. `is_blocked(status, html)` and `is_content_accepted(status, html)` keep working with two arguments throughout,
   so the eight call sites move in section 6 of `tasks.md` one at a time with the suite green between each.
4. Two behaviours change, both intended and both pinned by a counterexample: a wall from a vendor the dictionary did
   not know is a wall now, and a page with a real article beside a vendor script is content now. Every other page
   keeps its verdict, and the existing detector tests stay green except those that asserted a bare substring in a
   synthetic page of a few bytes, which are rewritten against the corpus with their new expectation named in the
   test.
5. `ERROR_KEYWORDS` in `ContentValidator` is untouched and its English-only defect is recorded in the register by
   task 10.4 as its own entry.
6. Rollback is `CHALLENGE_SCORE_THRESHOLD=1000`, which no sum of non-definitive weights reaches, leaving the two
   definitive headers, the empty-body status rule and the word floor. That is stricter than today, never looser.

## Open Questions

1. Whether 150 words is the right guard. The worked example of a short page hosting a Turnstile widget lands at 160
   and is a wall. The corpus margin table from task 9.1 is what either confirms the number or moves it, before the
   change is called done, and `nowsecure.nl` is captured as a fixture so the decision is made on the real page.
2. Which of `/errors/validateCaptcha` and `/errors_page/validateCaptcha` Amazon serves. The dictionary and one test
   say the second, spec 7 and every external source say the first. Task 3.5 measures it on five marketplaces.
3. Whether Cloudflare renders the challenge language client-side from `navigator.language`. If it does, the curl
   tier never sees a translated phrase and the phrase supplement is effectively a browser-tier signal for Cloudflare.
   Task 5.2 settles it by capturing the same challenge through curl and through a browser with a non-English locale.
4. Which vendors have no public wall to capture. Akamai, Imperva, Kasada, PerimeterX, DDoS-Guard and AWS WAF are
   expected to need a synthetic fixture on the first pass. Each synthetic fixture is listed in the manifest with
   `synthetic: true`, and task 8.6 records any real capture that a later spec 7 run produces so the synthetic one is
   replaced.
