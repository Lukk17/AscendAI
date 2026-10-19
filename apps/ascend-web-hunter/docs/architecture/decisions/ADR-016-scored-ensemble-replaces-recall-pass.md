# ADR-016: Scored ensemble replaces the readability recall pass

## Status

Accepted, 2026-10-19. Supersedes ADR-009 (the status-line update on ADR-009 itself is pending an owner
decision and is not part of this change).

## Context

`extract_text_with_fallback` in `src/reader/extraction.py` is the function every text-mode read returns its
`content` from. Since ADR-009 it ran trafilatura's default precision pass and only ran a second pass with
`favor_recall=True` when the first was shorter than `CONTENT_RECALL_FALLBACK_RATIO` (0.75) of the page's
plain text. The recall pass runs readability-lxml only below a threshold, so on a page where readability
was better but trafilatura was not thin, the worse result still won: the threshold decides, not quality.
The defect register case F53 (books.toscrape.com listings) showed the shape from the other side: trafilatura
kept prices and stock lines and dropped every title while clearing every absolute floor.

## Decision

Both extractors run on the same HTML for every extraction, in `extract_structured` and in
`extract_text_with_fallback` alike. Each result is scored by text length times (1 minus link density)
times (1 minus boilerplate ratio), and the higher scoring result wins. Ties go to trafilatura, the
incumbent. The scoring helpers live beside the extractors in `src/reader/extraction.py`:
`_trafilatura_structured`, `_readability_extract` and `_ensemble_score`.

## Alternatives Considered

### Keep the recall pass and retune its threshold

- Pros: a smaller diff, no second extractor run on every page.
- Cons: a threshold can only ask "is trafilatura thin", never "is readability better". The F53 listing
  pages clear any floor while losing the titles, so no threshold fixes them.
- Why not: the defect is structural, not a tuning problem.

### Run readability only and drop trafilatura

- Pros: one extractor, no scoring.
- Cons: trafilatura wins most article pages (nine article pages measured 0.90 to 1.00 of plain text on
  the default pass), and readability alone would regress them.
- Why not: it trades one blind spot for another.

## Consequences

### Positive

- Every page gets the better of the two extractors, measured rather than guessed.
- The recall-pass settings (`READABILITY_FALLBACK_MIN_CHARS`, `CONTENT_RECALL_FALLBACK_RATIO`) have no
  reader left and leave the configuration in the change that applies this record.

### Negative

- Two extractor runs per page instead of one in the common case, paid in CPU on every read.

### Risks

- The boilerplate marker list in `_ensemble_score` is heuristic and drifts with web design fashion. It is
  covered by fixture tests, so drift shows up as a test failure, not a silent regression.
