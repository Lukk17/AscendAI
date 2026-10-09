## Context

Detection lives in `apps/ascend-web-hunter/src/reader/cloudflare/challenge_detector.py`. Its wall decision is
reached from nine `is_blocked` call sites: `crawlee_strategy.py` line 101, `curl_cffi_fetcher.py` line 123,
`flaresolverr_strategy.py` line 82, `novnc_strategy.py` lines 122 and 123 (`page_blocked` and `cleared`),
`playwright_strategy.py` lines 79 and 107 (two calls), and `web_reader.py` lines 407 and 468. The line numbers are from 2026-10-01 and are a starting point, not a contract. By file: `curl_cffi_fetcher.py` (tiers 1 and 2), `playwright_strategy.py` (tier 4, four calls, two of them inside a
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
lets the nine call sites keep compiling on day one while each is moved, one task at a time, to pass what it has.

A signal fires at most once per verdict, however many markers matched it. Two reCAPTCHA scripts on one page are one
`vendor_script`. Every fired signal is kept on the verdict so the log line, the metric and the test can name it.

Rejected: a boolean per new signal added beside the existing ones. Nine call sites already combine three booleans
with `and` and `not`, and each new signal would have to be threaded through all nine with a decision about how it
combines. A score is one number with one comparison, and the combination rule lives in one place.

Rejected: a machine-learned classifier. It would need the corpus this change builds before it could be trained, it
could not say which marker decided a page, and a vendor changing its markup would degrade it silently. The
catalogue plus a score can be read, tested and corrected by hand.

### Decision 2: Five signal families, with the language-independent ones first

The weights are settings, one per signal, named `CHALLENGE_WEIGHT_<SIGNAL ID IN UPPER CASE>` with the weight of the
tables below as the default (owner rule 98 of 2026-10-08). They are relative to each other and to the setting
`CHALLENGE_SCORE_THRESHOLD`, and changing one without re-running the corpus is guessing, so the documentation says so
and a validator refuses a set of weights that breaks the rules of this decision (configuration section). The seven
tuning values the families compare with (the threshold, `CHALLENGE_RICH_CONTENT_WORDS`,
`CHALLENGE_FORM_DOMINANCE_RATIO`, `CHALLENGE_MIN_WORDS_PER_KB`, `CHALLENGE_THIN_LINK_COUNT`,
`CHALLENGE_RICH_LINK_COUNT` and `CHALLENGE_SHAPE_MAX_BYTES`) are settings too, with the values of the configuration
table as defaults. `challenge_signals.py` reads all of them from the settings. The corpus test in task 9.1 is the
place a default weight changes.

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

Weights and tuning values as settings were rejected by owner answer 93 and are adopted by owner rule 98 of
2026-10-08: every value with a default is a setting, and an operator may need to move a weight or the threshold on a
host whose traffic the corpus does not cover. The defaults stay the values of the tables, and the validator of task
1.2 keeps the rules of this decision true for any values: no signal other than `definitive_header` and
`status_empty_body` reaches the threshold alone, the two guards never add to a score, and no other signal subtracts.

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
language follows the browser's `navigator.language`, read client-side, not the request's `Accept-Language`. The
reference says it in one sentence, quoted under Open Question 3 (owner decision 65.27 of 2026-10-04), and task 5.2
captures the translated phrases through a browser. If it
holds, the curl tier only ever sees the page's default text, and the browser tiers see it in the fingerprint's
locale, so the phrase supplement must be captured through a browser per language and the default text captured
through curl.

### Decision 4: Phrases live in one maintained file with their provenance, and none is typed from memory

`challenge_dictionary.json` is the one maintained file. It carries the provenance of every entry itself, and the
detector loads it directly through one loader in `challenge_signals.py`. There is no source file beside it, no
generator script and no generated copy (owner answer 93 of 2026-10-08, review item B8): one piece of knowledge has one
file. `tests/reader/cloudflare/test_challenge_dictionary.py` checks the rules a generator would have enforced: every
marker has a source and a date, every translation has a provenance, and every phrase id appears once.

The file has three sections. `vendors` holds the marker table from Decision 3, each marker with its `signal`,
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
with no captured translation for a phrase simply has no entry, and `test_challenge_dictionary.py` prints the phrase by
language table so the gap is visible rather than guessed at.

The file holds each phrase as it was captured. The loader normalises every phrase when it reads the file, with the same
function the matcher applies to the page, so the matcher never has to agree with a second implementation.

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
  phrase translation in the catalogue file is fired by at least one of them.
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

Every row is a setting (owner rule 98 of 2026-10-08). The first seven are new and replace the module constants of
owner answer 93 (review item C14), with the same values as defaults. The last three are the settings that exist
today, kept. The weight settings `CHALLENGE_WEIGHT_*` of Decision 2 are new settings too, one per signal of its
tables, with the weight printed there as the default. `config.py` carries each default, the `ascend-web-hunter`
service of both compose files passes each new setting and the two existing `CHALLENGE_*` byte limits as
`${VAR:-default}` with the same value, and the sync rule puts each new name into both `.env.example` files and the
bundle README (task 1.4). The rows of `docs/configuration.md` end with "Added by
`detect-challenge-walls-in-any-language`." (task 10.1).

| Name | Default | Derivation |
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

One validator runs at settings construction (task 1.2): `CHALLENGE_WALL_MAX_BYTES` must not exceed
`CHALLENGE_SHAPE_MAX_BYTES`, so the word floor is never computed on a page the shape family refused, every weight
other than those of `definitive_header` and `status_empty_body` must stay below `CHALLENGE_SCORE_THRESHOLD`, the
weights of `rich_content` and `many_links` must not be positive and every other weight must not be negative, and
`CHALLENGE_THIN_LINK_COUNT` must not exceed `CHALLENGE_RICH_LINK_COUNT`.

## Observability

| Signal | Type | Labels | Meaning |
| :-- | :-- | :-- | :-- |
| `challenge_signals_fired_total` | Counter | `signal`, `vendor` | One increment per signal per verdict. `vendor` is a catalogue name, `none` for vendor-free signals. Cardinality is bounded by the catalogue. |
| `challenge_verdicts_total` | Counter | `verdict`, `tier` | `wall`, `content` or `no_content`, per tier name plus `novnc-monitor` and `reader`. |
| `challenge_score` | Histogram | none | Buckets `0, 20, 40, 60, 80, 100, 120, 160, 200, 300`, one at each weight sum that matters at the default weights, plus `CHALLENGE_SCORE_THRESHOLD` when an override moves it off the list, so the near misses on both sides of the threshold are visible. The bucket list is part of the metric's definition and stays a constant. |
| `strategy_attempts_total` | Counter | `strategy`, `outcome`, `domain` | Kept. `challenge_detected` keeps its meaning. |

One log line per verdict at INFO when the score is at or above half the threshold or the verdict is a wall, at DEBUG
otherwise: `Challenge verdict: wall=%s score=%d threshold=%d vendor=%s type=%s signals=%s tier=%s url=%s`. The
`signals` field lists ids and weights, never evidence beyond the marker that matched. No page text, no cookie value
and no header value other than the four allowlisted in Decision 7 appears in any line.

`ChallengeDetectedException` carries the verdict, so the tier's existing "block detected" warning gains the vendor
and the score in the same line rather than a second line.

## Migration from the current dictionary

1. `challenge_dictionary.json` keeps its filename and its four top-level keys become sections of the rewritten
   file, with `login_title_patterns` copied verbatim. The four `waf_script_signatures` become `vendor_script` markers under
   their vendors. The eleven `waf_strict_phrases` become the phrase entries marked `legacy-dictionary` in Decision 4.
   The one `waf_structural_markers` entry becomes an Amazon `interstitial_structure` marker, beside the
   `/errors/validateCaptcha` form the sources name. The marker matches both paths and neither is dropped (owner
   decision 65.27 of 2026-10-04).
2. The three size-gated substrings, `cf-turnstile`, `cf_clearance` and `datadome`, become a `captcha_element`, a
   `vendor_presence` and a `vendor_presence` marker with no size gate. The `Ray ID:` regex becomes a Cloudflare
   `interstitial_structure` marker.
3. `is_blocked(status, html)` and `is_content_accepted(status, html)` keep working with two arguments throughout,
   so the nine call sites move in section 6 of `tasks.md` one at a time with the suite green between each.
4. Two behaviours change, both intended and both pinned by a counterexample: a wall from a vendor the dictionary did
   not know is a wall now, and a page with a real article beside a vendor script is content now. Every other page
   keeps its verdict, and the existing detector tests stay green except those that asserted a bare substring in a
   synthetic page of a few bytes, which are rewritten against the corpus with their new expectation named in the
   test.
5. `ERROR_KEYWORDS` in `ContentValidator` is untouched and its English-only defect is recorded in the register by
   task 10.4 as its own entry.
6. Rollback is the image of the change before this one, ascend-web-hunter 0.0.9. The threshold and the weights are
   settings (owner rule 98 of 2026-10-08), but no value of them restores the phrase-first behaviour, because a
   definitive signal still forces a wall, so they tune the score and are not a rollback.

## Open Questions

All four were closed by owner decision 65.27 of 2026-10-04. They are kept with their answers so the numbers other
text cites stay valid.

1. Closed: the 150-word guard stays as a measured task. Task 9.1's corpus margin table, with `nowsecure.nl` captured
   as a fixture, confirms the number or moves it before the change is called done.
2. Closed: the Amazon marker matches both `/errors/validateCaptcha` and `/errors_page/validateCaptcha`, so neither
   path is dropped. Task 3.5 still records which path each marketplace serves, as evidence for the fixtures.
3. Closed: Cloudflare's challenge language follows the browser's `navigator.language`. Source, quoted on
   2026-10-04: "Cloudflare Challenges can detect multiple languages and display the localized challenge experience,
   which is determined by `navigator.language` value."
   (https://developers.cloudflare.com/cloudflare-challenges/reference/supported-languages/). The curl tier therefore
   sees only the page's default text, and the translated phrases are a browser-tier signal. Task 5.2 captures them
   through a browser per language.
4. Closed: the synthetic fixtures for Akamai, Imperva, Kasada, PerimeterX, DDoS-Guard and AWS WAF stay, listed with
   `synthetic: true`, and task 8.6 replaces each one with a real capture when a spec 7 run records one.

## Owner decisions of 2026-10-08

The owner approved on 2026-10-08 the fixes of the review of the group 1 and group 2 changes of 2026-10-07.

- Item 6: the fake site pages of the verdict spec of task 11.8 are named by path, and task 11.12 adds the missing ones
  (`/wall-vendor-thin`, `/wall-oversized`), rebuilds `/wall-ko` so it scores above the 428 threshold, rebuilds
  `/captcha-wall` into a blog post with a catalogued widget, and moves every page into one file each under
  `apps/ascend-web-hunter/e2e/fake-site/pages/`, which a unit test judges with `assess`. The pages are not corpus
  fixtures and the corpus rules of Decision 7 do not apply to them. The same unit test keeps `/turnstile-wall` of
  `open-several-novnc-windows-at-once` a wall.
- Item 8: task 8.4 no longer names a spec 7 Part 3, which does not exist. The hCaptcha demo form of spec 11 is the
  fixture that pins the human spec's contract.
- Item 19: task 9.3 runs mypy over `src scripts tests`, the same gate as `add-ascend-python-common` D14.
  (Changed by answer 93 below: with the generator gone there is no `scripts` folder, so task 9.3 runs mypy over
  `src tests`.)
- Item 20: spec 7 carries one cap rule. Task 11.5 replaces the "at least 4" line of
  `open-several-novnc-windows-at-once` task 11.1 in place with "at least 5".
- Owner decision of 2026-10-08, "one named version per change, in build order": this change ships as
  ascend-web-hunter 0.0.10 with its own CHANGELOG entry, one patch step after 0.0.9 of
  `open-several-novnc-windows-at-once` (build group 2, position 3). It no longer adds its lines to that change's entry
  (task 10.5).

Answer 87: confirmed, nothing to change. The verdict holds no state between requests. The catalogue is a file of the
image, the same in every ascend-web-hunter container, loaded once per process, and the metrics are per container like
every other metric of the service. No lock, cache, counter or queue of this change needs to be shared between
containers, so several containers run it safely as it is.

Answer 93: review item C14 is applied. The seven tuning values (`CHALLENGE_SCORE_THRESHOLD`,
`CHALLENGE_RICH_CONTENT_WORDS`, `CHALLENGE_FORM_DOMINANCE_RATIO`, `CHALLENGE_MIN_WORDS_PER_KB`,
`CHALLENGE_THIN_LINK_COUNT`, `CHALLENGE_RICH_LINK_COUNT` and `CHALLENGE_SHAPE_MAX_BYTES`) are module constants in
`challenge_signals.py` beside the weights, not settings (configuration table, tasks 1.1, 1.2 and 10.1). The rollback by
setting the threshold to 1000 goes with them, and a rollback is the image of the change before this one. (Changed by
answer 98 below: the seven tuning values and the weights are settings again, with the same values as defaults. The
rollback stays the image.) Review item
B8 is applied: `challenge_dictionary.json` is the one maintained file with its provenance, loaded directly and
normalised at load time, with no source file, no generator script and no generated copy (Decision 4, tasks 2.1 to 2.4,
5.1, 5.5 and 10.2, task 2.2 removed). The phrase by language table that the generator's coverage mode printed is
printed by the catalogue test instead, so the gap stays visible. Without a `scripts` folder, task 9.3 runs mypy over
`src tests`.

Answer 92: not applied, because each would cut what the owner asked for. Review item C15 (keep one live Amazon locale
in spec 7 instead of five) is skipped: the five rows are live checks against real sites, which answer 91.3 keeps, and
they are the only proof that the wall is caught in those languages on the real pages. Review item B15 (drop the
thirty-language phrase capture) is skipped by the owner's own list of things not to apply.

Answer 91.3: no spec of this change is dropped. The verdict spec of task 11.8 is the one deterministic spec of this
capability, and it proves what the unit test of task 11.12 cannot: that each real tier hands the status, the headers
and the cookie names of a real response to the verdict, and that a wall reaches the 428 through the stack. The spec 7
rows read real sites and stay.

Answer 85.1: no task of this change exports a key or a secret in a shell.

Answer 98: every value of this change that has a default is a setting (owner rule 98 of 2026-10-08), which also
decides the tuning constants of answer 93 (CANON 31.13): an operator may need to move the threshold, a weight or a
limit on traffic the corpus does not cover, without a new image. Settings, each read by `config.py` with its default,
passed by both compose files as `${VAR:-default}` with the same value, put into both `.env.example` files and the
bundle README by the sync rule (task 1.4) and listed in `docs/configuration.md` with "Added by
`detect-challenge-walls-in-any-language`." (task 10.1): `CHALLENGE_SCORE_THRESHOLD` 100, `CHALLENGE_RICH_CONTENT_WORDS`
150, `CHALLENGE_FORM_DOMINANCE_RATIO` 0.6, `CHALLENGE_MIN_WORDS_PER_KB` 2.0, `CHALLENGE_THIN_LINK_COUNT` 5,
`CHALLENGE_RICH_LINK_COUNT` 20, `CHALLENGE_SHAPE_MAX_BYTES` 500000, and the eighteen weights
`CHALLENGE_WEIGHT_DEFINITIVE_HEADER` 200, `CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE` 80,
`CHALLENGE_WEIGHT_VENDOR_SCRIPT` 60, `CHALLENGE_WEIGHT_VENDOR_PRESENCE` 30, `CHALLENGE_WEIGHT_STATUS_EMPTY_BODY` 200,
`CHALLENGE_WEIGHT_STATUS_SMALL_BODY` 50, `CHALLENGE_WEIGHT_STATUS_LARGE_BODY` 20, `CHALLENGE_WEIGHT_CAPTCHA_INPUT` 50,
`CHALLENGE_WEIGHT_CAPTCHA_ELEMENT` 40, `CHALLENGE_WEIGHT_FORM_DOMINANCE` 40, `CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY` 40,
`CHALLENGE_WEIGHT_THIN_TEXT` 20, `CHALLENGE_WEIGHT_FEW_LINKS` 20, `CHALLENGE_WEIGHT_NO_ARTICLE` 20,
`CHALLENGE_WEIGHT_RICH_CONTENT` -60, `CHALLENGE_WEIGHT_MANY_LINKS` -20, `CHALLENGE_WEIGHT_PHRASE_TITLE` 60 and
`CHALLENGE_WEIGHT_PHRASE_BODY` 30. The existing `CHALLENGE_DETECTION_MAX_BYTES` (50000) and `CHALLENGE_WALL_MAX_BYTES`
(50000) keep their defaults and gain their compose lines in the same task. A validator keeps the rules of Decision 2
true for any values (task 1.2), and the score histogram always has a boundary at the configured threshold (task 7.1,
the observability requirement). Kept as constants, because they are not operational: the zero weight of the
`parse_failed` pseudo-signal (it records a fact and never scores), the signal ids, family names and vendor names, the
histogram bucket list (part of the metric's definition), the metric names and labels, and the test-only values of the
corpus (the twenty point near-threshold band of task 9.1, the 200 kilobyte fixture bound of task 8.8 and the 50
millisecond measurement bound of task 9.4). The spec texts that said "fixed" for the threshold, the word count, the
link count and the form share now say "configured". Tasks changed: 1.1, 1.2, 4.7, 7.1, 9.4 and 10.1, new task 1.4. No
task of this change is ticked, so nothing is marked for rework. The proposal sentences that still called the tuning values constants
(What Changes, Impact, Risks and the operational note) now name them settings. No test or measurement of this change
uses LM Studio, and no text of this change names the old `e2e` profile or plans several copies elsewhere.
