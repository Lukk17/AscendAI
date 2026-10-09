Every command runs from `apps/ascend-web-hunter/` through that module's own virtual environment
(`.venv/Scripts/python.exe` on Windows, `.venv/bin/python` on Linux and macOS), never the system Python. The gate is
`--cov=src --cov-branch --cov-fail-under=100`, so every signal and every branch added below needs a test before the
suite goes green.

Sections 1 to 8 are the implementation and can be done in order, with one exception: section 8, the corpus, is
captured early because sections 3, 4 and 5 assert against it. Section 9 is the verification gate. Sections 10 and 11
are documentation and the e2e suite, both of which need the implementation first. Section 12 is live verification
and it gates calling the change done.

## 1. Configuration

- [ ] 1.1 Add to `src/config/config.py`, each with a `Field` carrying its default, its constraint and a description, the
      seven tuning settings `CHALLENGE_SCORE_THRESHOLD` (100), `CHALLENGE_RICH_CONTENT_WORDS` (150),
      `CHALLENGE_FORM_DOMINANCE_RATIO` (0.6, above 0 and at most 1), `CHALLENGE_MIN_WORDS_PER_KB` (2.0),
      `CHALLENGE_THIN_LINK_COUNT` (5), `CHALLENGE_RICH_LINK_COUNT` (20) and `CHALLENGE_SHAPE_MAX_BYTES` (500000), and
      one weight setting per signal of `design.md` Decision 2, named `CHALLENGE_WEIGHT_<SIGNAL ID IN UPPER CASE>` with
      the weight of that table as its default: `CHALLENGE_WEIGHT_DEFINITIVE_HEADER` (200),
      `CHALLENGE_WEIGHT_INTERSTITIAL_STRUCTURE` (80), `CHALLENGE_WEIGHT_VENDOR_SCRIPT` (60),
      `CHALLENGE_WEIGHT_VENDOR_PRESENCE` (30), `CHALLENGE_WEIGHT_STATUS_EMPTY_BODY` (200),
      `CHALLENGE_WEIGHT_STATUS_SMALL_BODY` (50), `CHALLENGE_WEIGHT_STATUS_LARGE_BODY` (20),
      `CHALLENGE_WEIGHT_CAPTCHA_INPUT` (50), `CHALLENGE_WEIGHT_CAPTCHA_ELEMENT` (40),
      `CHALLENGE_WEIGHT_FORM_DOMINANCE` (40), `CHALLENGE_WEIGHT_SCRIPT_ONLY_BODY` (40), `CHALLENGE_WEIGHT_THIN_TEXT`
      (20), `CHALLENGE_WEIGHT_FEW_LINKS` (20), `CHALLENGE_WEIGHT_NO_ARTICLE` (20), `CHALLENGE_WEIGHT_RICH_CONTENT`
      (-60), `CHALLENGE_WEIGHT_MANY_LINKS` (-20), `CHALLENGE_WEIGHT_PHRASE_TITLE` (60) and
      `CHALLENGE_WEIGHT_PHRASE_BODY` (30). `challenge_signals.py` reads them from the settings and holds no weight or
      tuning value of its own. The zero weight of the `parse_failed` pseudo-signal stays a constant, because it only
      records a fact (owner rule 98 of 2026-10-08, which replaces the module constants of owner answer 93 for these
      values). Verify with cases in `tests/config/test_config.py` for each default, a valid override and a rejected
      value outside its constraint, and by the tests of sections 4 and 9 asserting the boundaries at the defaults and
      one boundary moved by an override.
- [ ] 1.2 Add a model validator rejecting a `CHALLENGE_WALL_MAX_BYTES` above `CHALLENGE_SHAPE_MAX_BYTES`, a weight of
      a signal other than `definitive_header` and `status_empty_body` at or above `CHALLENGE_SCORE_THRESHOLD` (no
      single such signal may decide a wall, `design.md` Decision 2), a positive weight for `rich_content` or
      `many_links`, a negative weight for any other signal, and a `CHALLENGE_THIN_LINK_COUNT` above
      `CHALLENGE_RICH_LINK_COUNT`. Verify with one test per rule asserting construction fails and that the message
      names the settings involved.
- [ ] 1.3 Reword the descriptions of `CHALLENGE_DETECTION_MAX_BYTES` and `CHALLENGE_WALL_MAX_BYTES` to the meanings
      in `design.md`'s configuration table, without changing their defaults. Verify by asserting both defaults are
      unchanged in `tests/config/test_config.py`.
- [ ] 1.4 Pass every setting of task 1.1 and the two existing settings of task 1.3 through the `ascend-web-hunter`
      service of `compose.ascend-web-hunter.yaml` and of `deploy-standalone/compose.yaml` as
      `- <NAME>=${<NAME>:-<default>}` with the default of the settings, for example
      `- CHALLENGE_SCORE_THRESHOLD=${CHALLENGE_SCORE_THRESHOLD:-100}` and
      `- CHALLENGE_WEIGHT_RICH_CONTENT=${CHALLENGE_WEIGHT_RICH_CONTENT:--60}` (owner rule 98 of 2026-10-08). Under the
      sync rule, in the same commit as task 1.1, add each new setting as a commented line with its default and a
      one-line comment, in the form of `# RATE_LIMIT_DEFAULT=1200/minute`, to the root `.env.example` and
      `deploy-standalone/.env.example`, and a row (Required `No`, the default named) to the configuration table of
      `deploy-standalone/README.md`. Verify with `docker compose config` (read only) from the repository root and in
      `deploy-standalone/` showing each variable with its default on the service (the negative weights included), the
      same command with `CHALLENGE_SCORE_THRESHOLD=120` set in the shell of that one command showing the override, and
      a search of both `.env.example` files and the bundle README finding each new name once.

## 2. The catalogue file

- [ ] 2.1 Rewrite `src/reader/cloudflare/challenge_dictionary.json` into the one maintained catalogue file with the
      three sections from `design.md` Decision 4: `vendors` holding the marker table from Decision 3 with `signal`,
      `source` and `verified_on` per marker, `phrases` holding the sixteen ids with their canonical English and a
      `provenance` per translation, and `login_title_patterns` copied verbatim from the current dictionary. No source
      file, generator or generated copy is added (owner answer 93 of 2026-10-08, review item B8). Verify with
      `tests/reader/cloudflare/test_challenge_dictionary.py`, which loads the file, asserts every marker has a
      non-empty `source` URL and a `verified_on` date, asserts every translation has a `provenance`, and asserts every
      phrase id in Decision 4's table is present exactly once.
- [ ] 2.3 Carry every string the old dictionary held into the rewritten file under its new section. Verify with a test
      that lists the old dictionary's strings and finds each one in the loaded catalogue.
- [ ] 2.4 Make the detector load the catalogue file directly through one loader in `challenge_signals.py`, which
      normalises every phrase at load time and fails loudly on a missing or malformed file instead of the current
      silent fallback to empty lists. Verify with a test that a missing file raises at import with a message naming
      the path, matching the packaging-defect rule ADR-008 applies to the blocklist.

Task 2.2 removed by owner decision 93 of 2026-10-08.

## 3. Vendor signatures

- [ ] 3.1 Implement the `definitive_header`, `vendor_presence` and `vendor_script` signals in
      `src/reader/cloudflare/challenge_signals.py` as pure functions over a lower-cased header map, a cookie name
      sequence and the prefix, returning at most one `FiredSignal` each with the vendor and the marker that matched.
      Verify with `tests/reader/cloudflare/test_challenge_signals.py` covering, per vendor in Decision 3, one
      positive case per marker and one negative case with a near-miss string.
- [ ] 3.2 Implement `interstitial_structure` over the prefix, including the Cloudflare element ids and classes, the
      `Ray ID:` regex carried over from today, the DataDome host, the Incapsula path and texts, the PerimeterX id and
      path, the Amazon form action, image host and input, and the Akamai reference pattern gated on status 403.
      Verify with one positive fixture per marker and a test that the Akamai pattern does not fire on a 200.
- [ ] 3.3 Assert the once-per-verdict rule: a page carrying two reCAPTCHA scripts and three Cloudflare markers fires
      `vendor_script` once and `interstitial_structure` once. Verify with a test counting fired signal ids.
- [ ] 3.4 Assert header handling is case-insensitive and tolerant: `CF-Mitigated`, `cf-mitigated` and a header map
      of `None` all behave as specified. Verify with a parametrised test.
- [ ] 3.5 Measure Amazon's live captcha page form action on the five capture locales `amazon.de`, `amazon.fr`,
      `amazon.it`, `amazon.es` and `amazon.co.jp`, and on the four spec 7 already measured (`amazon.com`,
      `amazon.pl`, `amazon.co.uk` and `amazon.se`), with a direct `curl -sS` of `/errors/validateCaptcha` and record the `action` attribute of the
      form in each response in the catalogue file's `notes` for the Amazon vendor. Keep both paths in the marker
      whatever the responses carry (owner decision 65.27 of 2026-10-04), and record which path each marketplace
      served. Verify by the recorded responses being the fixtures captured in task 8.3
      and by the corpus test firing `interstitial_structure` on each.

## 4. The verdict and the structure and shape signals

- [ ] 4.1 Add `FiredSignal` and `ChallengeVerdict` to `challenge_signals.py` as frozen dataclasses per `design.md`
      Decision 1, with the `accepted` property. Verify with a test that the dataclasses are immutable and that
      `accepted` is false for a wall with content, false for content-free clean page, and true otherwise.
- [ ] 4.2 Implement the family B status signals with the empty-body case carrying the definitive weight. Verify with
      a parametrised test over 403, 429, 503, 200 and 404 crossed with empty, small and large bodies.
- [ ] 4.3 Implement `captcha_input`, `captcha_element`, `form_dominance` and `script_only_body` with
      `lxml.html.fromstring` on the prefix, each as a pure function over the parsed tree. Verify with tests using
      minimal documents for each attribute the design names, a `form_dominance` case just above and just below the
      ratio, a `script_only_body` case with and without the `noscript`, and the `geetest_` prefix case.
- [ ] 4.4 Implement the password-input classifier so a wall verdict whose dominant form carries
      `input type="password"` has `intervention_type="login"`. Verify with a test that the type is `captcha` when the
      password input is in a form that does not dominate, and `login` when it does.
- [ ] 4.5 Implement Decision 6: a parse failure records a zero-weight `parse_failed` signal and the other families
      still run. Verify with a test feeding bytes that make `fromstring` raise, asserting the signal is recorded, a
      definitive header still yields a wall, and the word floor still applies.
- [ ] 4.6 Implement family D over one trafilatura extraction shared with the word floor, bounded by
      `CHALLENGE_SHAPE_MAX_BYTES`, with the two negative guards. Verify with tests at each boundary named in the
      configuration table, a test that a page above the shape bound contributes no family D signal and passes the
      floor, and a test that trafilatura is called exactly once per `assess`.
- [ ] 4.7 Implement `assess` as the sum of fired weights compared with the threshold, with a definitive signal
      forcing `wall` regardless of the sum. Verify with a test that a definitive header beside `rich_content` and
      `many_links` is still a wall, and that the twelve worked examples in `design.md` Decision 2 produce the scores
      and verdicts printed there at the default settings, one parametrised case per row.
- [ ] 4.8 Reimplement `is_blocked`, `has_real_content` and `is_content_accepted` as readers of `assess`, keeping
      their two-argument forms working. Verify by the existing `tests/reader/cloudflare/test_challenge_detector.py`
      passing with only the changes named in `design.md` migration step 4, each rewritten test stating its new
      expectation in its docstring.

## 5. The phrase supplement

- [ ] 5.1 Implement the normalisation function (NFKC, casefold, punctuation stripped, whitespace collapsed) in
      `challenge_signals.py` and use it from both the catalogue loader and the matcher. Verify with a test that
      `Just a moment...`, `Just a moment…` and `JUST A MOMENT` normalise to one string, and that the loader calls the
      same function rather than defining its own.
- [ ] 5.2 Capture the Cloudflare phrases: open a page that serves a Cloudflare managed challenge in a Playwright
      context with `locale` set to each of the thirty codes, record the rendered `title` and heading, and record the
      same page through `curl_cffi`. Add each captured translation to the catalogue file with its provenance. Verify by
      the corpus fixtures from task 8.2 firing `phrase_title` or `phrase_body` for every captured language, and by
      writing the answer to Open Question 3 into `design.md` with the two captures as evidence.
- [ ] 5.3 Capture the Amazon phrases from the captcha page of the five capture locales in task 3.5, extending the
      four locales spec 7 already measured, and add them with provenance. Verify by the corpus test firing the phrase on each locale fixture.
- [ ] 5.4 Implement `phrase_title` and `phrase_body` over the normalised title and the normalised visible text of the
      prefix. Verify with a test that a phrase in the title fires `phrase_title` and not `phrase_body`, that the
      Polish translation the dictionary already carries fires on a Polish fixture, and that an article quoting
      `Just a moment...` in its body with `rich_content` fired is not a wall.
- [ ] 5.5 Make `test_challenge_dictionary.py` print the phrase by language table, and commit that table into
      `docs/challenge-detection.md` under a heading that names the capture date. Verify the table's language columns match the thirty codes and its phrase rows match the sixteen
      ids.

## 6. Wiring the call sites

- [ ] 6.1 Add `verdict` to `ChallengeDetectedException` in `src/api/exceptions.py`, with the message naming the
      vendor and the score, and take `intervention_type` from the verdict. Verify with tests in
      `tests/api/test_exception_handlers.py` that the exception's existing attribute and message shape are
      preserved for callers that read them.
- [ ] 6.2 Move `curl_cffi_fetcher.py` to pass the status, the headers and the set-cookie names. Verify with a test
      that a 403 with `cf-mitigated: challenge` and a rich body raises `ChallengeDetectedException` with vendor
      `cloudflare`, and that redirect handling is unchanged.
- [ ] 6.3 Move `playwright_strategy.py` to pass the initial response's status, `all_headers()` and the context's
      cookie names on all four calls, keeping the clear-wait loop's shape. Verify with a test that a challenge that
      clears within the wait produces content, one that does not raises after the wait, and that the headers passed
      on the post-render call are those of the initial response.
- [ ] 6.4 Move `flaresolverr_strategy.py` and `crawlee_strategy.py` to pass what each has. Verify with tests that
      the FlareSolverr solution's cookie names reach the verdict and that the Crawlee result container carries the
      final status and headers.
- [ ] 6.5 Move `novnc_strategy.py`'s `_poll_captcha` to one `assess` call with the storage state's cookie names,
      deriving `page_blocked` and `cleared` from the verdict. Verify with the existing monitor tests passing and one
      new test that a rendered wall with a `cf_clearance` cookie present still captures, as today.
- [ ] 6.6 Leave `web_reader.py`'s two calls on the two-argument form and make them log the verdict at the level
      the Observability section of `design.md` specifies. Verify with a caplog test on both the `read` and the
      `read_with_links` paths.
- [ ] 6.7 Grep `src/` for `is_blocked(200,` and `is_content_accepted(200,` and confirm the only remaining
      hard-coded 200 is in `web_reader.py`. Verify by the grep output being exactly those two lines.

## 7. Observability

- [ ] 7.1 Add `CHALLENGE_SIGNALS_FIRED_TOTAL`, `CHALLENGE_VERDICTS_TOTAL` and `CHALLENGE_SCORE` to
      `src/observability/metrics.py` with the labels and buckets in `design.md`, the histogram's boundaries being the
      bucket list of the Observability section plus `CHALLENGE_SCORE_THRESHOLD` when the list does not already hold it.
      Verify with cases in `tests/observability/test_metrics.py` asserting each name, type, label set and the bucket
      boundaries at the default threshold and at an overridden one.
- [ ] 7.2 Increment them from `assess` and from the tier that calls it, with the tier name passed in. Verify with a
      test that one wall verdict with four signals produces four signal increments, one verdict increment under
      `wall` and the tier, and one histogram observation at the score.
- [ ] 7.3 Assert the vendor label is bounded: a test iterates every fixture in the corpus and asserts the set of
      `vendor` label values used is a subset of the catalogue's vendor names plus `none`.
- [ ] 7.4 Emit the verdict log line at the level the design specifies and assert with a caplog test that it carries
      the score, the vendor, the type and the signal ids, and that no line carries a cookie value, a header value
      outside the four allowlisted names, or more than the matched marker of any evidence.

## 8. The fixture corpus

- [ ] 8.1 Create `tests/fixtures/challenge_walls/manifest.json` with the schema in `design.md` Decision 7 and a
      `README.md` beside it stating the capture rules, the size bound, the trimming rule and the no-secrets rule.
      Verify with `tests/reader/cloudflare/test_challenge_corpus.py` loading the manifest and asserting every entry
      has every required field and every `path` exists.
- [ ] 8.2 Capture the Cloudflare walls: the managed challenge through `curl_cffi` with its 403 and headers, and the
      rendered challenge through Playwright in `en`, `pl`, `de`, `fr`, `ja` and `ar`. Verify by the corpus test
      asserting `definitive_header` on the curl capture and `interstitial_structure` on each rendered capture.
- [ ] 8.3 Capture the Amazon captcha page from the five capture locales in task 3.5 (`amazon.de`, `amazon.fr`,
      `amazon.it`, `amazon.es`, `amazon.co.jp`) plus the four spec 7 already measured. Verify by the corpus test asserting `interstitial_structure` and `captcha_input` on each.
- [ ] 8.4 Capture one real wall for each vendor with a public one: the Google reCAPTCHA demo page, the hCaptcha demo
      form `https://democaptcha.com/demo-form-eng/hcaptcha.html` that spec 11 uses, and a GeeTest, MTCaptcha,
      Friendly Captcha and Arkose page where a public one serves the widget as the page's whole purpose. Verify by the
      corpus test asserting each vendor's `vendor_script` and the wall verdict, and by the hCaptcha demo fixture
      asserting a wall so the contract of spec 11 is pinned by a unit test. Spec 7 has no Part 3: its human part
      moved to spec 11.
- [ ] 8.5 Build synthetic fixtures, marked `synthetic: true`, for Akamai, Imperva, Kasada, PerimeterX, DDoS-Guard
      and AWS WAF from the cited markers alone. Verify by the corpus test asserting the wall verdict and by a test
      that every synthetic entry is listed in `design.md` Open Question 4.
- [ ] 8.6 Add a `notes` rule to the corpus README: when a spec 7 run records a real wall from a vendor that has a
      synthetic fixture, the run's raw response is captured into the corpus and the synthetic entry is replaced in
      the same commit. Verify by the README carrying the rule and the manifest test rejecting two entries for one
      vendor where one is synthetic.
- [ ] 8.7 Capture the counterexamples: a blog post with a reCAPTCHA comment form, `nowsecure.nl`, one vendor page
      hosting its widget beside real content, a login page with a captcha, Wikipedia articles in `en`, `pl`, `de`,
      `ja` and `ar`, a 404 page, a 403 with a large real body, and the raw HTML of `quotes.toscrape.com/js/` as the
      script-only shell. Verify by the corpus test asserting `wall` false on each except the login page, which
      asserts `wall` true and type `login`, and `has_content` false on the shell.
- [ ] 8.8 Enforce the corpus rules: every vendor has a wall fixture, every `vendor_script`, `interstitial_structure`
      and `definitive_header` marker is fired by at least one fixture, every phrase translation is fired by at least
      one fixture, no file exceeds 200 kilobytes, and no fixture contains a catalogue cookie name followed by `=` and
      a value. Verify by each rule being its own test that fails when one fixture or one marker is removed.

## 9. Verification gates

- [ ] 9.1 Make the corpus test print the fixture, score, margin and fired-signal table, with fixtures within
      twenty points of the threshold under their own heading, and paste that table into `design.md` under Open
      Question 1 with the run date. Verify the table has one row per manifest entry and that every wall has a
      positive margin and every counterexample a negative one.
- [ ] 9.2 Run the full gate and record the figure:
      `.venv/Scripts/python.exe -m pytest --cov=src --cov-branch --cov-report=term-missing --cov-fail-under=100`
      on Windows, or the same through `.venv/bin/python` on Linux and macOS. Verify it
      passes at 100 percent branch coverage with no `# pragma: no cover` and no `# noqa` added anywhere in this
      change.
- [ ] 9.3 Run `.venv/Scripts/python.exe -m ruff check .` and `.venv/Scripts/python.exe -m mypy src tests`
      (`.venv/bin/python` on Linux and macOS). Verify both are clean, with
      no suppression added.
- [ ] 9.4 Measure the cost of `assess` on the largest fixture in the corpus and on the largest page in spec 7's
      matrix, with `time.perf_counter` around one hundred calls each, and record both figures in `design.md`
      Decision 8. Verify the per-call figure on the largest fixture is under 50 milliseconds, and if it is not, bound
      it by lowering the default of the setting `CHALLENGE_SHAPE_MAX_BYTES` in `config.py`, in the two compose lines and
      the two `.env.example` lines of task 1.4, in the bundle README row and in the `docs/configuration.md` row in the
      same edit, and say so in the table.

## 10. Documentation and decisions

- [ ] 10.1 Add the two existing `CHALLENGE_*` settings `docs/configuration.md` does not list and every setting of task
      1.1 to the tables in `apps/ascend-web-hunter/AGENTS.md`, `README.md` and `docs/configuration.md`, the rows of
      `docs/configuration.md` in the same commit as the settings, each new row with its default and its description
      ending with "Added by `detect-challenge-walls-in-any-language`." (owner rule 98 of 2026-10-08, the per-service
      configuration reference), and add `docs/challenge-detection.md` describing the families, the weights, the
      threshold, the seven tuning settings, the weight settings with the validator rules of task 1.2 and the warning
      that a changed weight needs the corpus test of task 9.1 run again, and the capture rules, linked from
      `docs/README.md`. Verify each of the two existing names and every name of task 1.1 appears in all three tables,
      that every row this change adds to `docs/configuration.md` ends with "Added by
      `detect-challenge-walls-in-any-language`.", and that the new page is reachable from the documentation map.
- [ ] 10.2 Write `docs/architecture/decisions/ADR-014-scored-challenge-detection.md` in the existing ADR format:
      the scoring model, the family order, the definitive signals, the guard, the one catalogue file and its
      provenance rule, and the corpus as the admission rule, with the rejected alternatives from `design.md`
      Decisions 1, 2 and 4. Verify the file follows the structure of ADR-003 and ADR-008 and is added to the
      decisions `README.md` index, and that ADR-013 is the sibling change's record and is not touched.
- [ ] 10.3 Amend ADR-001 rather than superseding it: its Related section names `is_blocked`, `is_login_required` and
      `is_login_redirect_url`, and its Decision section says `ChallengeDetectedException` short-circuits to NoVNC.
      Point the Related entry at `assess` and the verdict, dated, and leave the rest intact. Verify ADR-001's status
      line and its other content are unchanged.
- [ ] 10.4 Add two rows to `docs/DEFECT_REGISTER.md`: one for the false negative spec 7's "pending anti-bot fix"
      paragraph describes, moved to Fixed with this change's commit once it lands, and one Found and not fixed row
      for `ERROR_KEYWORDS` failing validation on an article that mentions a captcha, with the measurement that shows
      it. Verify both rows follow the register's column layout and that no other row is touched.
- [ ] 10.5 Bump `version` in `apps/ascend-web-hunter/pyproject.toml`, the version line in
      `apps/ascend-web-hunter/AGENTS.md` and the version in `apps/ascend-web-hunter/docs/architecture/arc42/02-constraints.md`
      from `0.0.9` (set by `open-several-novnc-windows-at-once`) to `0.0.10`, and add one `## [0.0.10]` entry at the top
      of `apps/ascend-web-hunter/CHANGELOG.md` describing the scored challenge verdict (owner decision of 2026-10-08, one
      named version per change, in build order). The version moves in all four files together, per the register's F44
      rule. Verify `pyproject.toml`, `AGENTS.md` and the arc42 page read `0.0.10` and the CHANGELOG holds exactly one
      `## [0.0.10]` heading, the topmost version heading.

## 11. End-to-end coverage

- [ ] 11.1 Measure three candidate pages for the "Widgets that are not walls" group with a direct fetch and a word
      count of the trafilatura extraction, from the candidates `friendlycaptcha.com`, `mtcaptcha.com`,
      `hcaptcha.com`, the GeeTest adaptive captcha demo page and Google's reCAPTCHA about page. A candidate qualifies
      when it renders a catalogue widget and extracts at least 150 words. Record the three chosen URLs, their word
      counts and the date in the run record and in the spec's row notes. Verify by the three figures being present
      before the rows are written.
- [ ] 11.2 In `apps/ascend-web-hunter/e2e/testing/7-authenticated-realworld-scraping-test.md`, add a matrix group
      "Challenge walls in other languages" with rows `aa` to `ae`: `https://www.amazon.de/errors/validateCaptcha`,
      `https://www.amazon.fr/errors/validateCaptcha`, `https://www.amazon.it/errors/validateCaptcha`,
      `https://www.amazon.es/errors/validateCaptcha` and `https://www.amazon.co.jp/errors/validateCaptcha`, each
      expected `intervention` and gated. Add a "Widgets that are not walls" group with rows `af` to `ah` for the three
      pages from task 11.1, each expected `success` and gated, with the word count that qualified them in the row.
      Verify by a direct fetch of each `aa` to `ae` URL returning the captcha page and not a redirect to the
      storefront, dropping any row whose marketplace redirects rather than weakening it to best-effort.
- [ ] 11.3 Replace the "Dependency on the pending anti-bot fix" paragraph with a statement that the fix is this
      change, and keep rows v, w, x and y best-effort and content-gated. Verify by re-reading the Contract section
      and the retail section and confirming nothing in them still describes a 200 carrying an interstitial as the
      deployed behaviour.
- [ ] 11.4 Add the Bruno requests `realworld-aa-amazon-de-captcha.yml` through `realworld-ae-amazon-jp-captcha.yml`
      asserting HTTP 428, `code="human_intervention_required"` (the problem body of `add-ascend-python-common`,
      owner answer 60.2 of 2026-10-03) and a non-empty `vnc_url`, and
      `realworld-af-...` through `realworld-ah-...` asserting HTTP 200, `status="success"` and the page's own canary
      phrase. Verify each runs with `bru run "<file>" --env ascend-local` against a live stack.
- [ ] 11.5 Add a note to the spec's intervention handling section that rows `aa` to `ae` each spawn a NoVNC monitor
      that no human is expected to solve. State as a prerequisite that the matrix runs with
      `NOVNC_MAX_CONCURRENT_FLOWS` of at least 5, which the sibling change `open-several-novnc-windows-at-once`
      provides and which is built before this change. Write it by replacing in place the "at least 4" prerequisite
      that `open-several-novnc-windows-at-once` task 11.1 wrote, so spec 7 states one cap rule. Verify against the
      Concurrency section, which must say the five rows mutate the session keys for five Amazon marketplaces, and
      that spec 7 and its template name the cap once, as at least 5.
- [ ] 11.6 Update `e2e/testing/templates/7-authenticated-realworld-scraping-tasks.template.md` with rows `aa` to
      `ah` and the changed paragraph. Verify the template's row set matches the spec's row set exactly, item for item.
- [ ] 11.7 Update `e2e/README.md`'s capability table row for spec 7 to name the two new groups. Verify the row still
      describes every group the spec carries.
- [ ] 11.8 Owner request of 2026-10-04: prove the verdict end to end without depending on what a live site serves that
      day. Write the new automated spec `apps/ascend-web-hunter/e2e/testing/<N>-challenge-verdicts-test.md` (`<N>` the
      next free number at implementation time) and its template, reading pages of the shared e2e fake site under its
      allowed name `e2e-fake-site` (design D11 and D12 of `add-web-search-scraping-e2e`, owner answer 67.3 of 2026-10-04)
      through
      `POST /api/v2/web/read`. The fake site pages are the ones task 11.12 adds or rebuilds, and the unit test of task
      11.12 runs `assess` over the same page files, so the end-to-end rows and the unit tests judge the same markup.
      Rows, their fake site paths and their gated verdicts:
      - `/wall-ko`, a site's own captcha page in Korean with no vendor marker: HTTP 428 with `intervention_type`
        `captcha`
      - `/wall-tr`, a Turkish login form with a password input and a captcha input: HTTP 428 with `intervention_type`
        `login`
      - `/wall-vendor-thin`, a catalogued vendor script on a thin page: HTTP 428
      - `/wall-header`, a 403 carrying the definitive `cf-mitigated` challenge header beside a rich body: HTTP 428
      - `/wall-oversized`, a wall page larger than `CHALLENGE_DETECTION_MAX_BYTES`: HTTP 428
      - `/captcha-wall`, a blog post of at least 150 words with a catalogued widget under its comment form: HTTP 200
        `status` `success` with its canary sentence
      - `/article-ja` and `/article-ar`, a Japanese article and an Arabic article with no vendor marker: HTTP 200
        `success` with their canary sentences
      - `/prose-captcha`, a page with the word `captcha` only in its prose: HTTP 200 `success`
      - `/rich-403`, a 403 with a rich body and no other signal: any answer but HTTP 428
      Every 428 passes the problem body check of design D13 of
      `add-web-search-scraping-e2e` with a non-empty `vnc_url`. After the rows, `/metrics` shows
      `challenge_verdicts_total{verdict="wall"}` grown by the number of wall rows and `{verdict="content"}` grown by at
      least the number of content rows, and every `vendor` label value of `challenge_signals_fired_total` is a
      catalogue vendor name or the fixed label of the observability spec. Cleanup waits until
      `GET /api/v2/session/interventions` reports `active_flows` 0. Concurrency: each wall row opens a NoVNC flow, so the
      spec does not run beside the concurrent intervention spec of `open-several-novnc-windows-at-once` or any spec
      that can answer a 428. Verify every assertion is an HTTP status, a response body or `/metrics`, never a log line.
- [ ] 11.9 Add the Bruno requests of task 11.8 in the folder
      `docs/api/request/AscendAI/web-hunter/testing/challenge-verdicts/`, one request per row
      (`wall-own-captcha-korean.yml`, `wall-login-turkish.yml`, `wall-vendor-script-thin.yml`,
      `wall-definitive-header.yml`, `wall-oversized.yml`, `content-widget-under-article.yml`,
      `content-article-japanese.yml`, `content-article-arabic.yml`, `content-captcha-word-in-prose.yml`,
      `content-403-rich-body.yml`) plus `metrics-challenge.yml`, each with its assertions in the request file. Verify
      each runs with `bru run "<file>" --env ascend-local` against a live stack.
- [ ] 11.10 Move the live check of task 12.4 into spec 7 as gated rows `ai` (a Japanese Wikipedia article) and `aj` (an
      Arabic Wikipedia article), each expected `success` with a canary phrase measured from the article on the day the
      rows are written, with their Bruno requests `realworld-ai-wikipedia-ja.yml` and `realworld-aj-wikipedia-ar.yml`
      and the matching template rows. Verify the template row set matches the spec row set item for item.
- [ ] 11.11 Add the new spec of task 11.8 to the spec lists, counts and run order of scenarios 1 to 6 and of the
      ascend-web-hunter service suite in `docs/E2E_RUN_SCENARIOS.md`, as a spec that runs alone after the concurrent
      intervention spec, and add it to `e2e/README.md`'s capability table and `e2e/testing/README.md`'s ordered list.
      Verify every count in the document still adds up.
- [ ] 11.12 Make the shared fake site serve the pages of task 11.8 from one place and judge them with a unit test, before
      task 11.8 is written. Move the HTML of `/wall-ko`, `/wall-tr`, `/wall-header`, `/captcha-wall`, `/article-ja`,
      `/article-ar`, `/prose-captcha`, `/rich-403` and `/turnstile-wall` (the page of
      `open-several-novnc-windows-at-once` task 11.9) out of `apps/ascend-web-hunter/e2e/fake-site/app.py` into one
      file each under `apps/ascend-web-hunter/e2e/fake-site/pages/`, served unchanged by `app.py` with the status and
      headers each serves today. Add `/wall-vendor-thin` (a thin page whose only marker is one catalogued
      `vendor_script` of a vendor in the catalogue file of task 2.1, named in the fixtures README) and `/wall-oversized` (a
      wall whose marker sits inside the first `CHALLENGE_DETECTION_MAX_BYTES` and whose body is longer than that).
      Rebuild `/wall-ko`, which today holds one Korean sentence and scores below the 428 threshold, into a page with a
      captcha image, a text input for the answer and the Korean phrase of the catalogue file, still with no vendor
      marker. Rebuild `/captcha-wall` into a blog post of at least 150 words whose comment form carries a catalogued
      widget, keeping its canary sentence. Write `tests/reader/cloudflare/test_fake_site_verdicts.py`, which runs
      `assess` over every file of that folder with its served status and headers and asserts the verdict of task 11.8,
      and `wall` true for `/turnstile-wall`. List every page and its canary in
      `apps/ascend-web-hunter/e2e/fixtures/README.md`. Verify the unit test passes and fails when one page is turned
      into the other verdict, the image builds, and each page answers its documented status and `Content-Type`.

## 12. Live verification

- [ ] 12.1 Rebuild and restart the scrapper stack from the repository root against the main compose file, then
      confirm the container is running the new image. Verify with `docker compose ps ascend-web-hunter` and by
      reading the startup banner.
- [ ] 12.2 Read each Amazon locale captcha page through `POST /api/v2/web/read` and confirm HTTP 428 with a
      `vnc_url`, then read `/metrics` and confirm `challenge_signals_fired_total` carries `interstitial_structure`
      with `vendor="amazon"` and `challenge_verdicts_total` carries `verdict="wall"`. Verify against the metrics
      output rather than the log.
- [ ] 12.3 Read the three widget pages from task 11.1 and confirm HTTP 200 with `status="success"` and content that
      carries the page's own text, and confirm `challenge_verdicts_total` counted them as `content`. Verify against
      the response bodies and the metrics output.
- [ ] 12.4 Read a Wikipedia article in Japanese and one in Arabic and confirm both are `success` with the article
      text, so the guard is proven on non-Latin pages live. Verify against the response bodies.
- [ ] 12.5 Ask the owner which run scenario of `docs/E2E_RUN_SCENARIOS.md` to use, then re-run e2e spec 7 in full,
      Part 1 fanned out per the spec's concurrency rules (spec 7 has no Part 3 since its human part moved to spec 11),
      and confirm rows `aa` to `aj` return their gated verdicts and rows v, w, x and y return a terminal verdict with no
      interstitial marker on any success. Then run the new spec of task 11.8 alone. Verify by the run records written
      under `e2e/testing/runs/`, and attach them to this change.
