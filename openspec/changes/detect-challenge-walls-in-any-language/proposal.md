## Why

The service decides whether a page is a challenge wall by looking for things it already knows, and a wall it does
not know is handed back to the caller as a successful read.

`ChallengeDetector.is_blocked` in
[challenge_detector.py](../../../apps/ascend-web-hunter/src/reader/cloudflare/challenge_detector.py) fires on
exactly four kinds of evidence. A vendor script signature from
[challenge_dictionary.json](../../../apps/ascend-web-hunter/src/reader/cloudflare/challenge_dictionary.json), of
which there are four: `arkoselabs.com`, `recaptcha/api.js`, `hcaptcha.com/1/api.js` and `perimeterx.net`. A fixed
phrase from the same file, of which there are ten in English and one in Polish. One structural marker,
`/errors_page/validateCaptcha`. And, only when the page is under `CHALLENGE_WALL_MAX_BYTES`, the substrings
`cf-turnstile`, `cf_clearance` and `datadome`, plus a `Ray ID:` regex at any size. Everything else in the decision is
`has_real_content`, which accepts a page as content the moment trafilatura extracts `VALIDATION_MIN_WORDS` words
from it, and that threshold is ten.

Measured on 2026-09-10 against that code, the consequence is this. A wall from GeeTest, Akamai Bot Manager, Imperva
Incapsula, Kasada, MTCaptcha or Friendly Captcha, or a site's own image or text captcha, carries none of the four
script signatures and none of the eleven phrases. If its page explains itself in more than ten words, in any
language, `is_blocked` returns false, `has_real_content` returns true, and `_execute_strategy` in
[web_reader.py](../../../apps/ascend-web-hunter/src/reader/web_reader.py) accepts the wall as the page. The caller
receives HTTP 200, `status: success`, and the wall's own text as `content`. That result is then cached for
`READ_CACHE_TTL_SECONDS` and, through the MCP surface, fed to the agent as if it were the article.

The repository already records one instance of this shape. Spec 7's "Dependency on the pending anti-bot fix"
paragraph in
[7-authenticated-realworld-scraping-test.md](../../../apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md)
states that a live probe of each Amazon locale's `/errors/validateCaptcha` through `POST /api/v2/web/read` returned
HTTP 200 with `status: success` and the interstitial as content, and rows v, w, x and y exist to fail on exactly
that. The one structural marker in the dictionary is `/errors_page/validateCaptcha`, and the spec, the Bruno rows and
one existing test all name the path as `/errors/validateCaptcha`. Whether those are two real paths or one real path
and one typo is measured in this change rather than assumed, because a marker that never matches is the same as no
marker.

The phrase list is the wrong primary mechanism and it cannot be made the right one by making it longer. Cloudflare,
DataDome, Amazon and every site-specific wall render their explanation in the visitor's language. A phrase list
covering English and Polish recognises a wall served to a Polish or English browser and nothing else, and the
service's browser fingerprint sets the locale, so the language a wall arrives in is a property of configuration,
not of the site. The owner's requirement is that the scraper recognises a wall in any language. That rules out
words as the first line of evidence and puts it on the things a wall cannot translate: the vendor's script, cookie
and header signatures, the HTTP status the wall is served with, the shape of the page (a form with a captcha input,
an image or canvas named captcha, a page whose visible text is one form, a meta refresh or a script-only body), and
the ratio of extracted words to bytes, links and article structure that separates a wall from an article. Phrases
stay, as a supplement generated from a maintained source file for a broad set of languages, and never as the thing
the verdict depends on.

The other side of the same coin is a false positive that already exists today. `recaptcha/api.js` fires `is_blocked`
regardless of page size, so a blog post with a reCAPTCHA under its comment form is escalated tier by tier to a 428 and
a human. The threshold and the weights below are chosen so that a vendor script alone never crosses the line, and
so that a page carrying a real article never does either.

## What Changes

One verdict, with a score, instead of four booleans:

- `ChallengeDetector.assess(status_code, headers, html)` returns a `ChallengeVerdict` carrying the score, every
  signal that fired with its weight, the vendor the signals point at when they point at one, and the intervention
  type. `is_blocked`, `has_real_content` and `is_content_accepted` keep their names and become thin readers of
  that verdict, so the eight call sites that use them today keep working while each is moved to pass the response
  headers it already has.
- A page is a wall when its score reaches `CHALLENGE_SCORE_THRESHOLD`, or when a definitive signal fires. A
  definitive signal is one the vendor only ever emits while serving a challenge, such as Cloudflare's
  `cf-mitigated: challenge` response header, and it carries a weight of twice the threshold so no guard can cancel
  it.
- A page with fewer than `VALIDATION_MIN_WORDS` of extracted text is still not content, exactly as today. That
  floor is kept as a separate positive requirement, not folded into the score.

Signals in four families, the language-independent three first:

- Vendor signatures: script hosts and paths, cookie names, response headers and DOM markers for Cloudflare
  (managed challenge, JS challenge and the explicit Turnstile script), DataDome, GeeTest, Akamai Bot Manager,
  Imperva Incapsula, Kasada, MTCaptcha, Friendly Captcha, Arkose Labs, hCaptcha, Google reCAPTCHA, PerimeterX and
  HUMAN, DDoS-Guard, Amazon's own captcha page and AWS WAF. Every marker in the catalogue carries the source it was
  taken from, listed in [design.md](design.md).
- HTTP evidence: a 403, 429 or 503 with a small body, a WAF response header, a vendor server string.
- Page structure: a form whose input name, id or autocomplete contains `captcha`, an image, canvas or iframe whose
  src or id contains `captcha`, a page whose visible text is dominated by one form, a meta refresh, a body that is
  script and nothing else.
- Content shape: extracted words per kilobyte of HTML, link count, and whether an article or main element with real
  text exists. This family is also where the negative weights live. A page carrying `CHALLENGE_RICH_CONTENT_WORDS`
  of extracted article text is pulled back below the threshold unless a definitive signal says otherwise. That is
  the guard that keeps a blog post with a captcha under its comment form from becoming a human escalation.

Phrases as a generated supplement:

- `challenge_dictionary.json` stops being hand-edited. It becomes the generated output of
  `scripts/generate_challenge_dictionary.py` from `challenge_dictionary.source.json`, which holds the vendor
  catalogue with a source per marker and a phrase table with a provenance per translation. A test asserts the
  committed output is byte-identical to what the generator produces, so a hand edit fails the suite.
- The phrase set is sixteen canonical phrases, listed in [design.md](design.md), and the language set is thirty
  BCP 47 codes, also listed there. A translation enters the source file only when captured from the vendor's own
  localised page or from a measured interstitial, with the capture recorded beside it. No translation is typed from
  memory, including by the author of this change.
- Phrases are normalised before matching, so `Just a moment...` and `Just a moment…` are one phrase, and a phrase
  match in the title weighs more than the same phrase in the body.

A corpus that pins the behaviour:

- `tests/fixtures/challenge_walls/` holds one saved wall page per vendor, one per captured language for the two
  vendors that localise their wall, and a counterexample set: a blog post with a reCAPTCHA comment form, a page
  that hosts a Turnstile widget beside full content, a vendor's own marketing page that hosts its own widget, a
  login page with a captcha, articles in several languages, a 404 page, and a 403 with a large real body. A
  manifest records the expected verdict, the expected signals, the source URL, the capture date, the status and
  the headers of each. A fixture that could not be captured from a public page is built from the cited markers
  alone and marked synthetic, and a task exists to replace it with a capture.

Observability that names the signal:

- A counter per signal that fired, labelled by signal and vendor, a counter per verdict labelled by verdict and
  tier, and a histogram of scores with buckets at the weights, so an operator can see the near misses that sit just
  under the threshold and the walls that sit just over it.
- One log line per verdict at or above half the threshold, carrying the score, the signals, the vendor, the tier and
  the URL. `ChallengeDetectedException` carries the verdict, so the line the tier writes when it escalates says why.

The e2e suite gains rows that cannot pass by luck:

- Spec 7's matrix gains a "Challenge walls in other vendors and languages" group: Amazon's own captcha page in five
  more locales, gated to `intervention`, and the "pending anti-bot fix" paragraph is closed by this change. It also
  gains a "Widgets that are not walls" group: three vendor demo pages that host their own widget beside real
  content, gated to `success`, which is the false-positive guard exercised live.

## Scope

- `apps/ascend-web-hunter/src/reader/cloudflare/challenge_detector.py`: rewritten around `assess` and the verdict,
  with the three existing readers kept as wrappers.
- `apps/ascend-web-hunter/src/reader/cloudflare/challenge_signals.py`: new, the signal families, their weights and
  the pure functions that compute each one from a status, a header map, a prefix and an extraction.
- `apps/ascend-web-hunter/src/reader/cloudflare/challenge_dictionary.source.json`: new, the maintained source.
- `apps/ascend-web-hunter/src/reader/cloudflare/challenge_dictionary.json`: becomes generated output.
- `apps/ascend-web-hunter/scripts/generate_challenge_dictionary.py`: new, the generator, with a `--check` mode the
  test suite runs.
- `apps/ascend-web-hunter/src/api/exceptions.py`: `ChallengeDetectedException` gains the verdict.
- `apps/ascend-web-hunter/src/reader/strategies/curl_cffi_fetcher.py`, `playwright_strategy.py`,
  `flaresolverr_strategy.py`, `crawlee_strategy.py`, `novnc_strategy.py` and `src/reader/web_reader.py`: the eight
  call sites, each passing the headers it has.
- `apps/ascend-web-hunter/src/config/config.py`: seven settings, listed with derivations in [design.md](design.md).
- `apps/ascend-web-hunter/src/observability/metrics.py`: two counters and one histogram.
- `apps/ascend-web-hunter/tests/`: the fixture corpus, its manifest, the signal tests, the corpus test, the generator
  test, and the migration test, to the module's `--cov-fail-under=100` with `--cov-branch`.
- `apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md`, its sidecar template, the
  Bruno rows under `docs/api/request/AscendAI/web-hunter/testing/realworld/`, and `e2e/README.md`.
- Docs: `AGENTS.md`, `README.md`, `docs/configuration.md`, a new ADR-010, an amendment to ADR-001, and a new row in
  `docs/DEFECT_REGISTER.md`.

## Out of Scope

- Solving any challenge. This change decides that a page is a wall. What happens next is the existing escalation
  and, at the end of it, the existing 428.
- Language-independent login-wall detection beyond one classifier. `is_login_required` and its English title
  patterns are untouched. The only addition is that a wall verdict whose dominant form carries a password input is
  classified as `login` rather than `captcha`, because that is the language-independent signal the intervention
  type already needs.
- Changing the 428 body. The sibling change `open-several-novnc-windows-at-once` adds fields to it this week, and two
  changes editing one response shape at once is a merge hazard for no benefit. The vendor and the signals reach the
  operator through the log line and the metrics.
- `ERROR_KEYWORDS` in `ContentValidator`. Those seven English strings fail validation on extracted text, which sends
  an article about captchas to the next tier today. That is a separate defect with its own fix, recorded in the
  register by this change and not closed by it.
- A refresh endpoint or a runtime reload for the catalogue. The catalogue ships in the image like the blocklist
  does under ADR-008, and a new vendor is a commit.
- Any per-domain tuning of weights or thresholds. One score, one threshold, one catalogue.
- The tier ladder itself, which the unarchived `web-search-tier-ladder` delta reshapes. This change is written
  against the six tiers that exist and touches the detector every tier calls, not the order they are called in.

## Risks

- Weight tuning is a judgement until the corpus exists. The weights in [design.md](design.md) are derived from
  worked examples of a wall and a non-wall, not from a measured distribution. The corpus is what turns them into a
  measurement, and section 9 of [tasks.md](tasks.md) exists to run every fixture through the verdict and report the
  score margin of each, so that a fixture within twenty points of the threshold is visible before the change is
  called done.
- Latency. Structure and content-shape signals parse the page, and trafilatura already runs once in
  `has_real_content` for pages under `CHALLENGE_WALL_MAX_BYTES`. The verdict runs one parse and one extraction per
  page, bounded by `CHALLENGE_SHAPE_MAX_BYTES`, and task 9.4 measures the cost on the largest fixture rather than
  asserting it is small.
- A vendor changes its markers. Every marker carries its source and its capture date, the corpus pins the page it
  was seen on, and a marker with no fixture is not allowed into the catalogue. When a vendor moves, the fixture goes
  stale and the corpus test says which one.
- Behaviour change on pages that were escalated by a script signature alone. A page that carries `recaptcha/api.js`
  beside a real article was a 428 yesterday and is a 200 today. That is the intended fix of a false positive, it is
  stated in the migration section, and the counterexample corpus asserts it.
- The Amazon marker discrepancy. If `/errors_page/validateCaptcha` never matched, rows v, w, x and y have been
  passing on product pages and failing on interstitials since they were written, which is what the spec's own
  paragraph says. Task 3.5 measures the live form action before the catalogue commits to either path.
- Rollback. `CHALLENGE_SCORE_THRESHOLD` raised well above the sum of the non-definitive weights disables the score
  and leaves only the definitive signals and the word floor, which is a stricter version of today's behaviour. There
  is no setting that restores the phrase-first behaviour, and none is wanted.

## Capabilities

### New Capabilities

- `web-search-challenge-wall-detection`: what evidence the service weighs when deciding a page is a challenge wall,
  how it is scored, where the threshold sits, which signals are definitive, how a page with a real article is kept
  from being a wall, and what each tier does with the verdict.
- `web-search-challenge-signature-catalogue`: what the catalogue of vendor markers and phrases contains, where each
  entry's provenance lives, how the runtime file is generated from the source, which languages the phrase supplement
  covers, and what the fixture corpus must hold for a marker to be admitted.
- `web-search-challenge-detection-observability`: what the service reports about each verdict, over the metrics
  surface and the logs, so an operator can tell a wall the detector caught from one it nearly missed.

### Modified Capabilities

None. No capability under `openspec/specs/` covers ascend-web-hunter today. The unarchived
`web-search-fetch-correctness` delta requires that detection is not skipped by page size, and this change keeps that
requirement true and does not restate it. The unarchived `web-search-tier-ladder` delta requires a local CAPTCHA
solver before human escalation, which sits after the verdict this change produces and is untouched by it.

## Impact

API: none on the wire. Both surfaces return the same shapes with the same fields. What changes is which pages get
which shape: a wall from a vendor the dictionary did not know returns 428 where it returned 200, and a real page
that hosts a captcha widget returns 200 where it returned 428.

Operational: one parse and one extraction per page per tier, bounded by two byte limits. Three new metric series,
one of them a histogram. Seven settings with defaults that need no operator action.

Tests: `apps/ascend-web-hunter` runs `--cov=src --cov-branch --cov-fail-under=100`, so every signal and every branch
in the verdict needs a test before the suite goes green. The fixture corpus adds roughly forty HTML files under
`tests/fixtures/`, each bounded to 200 kilobytes, with no cookie values and no session content in any of them.

Docs: the environment variable tables in `apps/ascend-web-hunter/AGENTS.md`, `README.md` and
`docs/configuration.md`, which also gain the two existing `CHALLENGE_*` settings that `docs/configuration.md` does
not list today, a new ADR-010 for the scoring model and the catalogue, an amendment to ADR-001 whose Related section
names the booleans this change replaces, and one new row in `docs/DEFECT_REGISTER.md` for the false negative spec 7
already describes. ADR-009 is reserved by the sibling change `open-several-novnc-windows-at-once`.

## Relevant Skills

Load before implementing:

- `/python-patterns`, `/python-testing`, `/tdd-workflow`
- `/security-review` for the parser on untrusted HTML, the header map, the fixture corpus and what it must not
  contain
- `/api-design` for the verdict carried on the exception and the metric label sets
- `/e2e-runbooks` for the spec 7 rows, the Bruno requests and the sidecar template
- `/coding-standards`, `/code-reviewer`
- `/architecture-decision-records` for ADR-010 and the ADR-001 amendment
