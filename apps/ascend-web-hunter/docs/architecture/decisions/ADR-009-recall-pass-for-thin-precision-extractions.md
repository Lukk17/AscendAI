# ADR-009: A recall pass when the precision extraction is thin against the page

## Status

Accepted, 2026-09-10

## Context

`extract_text_with_fallback` in `src/reader/extraction.py` is the function every text-mode read returns its
`content` from. It ran `trafilatura.extract(html)` in the library's default mode, which is tuned for article pages,
and only fell back to readability-lxml when the result was shorter than `READABILITY_FALLBACK_MIN_CHARS` (200
characters, ADR-007). A listing page can clear that absolute floor while losing most of what a caller wanted.

Measured on 2026-09-10 on `https://books.toscrape.com/`: the default pass returned 319 characters made of prices
and stock lines and dropped every book title. `trafilatura.extract(html, favor_recall=True)` on the same page
returned 1143 characters including the titles. BeautifulSoup `get_text` after `remove_noise_tags` returned 1851
characters. The readability fallback never ran because 319 is above 200, and readability's own output on that page
(568 characters of HTML) would not have contained the titles either.

Trafilatura's documentation names this case. Its Python usage page says to use `favor_recall` "when parts of your
documents are missing", its troubleshooting page says the tool "is geared towards article pages, blog posts, and
main text content" and that "results vary on link lists, galleries, or catalogs", and its benchmark page scores
recall mode slightly below the default on an article corpus (precision 0.899 against 0.906, recall 0.939 against
0.943). None of its pages, its internal fallback rules (readability replaces its own output only when at least twice
as long, jusText only when three times as long, both compared extraction to extraction), or Mozilla Readability's
absolute 500 character `charThreshold` gives a ratio of extracted text to page text, so the threshold below is
derived from measurements.

## Decision

### D1, two passes, the second only when the first is thin against the page

`extract_text_with_fallback` and `extract_structured` share one gate, `_longer_of_two_passes`. The text path first
runs `trafilatura.extract(html)` as before. It then measures the page's plain
text as BeautifulSoup `get_text(" ", strip=True)` after `remove_noise_tags` (the same helper tier 1 and the link
annotator already use). When the precision result is shorter than `CONTENT_RECALL_FALLBACK_RATIO` times that plain
text length, it runs `trafilatura.extract(html, favor_recall=True)` and keeps whichever of the two results is
longer. The readability-lxml fallback of ADR-007 then applies to that result unchanged. A page with no plain text
never triggers the second pass, and the comparison is a multiplication, so there is no division.

### D2, the threshold is 0.75 and is a setting

`CONTENT_RECALL_FALLBACK_RATIO` in `src/config/config.py` defaults to `0.75`, constrained to the closed interval 0 to
1, where 0 never runs the second pass and 1 always runs it. On 2026-09-10 the precision pass covered 0.90 to 1.00 of
the plain text on nine article pages (gnu.org, peps.python.org, the docs.python.org tutorial, the kernel.org coding
style guide, paulgraham.com, danluu.com, MDN, keepachangelog.com, trafilatura's own documentation) and 0.19 to 0.87
on twelve same-day news articles from the Guardian, Ars Technica, TechCrunch, The Verge, the BBC and Wired, where
the recall pass returned identical text or, on one Ars Technica article, 1924 characters against 8956. Where the
precision pass dropped real content it covered 0.13 to 0.17 (three books.toscrape.com listings, titles restored by
the recall pass) and 0.61 (quotes.toscrape.com page 2, 29 lines restored). 0.75 is the midpoint between the highest
measured defective ratio, 0.61, and the lowest ratio at which the precision pass was already complete, 0.90. The
news articles below 0.75 pay for a second pass that changes nothing, which measured at 25 to 33 milliseconds on
pages of 50 to 390 kilobytes, against a per-tier `EXTRACT_TIMEOUT` of 30 seconds.

### D3, the longer result wins

The second pass replaces the first only when it is longer. The Ars Technica measurement is why: recall mode can
return far less than the default mode, so returning the recall result unconditionally would trade one loss for
another.

## Alternatives Considered

### Alternative 1: run `favor_recall=True` everywhere
- Pros: one pass per page, no threshold, no plain text measurement.
- Cons: trafilatura's own benchmark scores recall mode below the default on articles, and on one of twelve news
  articles measured the same day recall mode returned 1924 characters where the default returned 8956. The
  documentation positions recall mode as the remedy for missing content, not as the default.
- Why not: it fixes listings by degrading the article pages that are the bulk of what the reader is asked for.

### Alternative 2: lower `READABILITY_FALLBACK_MIN_CHARS` or compare against readability-lxml
- Pros: no new setting.
- Cons: readability-lxml returned 568 characters of HTML on the books page without the titles, so no floor makes
  it the right fallback here. An absolute floor also cannot tell a short page that was fully extracted from a long
  page that was mostly dropped.
- Why not: the defect is relative to the page, so the gate has to be relative to the page.

### Alternative 3: return trafilatura's `html2txt` when the ratio is low
- Pros: recovers everything, including the titles.
- Cons: `html2txt` is the library's documented last resort that "returns all text including boilerplate", scored at
  precision 0.531 on its benchmark. The reader would hand callers navigation and footers on every listing page.
- Why not: the recall pass restored the titles on every measured listing without that cost.

## Consequences

### Positive
- Listing and catalogue pages return their item titles in text mode, with the article path unchanged above the
  threshold.
- The threshold is one setting with a documented derivation and can be retuned from measurements without a code
  change.

### Negative
- Pages below the threshold pay one more trafilatura pass and one BeautifulSoup parse, measured at tens of
  milliseconds each.
- The gate is a length ratio, not a content check. It cannot tell a page where the precision pass dropped content
  from one where the remainder is sidebars, so it fires on some news articles for no gain.

### Risks
- A listing whose precision pass lands above 0.75 while still dropping items stays broken. The highest such ratio
  measured was 0.61, on quotes.toscrape.com page 2.
- The structured path, `extract_structured`, runs the same two passes in JSON mode through the shared gate, so
  when the two passes disagree on metadata (title, author, date) the caller gets the metadata of whichever pass
  won on content length.

## Related

- `src/reader/extraction.py`, `_longer_of_two_passes`, `_plain_text_length`, `_extract_text_with_recall_fallback`,
  `extract_text_with_fallback`, `extract_structured`.
- `src/config/config.py`, `CONTENT_RECALL_FALLBACK_RATIO`.
- `tests/fixtures/books_toscrape_index.html`, `tests/fixtures/gnu_free_sw_article.html`, the saved pages the tests
  run against.
- [ADR-007](ADR-007-structured-output-and-readability-fallback.md), the readability-lxml fallback that still applies
  after the two passes.
- [docs/configuration.md](../../configuration.md), the derivation of the default.
