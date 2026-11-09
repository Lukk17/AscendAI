# ADR-014: Scored challenge detection with a fixture corpus

## Status

Accepted - 2026-10-19

## Amendment, 2026-11-07 (is_content_accepted removed)

D1 changes on one name: `ChallengeDetector.is_content_accepted` is removed.
It had no caller left, because the read path (`src/reader/web_reader.py`),
`src/reader/strategies/browser_read.py` and the NoVNC monitor
(`src/reader/strategies/novnc_strategy.py`) read the verdict's `accepted`
field directly. `is_blocked` and `has_real_content` keep their names and
read the verdict. The rest of this record is unchanged.

## Amendment, 2026-11-07 (login landing rule, block phrase and prefix cuts)

D1 gains one rule outside the score. A read whose final address has a path
segment from the catalogue's `login_path_segments` while the requested
address has none, and that carries a second login sign (a query parameter
from `login_return_parameters` on the final address, or a password input on
the page), is a login wall in every read tier at any size. The reason is
measured: an anonymous read of `https://old.reddit.com/r/programming/` is
redirected to `https://old.reddit.com/login/?reason=lor2&dest=...`, a 200
page titled "Welcome to Reddit" that scores 60 and that no title or password
rule caught, so the browser tier returned it as content. The address is the
evidence the page itself does not carry. The second sign keeps help pages
such as `/en/login/reset-password` out. The verdict of this rule carries
`login_landing`, which makes the read ladder go straight to the NoVNC tier,
or end with `reason` `login_required` when no human may be asked, instead of
running every anonymous tier into the same login page. The NoVNC monitor
applies the rule, and its login redirect address check, only until its
window has seen a login wall.

D2 family E gains the body phrase `generic_blocked_by_network_security`,
and the prefix that families C and E parse is now taken after emptying
inline `<style>` bodies and cutting `data:` attribute values to `data:`.
The corpus fixture filed as a 403 with a large real body was Reddit's
"You've been blocked by network security" page, whose sentence sits at byte
189316, behind inline styles and an 87552-byte inline image. It is now the
wall `reddit-network-block-403.html` (`status_large_body` 20 plus
`phrase_body` 30 plus three shape signals, 110 in total). D4 keeps its rule that the corpus
holds a 403 with a large real body: no public article served with 403 was
found on 2026-11-07, so the e2e fake-site page `rich-403.html` holds that
guard and the gap is listed in the corpus README.

## Context

`ChallengeDetector.is_blocked` matched substrings from a hand-typed
`challenge_dictionary.json` over a 50 kilobyte prefix, plus a `Ray ID:` regex
and three weak substrings gated on page size. No call site passed the
response headers, so the one language-independent signal every fetch already
had was thrown away. The dictionary held four script signatures, eleven
phrases in two languages, one structural marker whose path was not the path
Amazon serves, and five English login title patterns. A wall in any other
language, from any vendor the dictionary did not know, was returned to the
caller as a successful page read. A page carrying a real article beside a
captcha widget was a wall. Nine call sites combined three booleans with
`and` and `not`, and each new signal would have to be threaded through all
nine with a decision about how it combines.

## Decision

### D1 - One scored verdict replaces the booleans

`assess(status_code, html, headers, cookie_names)` in
`src/reader/cloudflare/challenge_signals.py` returns a frozen
`ChallengeVerdict`: score, threshold, signals, vendor, wall (`score >=
threshold`, or a definitive signal fired), `has_content` (the
`VALIDATION_MIN_WORDS` floor, unchanged) and `intervention_type` (`login`
when the dominant form has a password input, else `captcha`). A signal fires
at most once per verdict. `is_blocked`, `has_real_content` and
`is_content_accepted` keep their names and read the verdict.

### D2 - Five signal families, language-independent first

Family A (vendor signatures: `definitive_header` 200,
`interstitial_structure` 80, `vendor_script` 60, `vendor_presence` 30) and
family B (HTTP evidence: `status_empty_body` 200, `status_small_body` 50,
`status_large_body` 20) come before family C (page structure over element
names and attribute values only), family D (content shape over one
trafilatura extraction) and family E (catalogue phrases, matched after
normalisation, as a supplement). The threshold is 100: no non-definitive
signal reaches it alone, and the two definitive signals weigh twice the
threshold so no guard combination cancels them. Weights and tuning values
are settings (`CHALLENGE_WEIGHT_*`, `CHALLENGE_SCORE_THRESHOLD` and the six
other tuning values), validated so no single non-definitive signal can
decide a wall and the guards can only subtract.

### D3 - Every marker carries its source, unverified markers stay out

`challenge_dictionary.json` is the one maintained file: vendors with the
marker table, each marker with its signal, source URL and verified-on date;
sixteen phrase ids with canonical English and a provenance per translation;
`login_title_patterns` carried over verbatim. Markers no vendor page or
maintained detector confirmed stay out. The loader normalises every phrase
at load with the same function the matcher uses, and fails loudly on a
missing or malformed file instead of falling back to empty lists.

### D4 - The corpus is the admission rule

`tests/fixtures/challenge_walls/` with `manifest.json` is the contract: a
marker without a fixture that fires it is not admitted, and a changed
weight or threshold is re-verified by the corpus margin table before the
change is called done. Fixtures carry no cookie values, tokens or personal
data; synthetic fixtures are marked and replaced with real captures when a
spec 7 run records one.

## Alternatives Considered

### Alternative 1: A boolean per new signal beside the existing ones
- **Pros**: Smaller diff to the call sites.
- **Cons**: Nine call sites already combine three booleans with `and` and
  `not`; each new signal would need threading through all nine with a
  decision about how it combines.
- **Why not**: A score is one number with one comparison, and the
  combination rule lives in one place.

### Alternative 2: A machine-learned classifier
- **Pros**: Could catch vendors the catalogue does not name.
- **Cons**: It would need the corpus this change builds before it could be
  trained; it could not say which marker decided a page; a vendor changing
  its markup would degrade it silently.
- **Why not**: The catalogue plus a score can be read, tested and corrected
  by hand.

### Alternative 3: Translating the phrases with machine translation
- **Pros**: Instant coverage in every language.
- **Cons**: It produces a plausible sentence that is not the sentence the
  vendor renders; a phrase that almost matches is a phrase that never
  matches.
- **Why not**: A translation enters the file only when captured from a
  served wall, with its provenance.

## Consequences

### Positive
- A wall from any catalogue vendor, and a site's own captcha from no vendor
  at all, is a wall in any language; a page carrying a real article beside
  a captcha widget is content.
- One score and one threshold shared by every tier and the monitor, with the
  deciding signals, the margin and the vendor visible in the log line and
  the metrics.
- Weights and the threshold are operable settings with a validator, tuned
  against the corpus rather than the code.

### Negative
- A page under 150 words whose main feature is a captcha widget is treated
  as a wall, and a human opens it once.
- Phrase coverage starts nearly empty outside English: a language with no
  captured translation for a phrase simply has no entry until a wall
  carrying it is captured.

### Risks
- **The corpus goes stale as vendors change markup.** A marker the corpus
  no longer fires is a silent hole until a live page proves it. The
  admission rule and the spec 7 live rows are the mitigation, not a fix.

## Related

- `src/reader/cloudflare/challenge_signals.py` - `assess`, `FiredSignal`, `ChallengeVerdict`.
- `src/reader/cloudflare/challenge_detector.py` - `is_blocked`, `is_content_accepted`, `is_login_required`.
- `src/reader/cloudflare/challenge_dictionary.json` - the one maintained catalogue file.
- `docs/challenge-detection.md` - families, weights, threshold, capture rules, phrase table.
- [ADR-001](ADR-001-multi-tier-extraction-strategy.md) - the tier ladder the verdict feeds.
- [ADR-003](ADR-003-novnc-ngrok-captcha-intervention.md) - the NoVNC end the verdict escalates to.
